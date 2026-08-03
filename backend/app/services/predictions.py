"""Shared creation service for manual and scheduled prediction jobs."""

from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.infrastructure.outbox import add_outbox
from backend.app.models.job import Job
from backend.app.models.research import ModelVersion, PredictionRun


async def create_prediction_job(
    session: AsyncSession,
    *,
    name: str,
    model: ModelVersion,
    feature_snapshot_id: UUID,
    owner_id: UUID | None,
    project_id: UUID,
) -> tuple[Job, PredictionRun]:
    """Persist a prediction and its queue intent in one database transaction."""
    job = Job(
        id=uuid4(),
        owner_id=owner_id,
        project_id=project_id,
        kind="prediction",
        status="queued",
        progress=0,
        payload={},
    )
    prediction = PredictionRun(
        id=uuid4(),
        project_id=project_id,
        job_id=job.id,
        model_id=model.id,
        feature_snapshot_id=feature_snapshot_id,
        name=name,
        status="queued",
    )
    job.payload = {"prediction_id": str(prediction.id)}
    session.add(job)
    await session.flush()
    session.add(prediction)
    add_outbox(session, job, "backend.app.workers.research.run_batch_prediction")
    return job, prediction

