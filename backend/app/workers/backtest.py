"""RQ worker for audited single-symbol and shared-cash portfolio backtests."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
from sqlalchemy import select

from backend.app.db.sync_session import SyncSessionFactory
from backend.app.infrastructure.object_storage import upload_json
from backend.app.models.backtest import BacktestRun
from backend.app.models.data_catalog import DataVersion
from backend.app.models.job import Job
from backend.app.models.research import Experiment, ModelVersion
from backend.app.infrastructure.object_storage import download_bytes
import io
from quant_core import (
    build_model_signal_frames, fetch_stock_data, generate_demo_stock_data, resolve_strategy, run_backtest,
    run_portfolio_backtest, validate_market_dataset,
)


class TaskCanceled(RuntimeError):
    pass


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict): return {str(k): _json_safe(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [_json_safe(v) for v in value]
    if isinstance(value, np.integer): return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value); return number if math.isfinite(number) else None
    if isinstance(value, (pd.Timestamp, datetime)): return value.isoformat()
    return value


def _set_progress(job_id: UUID, progress: float) -> None:
    with SyncSessionFactory() as session:
        current = session.get(Job, job_id)
        if current and current.status == "cancel_requested":
            current.status, current.completed_at = "canceled", datetime.now(UTC)
            session.commit(); raise TaskCanceled("Task canceled by user")
        if current:
            current.progress = progress; session.commit()


def _load_symbol(payload: dict[str, Any], symbol: str, seed: int = 42) -> pd.DataFrame:
    start, end = pd.Timestamp(payload["start_date"]).date(), pd.Timestamp(payload["end_date"]).date()
    if payload["data_source"] == "demo": return generate_demo_stock_data(start, end, seed=seed)
    return fetch_stock_data(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))


def _signals(payload: dict[str, Any], market: pd.DataFrame) -> pd.DataFrame:
    strategy, parameters, _ = resolve_strategy(payload["strategy_name"], payload.get("strategy_parameters", {}))
    return strategy(market, **parameters)


def _versioned_frames(payload: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """Load the exact immutable standardized data version selected by the request."""
    version_id = UUID(str(payload["data_version_id"]))
    with SyncSessionFactory() as session:
        version = session.get(DataVersion, version_id)
        if not version or version.layer != "standardized" or version.status != "ready" or not version.artifact_uri:
            raise LookupError("Ready standardized data version does not exist")
        uri = version.artifact_uri
    frame = pd.read_parquet(io.BytesIO(download_bytes(uri)))
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str)
    start, end = pd.Timestamp(payload["start_date"]), pd.Timestamp(payload["end_date"])
    frame = frame.loc[frame["date"].between(start, end)]
    requested = {str(symbol) for symbol in payload.get("symbols") or []}
    if payload.get("run_type") == "single" and payload.get("symbol") not in {"", "DATA_VERSION"}:
        requested.add(str(payload["symbol"]))
    if requested:
        frame = frame.loc[frame["symbol"].isin(requested)]
    if frame.empty:
        raise ValueError("Selected data version has no rows for this universe and date range")
    return {
        symbol: group.drop(columns=["symbol"]).set_index("date").sort_index()
        for symbol, group in frame.groupby("symbol", sort=True)
    }


def _benchmark(frames: dict[str, pd.DataFrame]) -> pd.Series:
    """Build the transparent equal-weight buy-and-hold benchmark."""
    normalized = [frame.close / frame.close.iloc[0] for frame in frames.values()]
    return pd.concat(normalized, axis=1).mean(axis=1) * 100


def _model_oos_portfolio_result(payload: dict[str, Any], project_id: UUID):
    """Backtest immutable OOS probabilities against their exact market version."""
    model_id = UUID(str(payload["model_id"]))
    with SyncSessionFactory() as session:
        row = session.execute(
            select(ModelVersion, Experiment)
            .join(Experiment, Experiment.id == ModelVersion.experiment_id)
            .where(
                ModelVersion.id == model_id,
                Experiment.project_id == project_id,
            )
        ).first()
        if row is None:
            raise LookupError("Model does not exist in this project")
        model, experiment = row
        if not model.prediction_artifact_uri:
            raise ValueError("Model has no out-of-sample prediction artifact")
        prediction_uri = model.prediction_artifact_uri
        model_name, model_version, algorithm = model.name, model.version, model.algorithm
        reproducibility = dict(model.reproducibility or {})

    predictions = pd.read_parquet(io.BytesIO(download_bytes(prediction_uri)))
    predictions["date"] = pd.to_datetime(predictions["date"]).dt.normalize()
    start, end = pd.Timestamp(payload["start_date"]), pd.Timestamp(payload["end_date"])
    predictions = predictions.loc[predictions["date"].between(start, end)].copy()
    if predictions.empty:
        raise ValueError("No OOS predictions overlap the requested backtest period")

    market_frames = _versioned_frames(payload)
    first_prediction = predictions["date"].min()
    # Remove the pre-OOS history from performance measurement.  One or more
    # post-prediction bars remain available for next-open execution and exit.
    market_frames = {
        symbol: frame.loc[frame.index >= first_prediction].copy()
        for symbol, frame in market_frames.items()
        if not frame.loc[frame.index >= first_prediction].empty
    }
    signal_frames, construction = build_model_signal_frames(
        market_frames,
        predictions,
        top_n=int(payload["top_n"]),
        minimum_probability=float(payload["minimum_probability"]),
        rebalance_frequency=int(payload["rebalance_frequency"]),
    )
    trades, equity, metrics, audit = run_portfolio_backtest(
        signal_frames,
        initial_cash=float(payload["initial_cash"]),
        max_positions=int(payload["top_n"]),
        max_volume_participation=float(payload["max_volume_participation"]),
        benchmark=_benchmark(signal_frames),
    )
    dataset_meta = reproducibility.get("dataset") or {}
    source_meta = dataset_meta.get("source") if isinstance(dataset_meta, dict) else {}
    audit["portfolio_construction"] = construction
    audit["model_lineage"] = {
        "model_id": str(model_id),
        "model_name": model_name,
        "model_version": model_version,
        "algorithm": algorithm,
        "model_sha256": reproducibility.get("model_sha256"),
        "prediction_sha256": reproducibility.get("prediction_sha256"),
        "prediction_artifact_uri": prediction_uri,
        "data_version_id": str(payload["data_version_id"]),
        "data_version_sha256": (
            source_meta.get("data_version_sha256")
            if isinstance(source_meta, dict) else None
        ),
        "validation": "purged_walk_forward_oos",
    }
    metrics.update(
        {
            "signal_source": "model_oos",
            "model_id": str(model_id),
            "prediction_rows": construction["prediction_rows"],
            "prediction_dates": construction["prediction_dates"],
            "rebalance_count": construction["rebalance_count"],
            "top_n": construction["top_n"],
            "minimum_probability": construction["minimum_probability"],
            "rebalance_frequency": construction["rebalance_frequency"],
        }
    )
    return trades, equity, metrics, audit


def _portfolio_result(payload: dict[str, Any], project_id: UUID):
    if payload.get("signal_source") == "model_oos":
        return _model_oos_portfolio_result(payload, project_id)
    if payload["data_source"] == "data_version":
        market_frames = _versioned_frames(payload)
    else:
        market_frames = {
            symbol: _load_symbol(payload, symbol, 42 + index)
            for index, symbol in enumerate(payload["symbols"])
        }
    frames = {symbol: _signals(payload, market) for symbol, market in market_frames.items()}
    # Equal-weight normalized close series provides a transparent default
    # benchmark when no official benchmark feed has been selected.
    trades, equity, metrics, audit = run_portfolio_backtest(
        frames, initial_cash=float(payload["initial_cash"]), max_positions=int(payload["max_positions"]),
        max_volume_participation=float(payload["max_volume_participation"]), benchmark=_benchmark(frames),
    )
    return trades, equity, metrics, audit


def execute_backtest(job_id: str) -> dict[str, Any]:
    parsed_id = UUID(job_id)
    try:
        with SyncSessionFactory() as session:
            job = session.get(Job, parsed_id)
            run = session.scalar(select(BacktestRun).where(BacktestRun.job_id == parsed_id))
            if not job or not run: raise LookupError(f"Backtest job {job_id} does not exist")
            job.status, job.progress, job.started_at, job.error_message = "running", 5.0, datetime.now(UTC), None
            job.attempt += 1
            job.lease_expires_at = datetime.now(UTC) + timedelta(minutes=15)
            session.commit(); payload, run_id = dict(job.payload), run.id
        _set_progress(parsed_id, 20)
        if payload.get("run_type", "single") == "portfolio":
            trades, equity, metrics, audit = _portfolio_result(payload, run.project_id)
        else:
            if payload["data_source"] == "data_version":
                loaded = _versioned_frames(payload)
                if len(loaded) != 1:
                    raise ValueError("Single-asset versioned backtest must resolve exactly one symbol")
                resolved_symbol, market = next(iter(loaded.items()))
            else:
                resolved_symbol = payload["symbol"]
                market = _load_symbol(payload, resolved_symbol)
            _, quality = validate_market_dataset({resolved_symbol: market})
            trades, equity, metrics = run_backtest(_signals(payload, market), initial_cash=float(payload["initial_cash"]))
            audit = {"data_quality": quality.to_dict(), "constraint_model": {"signal_execution":"next_trading_day_open","settlement":"T+1","lot_size":100}}
        if trades is None or equity is None or "error" in metrics: raise RuntimeError(metrics.get("error", "Backtest returned no result"))
        _set_progress(parsed_id, 75)
        safe_metrics, safe_audit = _json_safe(metrics), _json_safe(audit)
        artifact = {
            "schema_version": 2, "job_id": job_id, "backtest_id": str(run_id), "request": payload,
            "metrics": safe_metrics, "audit": safe_audit,
            "trades": json.loads(trades.to_json(orient="records", date_format="iso")),
            "equity": [{"date": pd.Timestamp(date).isoformat(), "value": float(value)} for date,value in equity.items()],
        }
        artifact_uri = upload_json(f"backtests/{run_id}/result.json", json.dumps(artifact, ensure_ascii=False, allow_nan=False).encode())
        with SyncSessionFactory() as session:
            current_job = session.get(Job, parsed_id)
            current_run = session.scalar(select(BacktestRun).where(BacktestRun.job_id == parsed_id))
            if not current_job or not current_run: raise LookupError("Backtest record disappeared")
            current_run.metrics, current_run.data_quality, current_run.artifact_uri = safe_metrics, safe_audit["data_quality"], artifact_uri
            current_job.status, current_job.progress, current_job.result_summary = "succeeded", 100, safe_metrics
            current_job.completed_at = datetime.now(UTC)
            current_job.lease_expires_at = None
            session.commit()
        return {"backtest_id": str(run_id), "artifact_uri": artifact_uri, "metrics": safe_metrics}
    except Exception as exc:
        with SyncSessionFactory() as session:
            failed = session.get(Job, parsed_id)
            if failed:
                failed.status = "canceled" if failed.status in {"cancel_requested","canceled"} else "failed"
                failed.completed_at, failed.error_message = datetime.now(UTC), str(exc)[:2000]
                failed.lease_expires_at = None
                session.commit()
        raise
