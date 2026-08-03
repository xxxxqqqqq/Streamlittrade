"""策略、数据集、训练实验和模型仓库API。"""

from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.app.db.session import get_db_session
from backend.app.infrastructure.outbox import add_outbox
from backend.app.models.job import Job
from backend.app.models.data_catalog import FeatureSnapshot
from backend.app.models.research import Dataset, Experiment, ModelVersion, PredictionRun, Strategy
from backend.app.schemas.research import (
    DatasetCreate, DatasetRead, ExperimentCreate, ExperimentRead, ModelRead,
    ModelRollbackRequest, ModelStageUpdate, PredictionCreate, PredictionRead,
    ProductionPredictionCreate, StrategyCreate, StrategyRead, TaskSubmission,
)
from backend.app.core.security import get_current_user, require_admin
from backend.app.models.identity import AuditLog, User
from backend.app.core.projects import ProjectContext, get_project_context
from backend.app.services.predictions import create_prediction_job

router=APIRouter(tags=["research"], dependencies=[Depends(get_current_user)])

@router.post("/strategies",response_model=StrategyRead,status_code=201)
async def create_strategy(body:StrategyCreate,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    # slug 在项目内代表一条策略演进链，每次提交自动产生下一版本。
    latest=await session.scalar(
        select(Strategy)
        .where(Strategy.project_id==context.project.id,Strategy.slug==body.slug)
        .order_by(Strategy.version.desc())
        .with_for_update()
    )
    item=Strategy(project_id=context.project.id,version=(latest.version+1 if latest else 1),**body.model_dump())
    session.add(item); await session.commit(); await session.refresh(item); return item

@router.get("/strategies",response_model=list[StrategyRead])
async def list_strategies(session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    return list((await session.scalars(select(Strategy).where(Strategy.project_id==context.project.id).order_by(Strategy.created_at.desc()))).all())

@router.post("/datasets",response_model=TaskSubmission,status_code=202)
async def create_dataset(body:DatasetCreate,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    if body.data_source=="feature_snapshot":
        snapshot=await session.scalar(
            select(FeatureSnapshot).where(
                FeatureSnapshot.id==body.feature_snapshot_id,
                FeatureSnapshot.project_id==context.project.id,
            )
        )
        if snapshot is None or snapshot.status!="ready":
            raise HTTPException(409,"必须选择当前项目内已就绪的特征快照")
    jid,did=uuid4(),uuid4(); spec=body.model_dump(mode="json")
    job=Job(id=jid,owner_id=context.user.id,project_id=context.project.id,kind="dataset",status="queued",progress=0,payload={"dataset_id":str(did)})
    item=Dataset(id=did,project_id=context.project.id,job_id=jid,feature_snapshot_id=body.feature_snapshot_id,name=body.name,status="queued",specification=spec)
    session.add(job);await session.flush();session.add(item);add_outbox(session,job,"backend.app.workers.research.build_dataset");await session.commit()
    return TaskSubmission(job_id=jid,resource_id=did)

@router.get("/datasets",response_model=list[DatasetRead])
async def list_datasets(session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    return list((await session.scalars(select(Dataset).where(Dataset.project_id==context.project.id).order_by(Dataset.created_at.desc()))).all())

@router.post("/experiments",response_model=TaskSubmission,status_code=202)
async def create_experiment(body:ExperimentCreate,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    dataset=await session.scalar(select(Dataset).where(Dataset.id==body.dataset_id,Dataset.project_id==context.project.id))
    if not dataset or dataset.status!="ready": raise HTTPException(409,"数据集尚未就绪")
    jid,eid=uuid4(),uuid4(); job=Job(id=jid,owner_id=context.user.id,project_id=context.project.id,kind="training",status="queued",progress=0,payload={"experiment_id":str(eid)})
    item=Experiment(id=eid,project_id=context.project.id,job_id=jid,**body.model_dump())
    session.add(job);await session.flush();session.add(item);add_outbox(session,job,"backend.app.workers.research.train_experiment");await session.commit()
    return TaskSubmission(job_id=jid,resource_id=eid)

@router.get("/experiments",response_model=list[ExperimentRead])
async def list_experiments(session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    return list((await session.scalars(select(Experiment).where(Experiment.project_id==context.project.id).order_by(Experiment.created_at.desc()))).all())

@router.get("/models",response_model=list[ModelRead])
async def list_models(session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    return list((await session.scalars(select(ModelVersion).join(Experiment,Experiment.id==ModelVersion.experiment_id).where(Experiment.project_id==context.project.id).order_by(ModelVersion.created_at.desc()))).all())


@router.patch("/models/{model_id}/stage",response_model=ModelRead)
async def update_model_stage(
    model_id:UUID,
    body:ModelStageUpdate,
    session:AsyncSession=Depends(get_db_session),
    admin:User=Depends(require_admin),
    context:ProjectContext=Depends(get_project_context),
):
    """执行受控模型晋级；禁止绕过验证直接发布生产。"""
    model=await session.scalar(select(ModelVersion).join(Experiment,Experiment.id==ModelVersion.experiment_id).where(ModelVersion.id==model_id,Experiment.project_id==context.project.id))
    if model is None: raise HTTPException(404,"模型不存在")
    allowed={"candidate":{"validated","archived"},"validated":{"production","archived"},"production":{"archived"},"archived":set()}
    if body.stage not in allowed.get(model.stage,set()):
        raise HTTPException(409,f"不允许从 {model.stage} 变更为 {body.stage}")
    previous=model.stage
    if body.stage == "validated":
        required = {"roc_auc", "rank_ic", "cost_adjusted_return", "folds"}
        missing = required.difference(model.metrics)
        if missing or len(model.metrics.get("folds", [])) < 3:
            raise HTTPException(409, f"模型缺少可信验证证据: {sorted(missing)}")
    if body.stage=="production":
        # 发布只替换当前项目内同算法的生产版本，不能影响其他项目。
        others=(
            await session.scalars(
                select(ModelVersion)
                .join(Experiment,Experiment.id==ModelVersion.experiment_id)
                .where(
                    Experiment.project_id==context.project.id,
                    ModelVersion.algorithm==model.algorithm,
                    ModelVersion.stage=="production",
                    ModelVersion.id!=model.id,
                )
            )
        ).all()
        for item in others: item.stage="archived"
    model.stage=body.stage
    session.add(AuditLog(actor_id=admin.id,action="model.stage_changed",resource_type="model",resource_id=str(model.id),details={"from":previous,"to":body.stage,"reason":body.reason}))
    await session.commit();await session.refresh(model);return model


@router.post("/models/{model_id}/rollback",response_model=ModelRead)
async def rollback_model(
    model_id:UUID,
    body:ModelRollbackRequest,
    session:AsyncSession=Depends(get_db_session),
    admin:User=Depends(require_admin),
    context:ProjectContext=Depends(get_project_context),
):
    """Restore a previously validated model as this project's production version."""
    model=await session.scalar(
        select(ModelVersion).join(Experiment,Experiment.id==ModelVersion.experiment_id).where(
            ModelVersion.id==model_id,Experiment.project_id==context.project.id
        )
    )
    if model is None:raise HTTPException(404,"模型不存在")
    if model.stage not in {"validated","archived"}:raise HTTPException(409,"只有已验证或已归档模型可以回滚到生产")
    required={"roc_auc","rank_ic","cost_adjusted_return","folds"}
    if required.difference(model.metrics):raise HTTPException(409,"模型缺少可信验证证据")
    current=(
        await session.scalars(
            select(ModelVersion).join(Experiment,Experiment.id==ModelVersion.experiment_id).where(
                Experiment.project_id==context.project.id,
                ModelVersion.algorithm==model.algorithm,
                ModelVersion.stage=="production",
                ModelVersion.id!=model.id,
            )
        )
    ).all()
    for item in current:item.stage="archived"
    previous=model.stage;model.stage="production"
    session.add(AuditLog(actor_id=admin.id,action="model.rollback",resource_type="model",resource_id=str(model.id),details={"from":previous,"to":"production","reason":body.reason}))
    await session.commit();await session.refresh(model);return model


async def _create_prediction(
    *,
    name:str,
    model:ModelVersion,
    snapshot:FeatureSnapshot,
    session:AsyncSession,
    context:ProjectContext,
) -> TaskSubmission:
    job,prediction=await create_prediction_job(
        session,
        name=name,
        model=model,
        feature_snapshot_id=snapshot.id,
        owner_id=context.user.id,
        project_id=context.project.id,
    )
    await session.commit()
    return TaskSubmission(job_id=job.id,resource_id=prediction.id)


@router.post("/predictions",response_model=TaskSubmission,status_code=202)
async def create_prediction(
    body:PredictionCreate,
    session:AsyncSession=Depends(get_db_session),
    context:ProjectContext=Depends(get_project_context),
):
    model=await session.scalar(
        select(ModelVersion).join(Experiment,Experiment.id==ModelVersion.experiment_id).where(
            ModelVersion.id==body.model_id,Experiment.project_id==context.project.id
        )
    )
    snapshot=await session.scalar(select(FeatureSnapshot).where(FeatureSnapshot.id==body.feature_snapshot_id,FeatureSnapshot.project_id==context.project.id))
    if model is None:raise HTTPException(404,"模型不存在")
    if snapshot is None or snapshot.status!="ready":raise HTTPException(409,"必须选择已就绪的特征快照")
    return await _create_prediction(name=body.name,model=model,snapshot=snapshot,session=session,context=context)


@router.get("/predictions",response_model=list[PredictionRead])
async def list_predictions(session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    return list((await session.scalars(select(PredictionRun).where(PredictionRun.project_id==context.project.id).order_by(PredictionRun.created_at.desc()).limit(200))).all())


@router.get("/predictions/{prediction_id}/artifact")
async def download_prediction(
    prediction_id:UUID,
    session:AsyncSession=Depends(get_db_session),
    context:ProjectContext=Depends(get_project_context),
):
    prediction=await session.scalar(select(PredictionRun).where(PredictionRun.id==prediction_id,PredictionRun.project_id==context.project.id))
    if prediction is None:raise HTTPException(404,"预测任务不存在")
    if prediction.status!="succeeded" or not prediction.artifact_uri:raise HTTPException(409,"预测产物尚未生成")
    from backend.app.infrastructure.object_storage import download_bytes
    payload=await run_in_threadpool(download_bytes,prediction.artifact_uri)
    return Response(
        content=payload,
        media_type="application/vnd.apache.parquet",
        headers={"Content-Disposition":f'attachment; filename="prediction-{prediction.id}.parquet"'},
    )


@router.get("/models/production",response_model=list[ModelRead])
async def production_models(session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    return list((await session.scalars(select(ModelVersion).join(Experiment,Experiment.id==ModelVersion.experiment_id).where(Experiment.project_id==context.project.id,ModelVersion.stage=="production").order_by(ModelVersion.created_at.desc()))).all())


@router.post("/models/production/{algorithm}/predictions",response_model=TaskSubmission,status_code=202)
async def production_prediction(
    algorithm:str,
    body:ProductionPredictionCreate,
    session:AsyncSession=Depends(get_db_session),
    context:ProjectContext=Depends(get_project_context),
):
    model=await session.scalar(
        select(ModelVersion).join(Experiment,Experiment.id==ModelVersion.experiment_id).where(
            Experiment.project_id==context.project.id,
            ModelVersion.algorithm==algorithm,
            ModelVersion.stage=="production",
        ).order_by(ModelVersion.created_at.desc())
    )
    snapshot=await session.scalar(select(FeatureSnapshot).where(FeatureSnapshot.id==body.feature_snapshot_id,FeatureSnapshot.project_id==context.project.id))
    if model is None:raise HTTPException(404,"当前项目没有该算法的生产模型")
    if snapshot is None or snapshot.status!="ready":raise HTTPException(409,"必须选择已就绪的特征快照")
    return await _create_prediction(name=body.name,model=model,snapshot=snapshot,session=session,context=context)
