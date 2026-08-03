"""Production prediction scheduling, drift monitoring, and alert lifecycle API."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.projects import ProjectContext, get_project_context
from backend.app.core.security import get_current_user, require_admin
from backend.app.db.session import get_db_session
from backend.app.infrastructure.outbox import add_outbox
from backend.app.models.data_catalog import FeatureSnapshot
from backend.app.models.identity import AuditLog, User
from backend.app.models.job import Job
from backend.app.models.operations import AlertEvent, DriftRun, PredictionSchedule
from backend.app.models.research import Dataset, Experiment, ModelVersion
from backend.app.schemas.operations import (
    AlertRead,
    AlertUpdate,
    DriftCreate,
    DriftRead,
    ScheduleCreate,
    ScheduleRead,
    ScheduleUpdate,
)
from backend.app.schemas.research import TaskSubmission
from backend.app.services.predictions import create_prediction_job


router = APIRouter(tags=["operations"], dependencies=[Depends(get_current_user)])


async def _production_model(
    session: AsyncSession, project_id: UUID, algorithm: str
) -> ModelVersion | None:
    return await session.scalar(
        select(ModelVersion)
        .join(Experiment, Experiment.id == ModelVersion.experiment_id)
        .where(
            Experiment.project_id == project_id,
            ModelVersion.algorithm == algorithm,
            ModelVersion.stage == "production",
        )
        .order_by(ModelVersion.created_at.desc())
    )


async def _ready_snapshot(
    session: AsyncSession, project_id: UUID, snapshot_id: UUID
) -> FeatureSnapshot | None:
    return await session.scalar(
        select(FeatureSnapshot).where(
            FeatureSnapshot.id == snapshot_id,
            FeatureSnapshot.project_id == project_id,
            FeatureSnapshot.status == "ready",
        )
    )


@router.post("/prediction-schedules", response_model=ScheduleRead, status_code=201)
async def create_schedule(
    body: ScheduleCreate,
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    """Create an interval schedule bound to a production algorithm and feature snapshot."""
    if await _production_model(session, context.project.id, body.algorithm) is None:
        raise HTTPException(409, "当前项目没有该算法的生产模型")
    if await _ready_snapshot(session, context.project.id, body.feature_snapshot_id) is None:
        raise HTTPException(409, "必须选择当前项目内已就绪的特征快照")
    item = PredictionSchedule(
        project_id=context.project.id,
        owner_id=context.user.id,
        next_run_at=datetime.now(UTC) + timedelta(minutes=body.interval_minutes),
        **body.model_dump(),
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.get("/prediction-schedules", response_model=list[ScheduleRead])
async def list_schedules(
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    return list(
        (
            await session.scalars(
                select(PredictionSchedule)
                .where(PredictionSchedule.project_id == context.project.id)
                .order_by(PredictionSchedule.created_at.desc())
            )
        ).all()
    )


@router.patch("/prediction-schedules/{schedule_id}", response_model=ScheduleRead)
async def update_schedule(
    schedule_id: UUID,
    body: ScheduleUpdate,
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    item = await session.scalar(
        select(PredictionSchedule).where(
            PredictionSchedule.id == schedule_id,
            PredictionSchedule.project_id == context.project.id,
        )
    )
    if item is None:
        raise HTTPException(404, "预测计划不存在")
    changes = body.model_dump(exclude_none=True)
    for key, value in changes.items():
        setattr(item, key, value)
    if "interval_minutes" in changes or changes.get("enabled") is True:
        item.next_run_at = datetime.now(UTC) + timedelta(minutes=item.interval_minutes)
    await session.commit()
    await session.refresh(item)
    return item


@router.post(
    "/prediction-schedules/{schedule_id}/run",
    response_model=TaskSubmission,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_schedule_now(
    schedule_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    schedule = await session.scalar(
        select(PredictionSchedule).where(
            PredictionSchedule.id == schedule_id,
            PredictionSchedule.project_id == context.project.id,
        )
    )
    if schedule is None:
        raise HTTPException(404, "预测计划不存在")
    model = await _production_model(session, context.project.id, schedule.algorithm)
    snapshot = await _ready_snapshot(
        session, context.project.id, schedule.feature_snapshot_id
    )
    if model is None or snapshot is None:
        alert = AlertEvent(
            project_id=context.project.id,
            code="SCHEDULE_BLOCKED",
            severity="warning",
            title="自动预测计划无法运行",
            message=f"{schedule.name} 缺少生产模型或已就绪特征快照",
            details={"schedule_id": str(schedule.id), "manual_run": True},
        )
        session.add(alert)
        await session.commit()
        raise HTTPException(409, "生产模型或特征快照已不可用")
    job, prediction = await create_prediction_job(
        session,
        name=f"{schedule.name} · manual",
        model=model,
        feature_snapshot_id=snapshot.id,
        owner_id=context.user.id,
        project_id=context.project.id,
    )
    now = datetime.now(UTC)
    schedule.last_run_at = now
    schedule.last_job_id = job.id
    schedule.next_run_at = now + timedelta(minutes=schedule.interval_minutes)
    await session.commit()
    return TaskSubmission(job_id=job.id, resource_id=prediction.id)


@router.post("/monitoring/drift-runs", response_model=TaskSubmission, status_code=202)
async def create_drift_run(
    body: DriftCreate,
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    model = await session.scalar(
        select(ModelVersion)
        .join(Experiment, Experiment.id == ModelVersion.experiment_id)
        .where(
            ModelVersion.id == body.model_id,
            Experiment.project_id == context.project.id,
        )
    )
    if model is None:
        raise HTTPException(404, "模型不存在")
    experiment = await session.get(Experiment, model.experiment_id)
    dataset = await session.get(Dataset, experiment.dataset_id)
    if dataset is None or dataset.feature_snapshot_id is None:
        raise HTTPException(409, "该模型没有可用于漂移比较的基线特征快照")
    current = await _ready_snapshot(
        session, context.project.id, body.current_snapshot_id
    )
    baseline = await _ready_snapshot(
        session, context.project.id, dataset.feature_snapshot_id
    )
    if current is None or baseline is None:
        raise HTTPException(409, "基线或当前特征快照不可用")
    job_id, run_id = uuid4(), uuid4()
    job = Job(
        id=job_id,
        owner_id=context.user.id,
        project_id=context.project.id,
        kind="drift_monitor",
        status="queued",
        progress=0,
        payload={"drift_run_id": str(run_id)},
    )
    run = DriftRun(
        id=run_id,
        project_id=context.project.id,
        job_id=job_id,
        model_id=model.id,
        baseline_snapshot_id=baseline.id,
        current_snapshot_id=current.id,
        status="queued",
    )
    session.add(job)
    await session.flush()
    session.add(run)
    add_outbox(session, job, "backend.app.workers.monitoring.run_drift_monitor")
    await session.commit()
    return TaskSubmission(job_id=job_id, resource_id=run_id)


@router.get("/monitoring/drift-runs", response_model=list[DriftRead])
async def list_drift_runs(
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    return list(
        (
            await session.scalars(
                select(DriftRun)
                .where(DriftRun.project_id == context.project.id)
                .order_by(DriftRun.created_at.desc())
                .limit(100)
            )
        ).all()
    )


@router.get("/monitoring/alerts", response_model=list[AlertRead])
async def list_alerts(
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    return list(
        (
            await session.scalars(
                select(AlertEvent)
                .where(AlertEvent.project_id == context.project.id)
                .order_by(AlertEvent.created_at.desc())
                .limit(200)
            )
        ).all()
    )


@router.patch("/monitoring/alerts/{alert_id}", response_model=AlertRead)
async def update_alert(
    alert_id: UUID,
    body: AlertUpdate,
    session: AsyncSession = Depends(get_db_session),
    admin: User = Depends(require_admin),
    context: ProjectContext = Depends(get_project_context),
):
    alert = await session.scalar(
        select(AlertEvent).where(
            AlertEvent.id == alert_id,
            AlertEvent.project_id == context.project.id,
        )
    )
    if alert is None:
        raise HTTPException(404, "告警不存在")
    previous = alert.status
    alert.status = body.status
    alert.acknowledged_by = admin.id
    alert.acknowledged_at = datetime.now(UTC)
    session.add(
        AuditLog(
            actor_id=admin.id,
            action="alert.status_changed",
            resource_type="alert",
            resource_id=str(alert.id),
            details={"from": previous, "to": body.status},
        )
    )
    await session.commit()
    await session.refresh(alert)
    return alert
