"""Cross-domain product APIs for global search and the notification center."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.projects import ProjectContext, get_project_context
from backend.app.core.security import get_current_user
from backend.app.db.session import get_db_session
from backend.app.models.backtest import BacktestRun
from backend.app.models.data_catalog import DataVersion, FeatureSnapshot
from backend.app.models.operations import AlertEvent
from backend.app.models.research import Dataset, Experiment, ModelVersion, Strategy
from backend.app.schemas.operations import AlertRead


router = APIRouter(tags=["product"], dependencies=[Depends(get_current_user)])


@router.get("/search")
async def global_search(
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=5, ge=1, le=20),
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    """Search the active project's primary research resources."""
    pattern = f"%{q.strip()}%"
    project_id = context.project.id
    results: list[dict] = []

    strategies = (
        await session.scalars(
            select(Strategy)
            .where(
                Strategy.project_id == project_id,
                or_(Strategy.name.ilike(pattern), Strategy.slug.ilike(pattern)),
            )
            .limit(limit)
        )
    ).all()
    results.extend(
        {
            "id": str(item.id),
            "type": "strategy",
            "title": item.name,
            "subtitle": f"{item.slug} v{item.version}",
            "url": "/strategies",
        }
        for item in strategies
    )

    datasets = (
        await session.scalars(
            select(Dataset)
            .where(Dataset.project_id == project_id, Dataset.name.ilike(pattern))
            .limit(limit)
        )
    ).all()
    results.extend(
        {
            "id": str(item.id),
            "type": "dataset",
            "title": item.name,
            "subtitle": item.status,
            "url": "/datasets",
        }
        for item in datasets
    )

    experiments = (
        await session.scalars(
            select(Experiment)
            .where(Experiment.project_id == project_id, Experiment.name.ilike(pattern))
            .limit(limit)
        )
    ).all()
    results.extend(
        {
            "id": str(item.id),
            "type": "experiment",
            "title": item.name,
            "subtitle": f"{item.algorithm} · {item.status}",
            "url": "/experiments",
        }
        for item in experiments
    )

    models = (
        await session.scalars(
            select(ModelVersion)
            .join(Experiment, Experiment.id == ModelVersion.experiment_id)
            .where(
                Experiment.project_id == project_id,
                ModelVersion.name.ilike(pattern),
            )
            .limit(limit)
        )
    ).all()
    results.extend(
        {
            "id": str(item.id),
            "type": "model",
            "title": item.name,
            "subtitle": f"{item.algorithm} · {item.stage}",
            "url": f"/models/{item.id}",
        }
        for item in models
    )

    backtests = (
        await session.scalars(
            select(BacktestRun)
            .where(
                BacktestRun.project_id == project_id,
                or_(
                    BacktestRun.symbol.ilike(pattern),
                    BacktestRun.strategy_name.ilike(pattern),
                ),
            )
            .limit(limit)
        )
    ).all()
    results.extend(
        {
            "id": str(item.id),
            "type": "backtest",
            "title": item.symbol,
            "subtitle": item.strategy_name,
            "url": f"/backtests/{item.id}",
        }
        for item in backtests
    )

    versions = (
        await session.scalars(
            select(DataVersion)
            .where(
                DataVersion.project_id == project_id,
                DataVersion.content_sha256.ilike(pattern),
            )
            .limit(limit)
        )
    ).all()
    results.extend(
        {
            "id": str(item.id),
            "type": "data_version",
            "title": f"{item.layer} 数据版本",
            "subtitle": (item.content_sha256 or "")[:16],
            "url": f"/data-center/versions/{item.id}",
        }
        for item in versions
    )

    snapshots = (
        await session.scalars(
            select(FeatureSnapshot)
            .where(
                FeatureSnapshot.project_id == project_id,
                FeatureSnapshot.name.ilike(pattern),
            )
            .limit(limit)
        )
    ).all()
    results.extend(
        {
            "id": str(item.id),
            "type": "feature_snapshot",
            "title": item.name,
            "subtitle": item.status,
            "url": f"/data-center/snapshots/{item.id}",
        }
        for item in snapshots
    )
    return results[: limit * 5]


@router.get("/notifications", response_model=list[AlertRead])
async def notifications(
    status: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    filters = [AlertEvent.project_id == context.project.id]
    if status:
        filters.append(AlertEvent.status == status)
    return list(
        (
            await session.scalars(
                select(AlertEvent)
                .where(*filters)
                .order_by(AlertEvent.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
