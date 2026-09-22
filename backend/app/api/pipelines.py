"""一键研究流水线 API：一次提交，服务端链式完成快照到调参区回测。"""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.projects import ProjectContext, get_project_context
from backend.app.core.security import get_current_user
from backend.app.db.session import get_db_session
from backend.app.infrastructure.outbox import add_outbox
from backend.app.models.data_catalog import DataVersion, FeatureDefinition, FeatureSnapshot
from backend.app.models.research import ResearchPipeline
from backend.app.schemas.research import PipelineRead, PipelineSubmission, QuickResearchCreate
from backend.app.services.pipeline import build_pipeline_spec, plan_first_step

router = APIRouter(tags=["research-pipelines"], dependencies=[Depends(get_current_user)])


@router.post("/pipelines/quick-research", response_model=PipelineSubmission, status_code=202)
async def create_quick_research(
    body: QuickResearchCreate,
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    inputs: dict = {
        "horizon": body.horizon,
        "training_fraction": body.training_fraction,
        "algorithm": body.algorithm,
        "algorithm_parameters": body.algorithm_parameters,
        "top_n": body.top_n,
        "minimum_probability": body.minimum_probability,
        "rebalance_frequency": body.rebalance_frequency,
        "initial_cash": body.initial_cash,
    }
    if body.feature_snapshot_id:
        snapshot = await session.scalar(
            select(FeatureSnapshot).where(
                FeatureSnapshot.id == body.feature_snapshot_id,
                FeatureSnapshot.project_id == context.project.id,
            )
        )
        if snapshot is None or snapshot.status != "ready":
            raise HTTPException(409, "必须选择当前项目内已就绪的特征快照")
        first_step = "factor_research"
        inputs["feature_snapshot_id"] = str(snapshot.id)
        inputs["data_version_id"] = str(snapshot.data_version_id)
    else:
        version = await session.scalar(
            select(DataVersion).where(
                DataVersion.id == body.data_version_id,
                DataVersion.project_id == context.project.id,
            )
        )
        if version is None or version.layer != "standardized" or version.status != "ready":
            raise HTTPException(409, "必须选择当前项目内已就绪的标准化数据版本")
        definitions = list(
            (await session.scalars(select(FeatureDefinition).where(FeatureDefinition.status == "active"))).all()
        )
        if not definitions:
            raise HTTPException(409, "当前没有可用的因子定义")
        first_step = "materialize"
        inputs["data_version_id"] = str(version.id)
        inputs["feature_definition_ids"] = [str(item.id) for item in definitions]
    pipeline = ResearchPipeline(
        id=uuid4(), project_id=context.project.id, owner_id=context.user.id,
        name=body.name, status="running", current_step=first_step,
        spec=build_pipeline_spec(inputs, first_step),
    )
    job, resource, function_path, _spec, _step = plan_first_step(pipeline)
    session.add(job)
    await session.flush()
    session.add(pipeline)
    session.add(resource)
    add_outbox(session, job, function_path)
    await session.commit()
    return PipelineSubmission(pipeline_id=pipeline.id, job_id=pipeline.current_job_id)


@router.get("/pipelines", response_model=list[PipelineRead])
async def list_pipelines(
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    return list(
        (await session.scalars(
            select(ResearchPipeline)
            .where(ResearchPipeline.project_id == context.project.id)
            .order_by(ResearchPipeline.created_at.desc())
            .limit(100)
        )).all()
    )


@router.get("/pipelines/{pipeline_id}", response_model=PipelineRead)
async def read_pipeline(
    pipeline_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    pipeline = await session.scalar(
        select(ResearchPipeline).where(
            ResearchPipeline.id == pipeline_id,
            ResearchPipeline.project_id == context.project.id,
        )
    )
    if pipeline is None:
        raise HTTPException(404, "Pipeline not found")
    return pipeline
