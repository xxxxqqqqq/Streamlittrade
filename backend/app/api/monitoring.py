"""Project-scoped operational metrics and persisted alert summary."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.projects import ProjectContext, get_project_context
from backend.app.core.security import require_admin
from backend.app.db.session import get_db_session
from backend.app.models.identity import AuditLog, User
from backend.app.models.job import Job
from backend.app.models.operations import AlertEvent, DriftRun, PredictionSchedule
from backend.app.models.paper import PaperAccount
from backend.app.models.research import Experiment, ModelVersion


router = APIRouter(prefix="/monitoring", tags=["monitoring"])


async def _counts(session: AsyncSession, statement) -> dict[str, int]:
    return {
        str(key): int(value)
        for key, value in (await session.execute(statement)).all()
    }


@router.get("/overview")
async def overview(
    _admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
) -> dict[str, Any]:
    """Return only the active project's operational state."""
    project_id = context.project.id
    since = datetime.now(UTC) - timedelta(hours=24)
    job_counts = await _counts(
        session,
        select(Job.status, func.count())
        .where(Job.project_id == project_id)
        .group_by(Job.status),
    )
    model_counts = await _counts(
        session,
        select(ModelVersion.stage, func.count())
        .join(Experiment, Experiment.id == ModelVersion.experiment_id)
        .where(Experiment.project_id == project_id)
        .group_by(ModelVersion.stage),
    )
    account_counts = await _counts(
        session,
        select(PaperAccount.status, func.count())
        .where(PaperAccount.project_id == project_id)
        .group_by(PaperAccount.status),
    )
    failed_24h = int(
        await session.scalar(
            select(func.count())
            .select_from(Job)
            .where(
                Job.project_id == project_id,
                Job.status == "failed",
                Job.completed_at >= since,
            )
        )
        or 0
    )
    audit_24h = int(
        await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.created_at >= since)
        )
        or 0
    )
    open_alerts = int(
        await session.scalar(
            select(func.count())
            .select_from(AlertEvent)
            .where(
                AlertEvent.project_id == project_id,
                AlertEvent.status == "open",
            )
        )
        or 0
    )
    enabled_schedules = int(
        await session.scalar(
            select(func.count())
            .select_from(PredictionSchedule)
            .where(
                PredictionSchedule.project_id == project_id,
                PredictionSchedule.enabled.is_(True),
            )
        )
        or 0
    )
    drift_counts = await _counts(
        session,
        select(DriftRun.alert_level, func.count())
        .where(DriftRun.project_id == project_id)
        .group_by(DriftRun.alert_level),
    )
    alerts = []
    if failed_24h:
        alerts.append(
            {
                "severity": "warning",
                "code": "JOB_FAILURES",
                "message": f"过去24小时有 {failed_24h} 个失败任务",
            }
        )
    if account_counts.get("frozen", 0):
        alerts.append(
            {
                "severity": "critical",
                "code": "FROZEN_ACCOUNTS",
                "message": f"有 {account_counts['frozen']} 个模拟账户处于冻结状态",
            }
        )
    if not model_counts.get("production", 0):
        alerts.append(
            {
                "severity": "info",
                "code": "NO_PRODUCTION_MODEL",
                "message": "当前项目没有生产模型",
            }
        )
    if open_alerts:
        alerts.append(
            {
                "severity": "warning",
                "code": "OPEN_OPERATIONAL_ALERTS",
                "message": f"当前有 {open_alerts} 条未处置生产告警",
            }
        )
    return {
        "generated_at": datetime.now(UTC),
        "jobs": job_counts,
        "models": model_counts,
        "paper_accounts": account_counts,
        "drift_runs": drift_counts,
        "failed_jobs_24h": failed_24h,
        "audit_events_24h": audit_24h,
        "open_alerts": open_alerts,
        "enabled_schedules": enabled_schedules,
        "alerts": alerts,
    }
