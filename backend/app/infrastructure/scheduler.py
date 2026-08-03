"""Database-backed interval scheduler for production prediction jobs."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from backend.app.db.sync_session import SyncSessionFactory
from backend.app.infrastructure.outbox import add_outbox
from backend.app.models.data_catalog import FeatureSnapshot
from backend.app.models.job import Job
from backend.app.models.operations import AlertEvent, PredictionSchedule
from backend.app.models.research import Experiment, ModelVersion, PredictionRun


def enqueue_due_schedules(limit: int = 20) -> int:
    """Claim due schedules and persist jobs transactionally.

    ``SKIP LOCKED`` allows multiple API replicas to run this loop without creating
    duplicate jobs for the same due time.
    """
    now = datetime.now(UTC)
    created = 0
    with SyncSessionFactory() as session:
        schedules = list(
            session.scalars(
                select(PredictionSchedule)
                .where(
                    PredictionSchedule.enabled.is_(True),
                    PredictionSchedule.next_run_at <= now,
                )
                .order_by(PredictionSchedule.next_run_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
        for schedule in schedules:
            model = session.scalar(
                select(ModelVersion)
                .join(Experiment, Experiment.id == ModelVersion.experiment_id)
                .where(
                    Experiment.project_id == schedule.project_id,
                    ModelVersion.algorithm == schedule.algorithm,
                    ModelVersion.stage == "production",
                )
                .order_by(ModelVersion.created_at.desc())
            )
            snapshot = session.get(FeatureSnapshot, schedule.feature_snapshot_id)
            if (
                model is None
                or snapshot is None
                or snapshot.project_id != schedule.project_id
                or snapshot.status != "ready"
            ):
                schedule.next_run_at = now + timedelta(
                    minutes=schedule.interval_minutes
                )
                session.add(
                    AlertEvent(
                        project_id=schedule.project_id,
                        code="SCHEDULE_BLOCKED",
                        severity="warning",
                        title="自动预测计划无法运行",
                        message=f"{schedule.name} 缺少生产模型或已就绪特征快照",
                        details={"schedule_id": str(schedule.id)},
                    )
                )
                continue
            job = Job(
                id=uuid4(),
                owner_id=schedule.owner_id,
                project_id=schedule.project_id,
                kind="prediction",
                status="queued",
                progress=0,
                payload={},
            )
            prediction = PredictionRun(
                id=uuid4(),
                project_id=schedule.project_id,
                job_id=job.id,
                model_id=model.id,
                feature_snapshot_id=snapshot.id,
                name=f"{schedule.name} · scheduled",
                status="queued",
            )
            job.payload = {
                "prediction_id": str(prediction.id),
                "schedule_id": str(schedule.id),
            }
            session.add(job)
            session.flush()
            session.add(prediction)
            add_outbox(
                session, job, "backend.app.workers.research.run_batch_prediction"
            )
            schedule.last_job_id = job.id
            schedule.last_run_at = now
            schedule.next_run_at = now + timedelta(
                minutes=schedule.interval_minutes
            )
            created += 1
        session.commit()
    return created


async def scheduler_loop(stop: asyncio.Event) -> None:
    """Continuously claim schedules; durable timestamps survive process restarts."""
    while not stop.is_set():
        await asyncio.to_thread(enqueue_due_schedules)
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except TimeoutError:
            pass

