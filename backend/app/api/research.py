"""策略、数据集、训练实验和模型仓库API。"""

from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.app.db.session import get_db_session
from backend.app.infrastructure.outbox import add_outbox
from backend.app.models.job import Job
from backend.app.models.data_catalog import FactorResearchRun, FeatureSnapshot
from backend.app.models.research import Dataset, Experiment, ModelVersion, PredictionRun, SealedEvaluation, Strategy
from backend.app.schemas.research import (
    DatasetCreate, DatasetRead, ExperimentCreate, ExperimentRead, ModelRead,
    ModelRollbackRequest, ModelStageUpdate, PredictionCreate, PredictionRead,
    ProductionPredictionCreate, SealedEvaluationCreate, SealedEvaluationRead,
    StrategyCreate, StrategyRead, TaskSubmission,
)
from backend.app.core.security import get_current_user, require_admin
from backend.app.models.identity import AuditLog, User
from backend.app.core.projects import ProjectContext, get_project_context
from backend.app.services.predictions import create_prediction_job
from backend.app.services.research_gates import calibration_evidence_complete, validate_factor_dataset_gate

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
        factor_run=await session.scalar(
            select(FactorResearchRun).where(
                FactorResearchRun.id==body.factor_research_id,
                FactorResearchRun.project_id==context.project.id,
            )
        )
        if factor_run is None:
            raise HTTPException(409,"必须选择当前项目内的因子研究门禁")
        try:
            validate_factor_dataset_gate(
                snapshot_id=snapshot.id,
                horizon=body.horizon,
                training_fraction=body.training_fraction,
                run_snapshot_id=factor_run.snapshot_id,
                run_status=factor_run.status,
                run_parameters=factor_run.parameters,
                run_metrics=factor_run.metrics,
                selected_feature_slugs=factor_run.selected_feature_slugs,
            )
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from exc
    jid,did=uuid4(),uuid4(); spec=body.model_dump(mode="json")
    job=Job(id=jid,owner_id=context.user.id,project_id=context.project.id,kind="dataset",status="queued",progress=0,payload={"dataset_id":str(did)})
    item=Dataset(id=did,project_id=context.project.id,job_id=jid,feature_snapshot_id=body.feature_snapshot_id,factor_research_id=body.factor_research_id,name=body.name,status="queued",specification=spec)
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


@router.get("/models/{model_id}/sealed-evaluation", response_model=SealedEvaluationRead | None)
async def read_sealed_evaluation(
    model_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    return await session.scalar(
        select(SealedEvaluation)
        .join(ModelVersion, ModelVersion.id == SealedEvaluation.model_id)
        .join(Experiment, Experiment.id == ModelVersion.experiment_id)
        .where(SealedEvaluation.model_id == model_id, Experiment.project_id == context.project.id)
    )


@router.post("/models/{model_id}/sealed-evaluation", response_model=TaskSubmission, status_code=202)
async def create_sealed_evaluation(
    model_id: UUID,
    body: SealedEvaluationCreate,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(require_admin),
    context: ProjectContext = Depends(get_project_context),
):
    row = (
        await session.execute(
            select(ModelVersion, Experiment, Dataset)
            .join(Experiment, Experiment.id == ModelVersion.experiment_id)
            .join(Dataset, Dataset.id == Experiment.dataset_id)
            .where(ModelVersion.id == model_id, Experiment.project_id == context.project.id)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "模型不存在")
    model, _experiment, dataset = row
    if model.stage != "candidate":
        raise HTTPException(409, "只有锁定参数的候选模型可以开启最终封存区")
    protocol = dict((dataset.metadata_snapshot or {}).get("research_protocol") or {})
    if protocol.get("kind") != "train_tune_sealed_v1" or model.metrics.get("sealed_status") != "locked":
        raise HTTPException(409, "该模型不是三段式研究产生的封存候选模型")
    existing = await session.scalar(select(SealedEvaluation).where(SealedEvaluation.dataset_id == dataset.id))
    if existing is not None:
        raise HTTPException(409, "该数据集的最终封存区已经开启，不能用于第二个模型")
    jid, evaluation_id = uuid4(), uuid4()
    job = Job(
        id=jid, owner_id=context.user.id, project_id=context.project.id,
        kind="sealed_evaluation", status="queued", progress=0,
        payload={"sealed_evaluation_id": str(evaluation_id)},
    )
    evaluation = SealedEvaluation(
        id=evaluation_id, project_id=context.project.id, dataset_id=dataset.id,
        model_id=model.id, job_id=jid, status="queued", reason=body.reason,
    )
    session.add(job); await session.flush(); session.add(evaluation)
    session.add(AuditLog(
        actor_id=admin.id, action="model.sealed_evaluation_opened",
        resource_type="model", resource_id=str(model.id),
        details={"dataset_id": str(dataset.id), "reason": body.reason},
    ))
    add_outbox(session, job, "backend.app.workers.research.evaluate_sealed_model")
    await session.commit()
    return TaskSubmission(job_id=jid, resource_id=evaluation_id)


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
        if model.metrics.get("evaluation_scope") == "tuning_oos" and not model.metrics.get("sealed_evaluation"):
            raise HTTPException(409, "三段式研究模型必须先完成唯一一次最终封存区评估")
        if model.metrics.get("evaluation_scope") == "tuning_oos":
            if not calibration_evidence_complete(model.metrics):
                raise HTTPException(409, "模型缺少调参区或最终封存区的概率校准证据")
    if body.stage=="production":
        if model.metrics.get("evaluation_scope") == "tuning_oos":
            if not calibration_evidence_complete(model.metrics):
                raise HTTPException(409, "未通过最终封存区概率校准门禁")
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
    if model.metrics.get("evaluation_scope") == "tuning_oos":
        if not calibration_evidence_complete(model.metrics):
            raise HTTPException(409, "模型缺少调参区或封存区概率校准证据，不能回滚为生产")
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
    if model.metrics.get("evaluation_scope") == "tuning_oos" and model.metrics.get("sealed_status") == "locked":
        dataset_meta = (model.reproducibility or {}).get("dataset") or {}
        source = dataset_meta.get("source") if isinstance(dataset_meta, dict) else {}
        if str((source or {}).get("feature_snapshot_id")) == str(snapshot.id):
            raise HTTPException(409, "最终封存区仍锁定，不能通过批量预测提前读取同一研究快照")
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
