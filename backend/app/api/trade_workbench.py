"""Model-to-trade workbench endpoints."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from backend.app.core.projects import ProjectContext, get_project_context
from backend.app.core.security import get_current_user
from backend.app.db.session import get_db_session
from backend.app.models.backtest import BacktestRun
from backend.app.schemas.backtest import BacktestCreate, BacktestSubmission
from backend.app.schemas.trade_workbench import (
    SignalSeriesRead,
    SnapshotBacktestCreate,
    SymbolTimelineRead,
    WorkbenchContextRead,
)
from backend.app.services.backtests import create_backtest
from backend.app.services.trade_workbench import (
    factor_rows,
    get_model_backtest,
    get_model_chain,
    market_rows,
    normalized_request,
    prediction_frame,
    read_artifact,
    selection_rows,
    trade_events,
)


router = APIRouter(tags=["trade-workbench"], dependencies=[Depends(get_current_user)])


async def _backtest_options(session: AsyncSession, model_id: UUID, project_id: UUID):
    return list(
        (
            await session.scalars(
                select(BacktestRun)
                .where(
                    BacktestRun.project_id == project_id,
                    BacktestRun.model_id == model_id,
                    BacktestRun.signal_source == "model_oos",
                    BacktestRun.artifact_uri.is_not(None),
                )
                .order_by(BacktestRun.created_at.desc())
            )
        ).all()
    )


@router.get("/models/{model_id}/trade-workbench/context", response_model=WorkbenchContextRead)
async def workbench_context(
    model_id: UUID,
    backtest_id: UUID | None = None,
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    chain = await get_model_chain(session, model_id, context.project.id)
    predictions = await run_in_threadpool(prediction_frame, chain)
    backtests = await _backtest_options(session, model_id, context.project.id)
    active = None
    if backtest_id:
        run = await get_model_backtest(session, backtest_id, model_id, context.project.id)
        artifact = await run_in_threadpool(read_artifact, run.artifact_uri)
        active = {
            "id": str(run.id),
            "created_at": run.created_at.isoformat(),
            "metrics": run.metrics or {},
            "request": normalized_request(artifact),
            "artifact_schema_version": int(artifact.get("schema_version", 2)),
        }
    metadata = chain.dataset.metadata_snapshot or {}
    source = metadata.get("source") if isinstance(metadata, dict) else {}
    definitions = (chain.snapshot.lineage or {}).get("definitions", [])
    features = [item.get("slug") for item in definitions if item.get("slug")]
    if not features:
        features = list(metadata.get("features") or [])
    folds = list((chain.model.metrics or {}).get("folds") or [])
    return {
        "model": {
            "id": str(chain.model.id), "name": chain.model.name,
            "version": chain.model.version, "algorithm": chain.model.algorithm,
            "stage": chain.model.stage,
            "model_sha256": (chain.model.reproducibility or {}).get("model_sha256"),
            "prediction_sha256": (chain.model.reproducibility or {}).get("prediction_sha256"),
        },
        "research": {
            "experiment_id": str(chain.experiment.id),
            "dataset_id": str(chain.dataset.id),
            "dataset_sha256": metadata.get("content_sha256"),
            "feature_snapshot_id": str(chain.snapshot.id),
            "feature_snapshot_sha256": chain.snapshot.content_sha256,
            "data_version_id": str(chain.version.id),
            "data_version_sha256": chain.version.content_sha256,
            "lineage": source or {},
        },
        "prediction_target": {
            "kind": "binary_classification",
            "output": "up_probability",
            "label": metadata.get("label", "future_return > 0"),
            "horizon_trading_days": metadata.get("horizon", chain.dataset.specification.get("horizon", 5)),
        },
        "evaluation": {
            "scope": (chain.model.metrics or {}).get("evaluation_scope", "cv_oos"),
            "validation": (chain.model.metrics or {}).get("split", "purged_walk_forward"),
            "oos_start": predictions["date"].min().date().isoformat(),
            "oos_end": predictions["date"].max().date().isoformat(),
            "folds": folds,
            "warning": "当前为调参区样本外结果；最终封存区不会用于模型和组合参数选择。" if (chain.model.metrics or {}).get("evaluation_scope") == "tuning_oos" else "当前为交叉验证样本外结果，不是从未参与选模的最终封存检验区。",
        },
        "universe": sorted(predictions["symbol"].astype(str).unique().tolist()),
        "features": features,
        "backtests": [
            {
                "id": str(item.id), "created_at": item.created_at.isoformat(),
                "start_date": item.start_date.isoformat(), "end_date": item.end_date.isoformat(),
                "metrics": item.metrics or {},
            }
            for item in backtests
        ],
        "active_backtest": active,
    }


@router.get("/models/{model_id}/signals", response_model=SignalSeriesRead)
async def model_signals(
    model_id: UUID,
    symbol: str = Query(min_length=1, max_length=20),
    backtest_id: UUID | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    chain = await get_model_chain(session, model_id, context.project.id)
    artifact = None
    if backtest_id:
        run = await get_model_backtest(session, backtest_id, model_id, context.project.id)
        artifact = await run_in_threadpool(read_artifact, run.artifact_uri)
    predictions = await run_in_threadpool(prediction_frame, chain)
    rows = await run_in_threadpool(
        selection_rows,
        predictions,
        symbol,
        artifact=artifact,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
    )
    if not rows:
        raise HTTPException(404, "该股票在样本外预测区间没有记录")
    return {"model_id": str(model_id), "symbol": symbol, "rows": rows}


@router.get("/backtests/{backtest_id}/symbol-timeline", response_model=SymbolTimelineRead)
async def symbol_timeline(
    backtest_id: UUID,
    symbol: str = Query(min_length=1, max_length=20),
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    run = await session.scalar(
        select(BacktestRun).where(
            BacktestRun.id == backtest_id,
            BacktestRun.project_id == context.project.id,
            BacktestRun.signal_source == "model_oos",
        )
    )
    if run is None or run.model_id is None:
        raise HTTPException(404, "模型回测不存在")
    if not run.artifact_uri:
        raise HTTPException(409, "回测产物尚未生成")
    chain = await get_model_chain(session, run.model_id, context.project.id)
    artifact = await run_in_threadpool(read_artifact, run.artifact_uri)
    request = normalized_request(artifact)
    start = str(request.get("start_date", run.start_date.isoformat()))[:10]
    end = str(request.get("end_date", run.end_date.isoformat()))[:10]
    predictions = await run_in_threadpool(prediction_frame, chain)
    bars = await run_in_threadpool(market_rows, chain, symbol, start, end)
    signals = await run_in_threadpool(selection_rows, predictions, symbol, artifact=artifact, start_date=start, end_date=end)
    factors = await run_in_threadpool(factor_rows, chain, symbol, start, end)
    events = trade_events(artifact, symbol)
    if not bars:
        raise HTTPException(404, "该股票在回测行情中没有记录")
    return {
        "model_id": str(run.model_id), "backtest_id": str(run.id), "symbol": symbol,
        "artifact_schema_version": int(artifact.get("schema_version", 2)),
        "context": {
            "request": request,
            "constraint_model": artifact.get("audit", {}).get("constraint_model", {}),
            "model_lineage": artifact.get("audit", {}).get("model_lineage", {}),
            "portfolio_construction": artifact.get("audit", {}).get("portfolio_construction", {}),
            "metrics": artifact.get("metrics", {}),
            "evaluation_scope": (chain.model.metrics or {}).get("evaluation_scope", "cv_oos"),
        },
        "bars": bars, "signals": signals, "factors": factors, "events": events,
    }


@router.post(
    "/models/{model_id}/backtest-from-snapshot",
    response_model=BacktestSubmission,
    status_code=status.HTTP_202_ACCEPTED,
)
async def backtest_from_snapshot(
    model_id: UUID,
    body: SnapshotBacktestCreate,
    session: AsyncSession = Depends(get_db_session),
    context: ProjectContext = Depends(get_project_context),
):
    chain = await get_model_chain(session, model_id, context.project.id)
    predictions = await run_in_threadpool(prediction_frame, chain)
    oos_start = predictions["date"].min().date()
    oos_end = predictions["date"].max().date()
    market_end = date.fromisoformat(
        str(chain.version.specification.get("end_date", oos_end.isoformat()))[:10]
    )
    start = body.start_date or oos_start
    end = body.end_date or market_end
    if start < oos_start or start > oos_end or end > market_end or start >= end:
        raise HTTPException(409, "信号起点必须位于 CV OOS 区间，结束日不得超过绑定行情版本")
    request = BacktestCreate(
        signal_source="model_oos", model_id=model_id,
        symbols=sorted(predictions["symbol"].astype(str).unique().tolist()),
        data_version_id=chain.version.id, start_date=start, end_date=end,
        initial_cash=body.initial_cash, top_n=body.top_n,
        minimum_probability=body.minimum_probability,
        rebalance_frequency=body.rebalance_frequency,
        max_volume_participation=body.max_volume_participation,
        lot_size=body.lot_size, commission=body.commission,
        minimum_commission=body.minimum_commission,
        stamp_duty=body.stamp_duty, slippage=body.slippage,
    )
    job, run = await create_backtest(
        session, request, owner_id=context.user.id, project_id=context.project.id
    )
    return BacktestSubmission(job_id=job.id, backtest_id=run.id)
