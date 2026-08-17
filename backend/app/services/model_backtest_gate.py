"""Pure governance helpers for trustworthy model portfolio backtests."""

from __future__ import annotations

from typing import Any


SEALED_DEFAULT_PORTFOLIO_PROTOCOL: dict[str, Any] = {
    "top_n": 5,
    "minimum_probability": 0.55,
    "rebalance_frequency": 5,
    "initial_cash": 1_000_000,
    "max_volume_participation": 0.05,
    "lot_size": 100,
    "commission": 0.0003,
    "minimum_commission": 5.0,
    "stamp_duty": 0.0005,
    "slippage": 0.001,
}


def prediction_window(
    model_metrics: dict[str, Any] | None,
    sealed_metrics: dict[str, Any] | None,
    scope: str,
) -> tuple[str, str]:
    """Return the complete immutable date window allowed for one OOS scope."""

    if scope == "sealed_oos":
        metrics = sealed_metrics or {}
        if metrics.get("evaluation_scope") != "final_sealed_holdout":
            raise ValueError("最终封存区评估尚未成功完成")
        start, end = metrics.get("sealed_start"), metrics.get("sealed_end")
    elif scope == "tuning_oos":
        metrics = model_metrics or {}
        if metrics.get("evaluation_scope") != "tuning_oos":
            raise ValueError("模型没有调参区样本外预测")
        tuning = (metrics.get("research_split") or {}).get("tuning") or {}
        start, end = tuning.get("start"), tuning.get("end")
    else:
        raise ValueError("不受支持的模型回测预测作用域")
    if not start or not end:
        raise ValueError("样本外预测缺少不可变日期边界")
    return str(start), str(end)


def sealed_portfolio_protocol(sealed_metrics: dict[str, Any] | None) -> tuple[dict[str, Any], str]:
    """Load the pre-registered portfolio policy or a flagged legacy fallback."""

    metrics = sealed_metrics or {}
    registered = metrics.get("portfolio_protocol")
    if isinstance(registered, dict) and registered:
        return {**SEALED_DEFAULT_PORTFOLIO_PROTOCOL, **registered}, "preregistered"
    return dict(SEALED_DEFAULT_PORTFOLIO_PROTOCOL), "legacy_default_not_preregistered"
