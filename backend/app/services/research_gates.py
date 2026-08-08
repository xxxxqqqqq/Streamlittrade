"""Deterministic gates connecting factor research to formal datasets."""

from __future__ import annotations

import hashlib
import json
import numpy as np
import pandas as pd
from typing import Any
from uuid import UUID


def calibration_evidence_complete(model_metrics: dict[str, Any] | None) -> bool:
    """Require both tuning OOS and one-time sealed reliability evidence."""
    metrics = model_metrics or {}
    required = {"brier_score", "log_loss", "expected_calibration_error", "bins"}
    tuning = metrics.get("calibration") or {}
    sealed = (metrics.get("sealed_evaluation") or {}).get("calibration") or {}
    return not required.difference(tuning) and not required.difference(sealed)


def factor_training_dates(dates, training_fraction: float, horizon: int):
    """Reserve all tuning/sealed dates and purge forward labels at the boundary."""
    unique_dates = np.array(sorted(pd.to_datetime(pd.Series(dates)).dropna().dt.normalize().unique()))
    training_end_pos = int(len(unique_dates) * training_fraction)
    evaluation_end_pos = training_end_pos - horizon
    if evaluation_end_pos < 20 or training_end_pos >= len(unique_dates):
        raise ValueError("Not enough dates to isolate factor training from tuning and sealed regions")
    return unique_dates[:evaluation_end_pos], unique_dates[training_end_pos]


def validate_factor_dataset_gate(
    *,
    snapshot_id: UUID,
    horizon: int,
    training_fraction: float,
    run_snapshot_id: UUID,
    run_status: str,
    run_parameters: dict[str, Any] | None,
    run_metrics: dict[str, Any] | None,
    selected_feature_slugs: list[str] | None,
) -> list[str]:
    """Return the frozen approved features or reject an invalid research gate."""
    if run_status != "succeeded":
        raise ValueError("因子研究尚未成功完成")
    if run_snapshot_id != snapshot_id:
        raise ValueError("因子研究与特征快照不匹配")
    researched_horizon = int((run_parameters or {}).get("forward_period", 0))
    if researched_horizon != int(horizon):
        raise ValueError("数据集预测周期必须与因子研究的未来收益周期一致")
    researched_training_fraction = float((run_parameters or {}).get("training_fraction", 0))
    if abs(researched_training_fraction - float(training_fraction)) > 1e-9:
        raise ValueError("数据集训练区比例必须与因子研究的训练区一致")
    selected = list(dict.fromkeys(selected_feature_slugs or []))
    if not selected:
        raise ValueError("该因子研究没有任何通过门禁的因子")
    metrics = run_metrics or {}
    if metrics.get("evaluation_scope") != "factor_training_only":
        raise ValueError("该因子研究曾读取调参区或封存区，不能用于正式数据集")
    screening = metrics.get("screening") or {}
    if screening.get("multiple_testing") != "benjamini_hochberg":
        raise ValueError("该因子研究未经多重试验假发现率控制")
    reported = list(screening.get("selected") or [])
    factors = metrics.get("factors") or {}
    if selected != reported or any(not (factors.get(slug) or {}).get("passed") for slug in selected):
        raise ValueError("因子研究的通过列表与审查指标不一致")
    return selected


def factor_gate_snapshot(*, run_id: UUID, snapshot_id: UUID, parameters: dict, metrics: dict, selected: list[str]) -> dict:
    """Create an immutable, content-addressed audit snapshot for dataset lineage."""
    payload = {
        "kind": "factor_research_gate_v1",
        "factor_research_id": str(run_id),
        "feature_snapshot_id": str(snapshot_id),
        "parameters": parameters,
        "selected_feature_slugs": selected,
        "metrics": metrics,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**payload, "content_sha256": hashlib.sha256(encoded).hexdigest()}
