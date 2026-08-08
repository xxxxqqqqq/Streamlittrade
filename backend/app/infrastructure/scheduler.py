"""Database-backed interval scheduler for production prediction jobs."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.db.sync_session import SyncSessionFactory
from backend.app.infrastructure.outbox import add_outbox
from backend.app.models.data_catalog import FeatureSnapshot
from backend.app.models.job import Job
from backend.app.models.operations import AlertEvent, PaperAutomationRun, PaperAutomationSchedule, PredictionSchedule
from backend.app.models.paper import PaperAccount
from backend.app.models.research import Experiment, ModelVersion, PredictionRun
from backend.app.services.paper_automation import snapshot_supports_features


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


def enqueue_due_paper_automations(limit: int = 20) -> int:
    """Use the newest compatible immutable snapshot exactly once per schedule."""
    now, created = datetime.now(UTC), 0
    with SyncSessionFactory() as session:
        schedules = list(session.scalars(
            select(PaperAutomationSchedule).where(
                PaperAutomationSchedule.enabled.is_(True),
                PaperAutomationSchedule.next_run_at <= now,
            ).order_by(PaperAutomationSchedule.next_run_at).limit(limit).with_for_update(skip_locked=True)
        ).all())
        for schedule in schedules:
            schedule.next_run_at = now + timedelta(minutes=schedule.interval_minutes)
            model = session.scalar(select(ModelVersion).join(Experiment, Experiment.id == ModelVersion.experiment_id).where(
                Experiment.project_id == schedule.project_id,
                ModelVersion.algorithm == schedule.algorithm,
                ModelVersion.stage == "production",
            ).order_by(ModelVersion.created_at.desc()))
            account = session.get(PaperAccount, schedule.account_id)
            required = list((model.reproducibility or {}).get("features") or []) if model else []
            snapshots = list(session.scalars(select(FeatureSnapshot).where(
                FeatureSnapshot.project_id == schedule.project_id,
                FeatureSnapshot.status == "ready",
            ).order_by(FeatureSnapshot.created_at.desc()).limit(100)).all())
            snapshot = next((item for item in snapshots if snapshot_supports_features(item.lineage, required)), None)
            calibrated = bool(model and isinstance((model.metrics or {}).get("calibration"), dict))
            if model is None or not calibrated or account is None or account.status != "active" or snapshot is None:
                session.add(AlertEvent(project_id=schedule.project_id, code="PAPER_AUTOMATION_BLOCKED", severity="warning", title="模拟交易自动化被门禁阻止", message=f"{schedule.name} 缺少生产模型、启用账户或兼容的最新快照", details={"schedule_id": str(schedule.id)}))
                continue
            already = session.scalar(select(PaperAutomationRun.id).where(
                PaperAutomationRun.schedule_id == schedule.id,
                PaperAutomationRun.feature_snapshot_id == snapshot.id,
            ))
            if already:
                continue
            job_id, run_id = uuid4(), uuid4()
            job = Job(id=job_id, owner_id=schedule.owner_id, project_id=schedule.project_id, kind="paper_automation", status="queued", progress=0, payload={"paper_automation_run_id": str(run_id), "schedule_id": str(schedule.id)})
            run = PaperAutomationRun(id=run_id, project_id=schedule.project_id, schedule_id=schedule.id, job_id=job_id, account_id=schedule.account_id, model_id=model.id, feature_snapshot_id=snapshot.id, status="queued")
            session.add(job); session.flush(); session.add(run)
            add_outbox(session, job, "backend.app.workers.automation.run_paper_automation")
            schedule.last_job_id, schedule.last_run_at = job_id, now
            created += 1
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
    return created


async def scheduler_loop(stop: asyncio.Event) -> None:
    """Continuously claim schedules; durable timestamps survive process restarts."""
    while not stop.is_set():
        await asyncio.to_thread(enqueue_due_schedules)
        await asyncio.to_thread(enqueue_due_paper_automations)
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except TimeoutError:
            pass
