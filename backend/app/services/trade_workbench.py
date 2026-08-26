"""Read-only joins across immutable research and backtest artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
import pyarrow.parquet as parquet
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.infrastructure.object_storage import download_file
from backend.app.models.backtest import BacktestRun
from backend.app.models.data_catalog import DataVersion, FeatureSnapshot
from backend.app.models.research import Dataset, Experiment, ModelVersion
from quant_core.model_portfolio import rank_model_predictions


@dataclass(frozen=True)
class ModelResearchChain:
    model: ModelVersion
    experiment: Experiment
    dataset: Dataset
    snapshot: FeatureSnapshot
    version: DataVersion


async def get_model_chain(
    session: AsyncSession, model_id: UUID, project_id: UUID
) -> ModelResearchChain:
    row = (
        await session.execute(
            select(ModelVersion, Experiment, Dataset)
            .join(Experiment, Experiment.id == ModelVersion.experiment_id)
            .join(Dataset, Dataset.id == Experiment.dataset_id)
            .where(ModelVersion.id == model_id, Experiment.project_id == project_id)
        )
    ).first()
    if row is None:
        raise HTTPException(404, "模型不存在或不属于当前项目")
    model, experiment, dataset = row
    if not model.prediction_artifact_uri:
        raise HTTPException(409, "模型没有可用于交易工作台的样本外预测产物")
    if not dataset.feature_snapshot_id:
        raise HTTPException(409, "模型没有绑定正式因子快照")
    snapshot = await session.scalar(
        select(FeatureSnapshot).where(
            FeatureSnapshot.id == dataset.feature_snapshot_id,
            FeatureSnapshot.project_id == project_id,
            FeatureSnapshot.status == "ready",
        )
    )
    if snapshot is None:
        raise HTTPException(409, "模型绑定的因子快照不可用")
    version = await session.scalar(
        select(DataVersion).where(
            DataVersion.id == snapshot.data_version_id,
            DataVersion.project_id == project_id,
            DataVersion.status == "ready",
            DataVersion.layer == "standardized",
        )
    )
    if version is None:
        raise HTTPException(409, "模型绑定的标准化数据版本不可用")
    return ModelResearchChain(model, experiment, dataset, snapshot, version)


async def get_model_backtest(
    session: AsyncSession, backtest_id: UUID, model_id: UUID, project_id: UUID
) -> BacktestRun:
    run = await session.scalar(
        select(BacktestRun).where(
            BacktestRun.id == backtest_id,
            BacktestRun.project_id == project_id,
            BacktestRun.model_id == model_id,
            BacktestRun.signal_source == "model_oos",
        )
    )
    if run is None:
        raise HTTPException(404, "该模型的回测不存在")
    if not run.artifact_uri:
        raise HTTPException(409, "回测产物尚未生成")
    return run


def read_parquet(
    uri: str,
    *,
    columns: list[str] | None = None,
    filters: list[tuple[str, str, Any]] | None = None,
) -> pd.DataFrame:
    """Stream an artifact to disk and let PyArrow prune columns and row groups.

    Trade-workbench requests run in the 512 MiB API container.  Reading the
    complete 87-factor snapshot into a BytesIO and then copying the DataFrame
    can exceed that limit.  A temporary local file keeps object bytes out of
    Python heap while Parquet projection/filtering bounds the decoded frame.
    """

    with TemporaryDirectory(prefix="quantforge-workbench-") as directory:
        path = download_file(uri, Path(directory) / "artifact.parquet")
        available = set(parquet.ParquetFile(path).schema_arrow.names)
        selected = [column for column in columns if column in available] if columns else None
        applicable_filters = (
            [item for item in filters if item[0] in available] if filters else None
        )
        return pd.read_parquet(path, columns=selected, filters=applicable_filters)


def read_artifact(uri: str) -> dict[str, Any]:
    with TemporaryDirectory(prefix="quantforge-workbench-") as directory:
        path = download_file(uri, Path(directory) / "artifact.json")
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)


def _date_text(value: Any) -> str:
    return pd.Timestamp(value).date().isoformat()


def _safe(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


def prediction_frame(chain: ModelResearchChain) -> pd.DataFrame:
    frame = read_parquet(
        chain.model.prediction_artifact_uri,
        columns=["date", "symbol", "prediction", "probability"],
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    return rank_model_predictions(frame)


def normalized_request(artifact: dict[str, Any]) -> dict[str, Any]:
    request = dict(artifact.get("request") or {})
    defaults = {
        "lot_size": 100,
        "commission": 0.0003,
        "minimum_commission": 5.0,
        "stamp_duty": 0.0005,
        "slippage": 0.001,
    }
    return {**defaults, **request}


def selection_rows(
    predictions: pd.DataFrame,
    symbol: str,
    *,
    artifact: dict[str, Any] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    frame = predictions.loc[predictions["symbol"] == str(symbol)].copy()
    if start_date:
        frame = frame.loc[frame["date"] >= pd.Timestamp(start_date)]
    if end_date:
        frame = frame.loc[frame["date"] <= pd.Timestamp(end_date)]
    construction = (artifact or {}).get("audit", {}).get("portfolio_construction", {})
    request = normalized_request(artifact or {})
    top_n = int(construction.get("top_n", request.get("top_n", 0)) or 0)
    threshold = float(construction.get("minimum_probability", request.get("minimum_probability", 0)) or 0)
    rebalances = {
        str(item.get("date"))[:10]: item
        for item in construction.get("rebalances", [])
    }
    rows: list[dict[str, Any]] = []
    for item in frame.itertuples(index=False):
        date = _date_text(item.date)
        decision = rebalances.get(date)
        probability = float(item.probability)
        rank = int(item.rank)
        selected = bool(decision and str(symbol) in decision.get("selected", []))
        if not decision:
            reason = "非调仓日，仅展示样本外预测"
        elif probability < threshold:
            reason = f"预测概率低于阈值 {threshold:.2%}"
        elif rank > top_n:
            reason = f"横截面排名第 {rank}，未进入 Top {top_n}"
        elif selected:
            reason = f"达到阈值并进入 Top {top_n}"
        else:
            reason = "未进入目标组合"
        rows.append(
            {
                "date": date,
                "prediction": _safe(getattr(item, "prediction", None)),
                "probability": probability,
                "rank": rank,
                "universe_size": int(item.universe_size),
                "threshold_met": probability >= threshold,
                "is_rebalance_day": decision is not None,
                "selected": selected,
                "reason": reason,
            }
        )
    return rows


def market_rows(chain: ModelResearchChain, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    requested_fields = [
        "date", "symbol", "open", "high", "low", "close", "volume", "amount",
        "is_suspended", "is_st", "limit_up", "limit_down",
    ]
    frame = read_parquet(
        chain.version.artifact_uri,
        columns=requested_fields,
        filters=[("symbol", "==", str(symbol))],
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str)
    frame = frame.loc[
        (frame["symbol"] == str(symbol))
        & frame["date"].between(pd.Timestamp(start), pd.Timestamp(end))
    ].sort_values("date")
    fields = [
        "date", "open", "high", "low", "close", "volume", "amount",
        "is_suspended", "is_st", "limit_up", "limit_down",
    ]
    fields = [field for field in fields if field in frame.columns]
    return [
        {key: (_date_text(value) if key == "date" else _safe(value)) for key, value in row.items()}
        for row in frame[fields].to_dict("records")
    ]


def factor_rows(chain: ModelResearchChain, symbol: str, start: str, end: str) -> list[dict[str, Any]]:
    metadata = chain.dataset.metadata_snapshot or {}
    feature_columns = list(metadata.get("features") or [])
    frame = read_parquet(
        chain.snapshot.artifact_uri,
        columns=["date", "symbol", *feature_columns] if feature_columns else None,
        filters=[("symbol", "==", str(symbol))],
    )
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str)
    frame = frame.loc[
        (frame["symbol"] == str(symbol))
        & frame["date"].between(pd.Timestamp(start), pd.Timestamp(end))
    ].sort_values("date")
    return [
        {key: (_date_text(value) if key == "date" else _safe(value)) for key, value in row.items() if key != "symbol"}
        for row in frame.to_dict("records")
    ]


def trade_events(artifact: dict[str, Any], symbol: str) -> list[dict[str, Any]]:
    result = []
    for raw in artifact.get("trades", []):
        if str(raw.get("symbol")) != str(symbol):
            continue
        item = _safe(raw)
        item["date"] = str(item.get("date", ""))[:10]
        if item.get("signal_date"):
            item["signal_date"] = str(item["signal_date"])[:10]
        if item.get("entry_date"):
            item["entry_date"] = str(item["entry_date"])[:10]
        result.append(item)
    return result
