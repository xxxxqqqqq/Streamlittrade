"""Point-in-time dynamic equity universe construction."""

from __future__ import annotations

from typing import Any

import pandas as pd


DEFAULT_UNIVERSE_POLICY = {
    "enabled": True,
    "min_history_days": 120,
    "min_price": 3.0,
    "liquidity_lookback": 20,
    "min_avg_turnover": 1_000_000.0,
    "max_members": 100,
}


def apply_dynamic_universe(frame: pd.DataFrame, policy: dict[str, Any] | None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Mark daily membership using only observations available through that close."""
    rules = {**DEFAULT_UNIVERSE_POLICY, **dict(policy or {})}
    result = frame.copy().sort_values(["symbol", "date"]).reset_index(drop=True)
    if not bool(rules["enabled"]):
        result["universe_member"] = True
        result["universe_rank"] = 1
    else:
        lookback = int(rules["liquidity_lookback"])
        result["_history_days"] = result.groupby("symbol").cumcount() + 1
        result["_turnover"] = result["close"].astype(float) * result["volume"].astype(float)
        result["_avg_turnover"] = result.groupby("symbol", sort=False)["_turnover"].transform(
            lambda values: values.rolling(lookback, min_periods=lookback).mean()
        )
        result["universe_rank"] = result.groupby("date")["_avg_turnover"].rank(
            method="first", ascending=False, na_option="bottom"
        ).astype("Int64")
        eligible = (
            (result["_history_days"] >= int(rules["min_history_days"]))
            & (result["close"].astype(float) >= float(rules["min_price"]))
            & (result["volume"].astype(float) > 0)
            & (result["_avg_turnover"] >= float(rules["min_avg_turnover"]))
            & (result["universe_rank"] <= int(rules["max_members"]))
        )
        result["universe_member"] = eligible.fillna(False).astype(bool)
        result = result.drop(columns=["_history_days", "_turnover", "_avg_turnover"])
    daily = result.groupby("date")["universe_member"].sum()
    report = {
        "kind": "point_in_time_liquidity_universe_v1",
        "policy": rules,
        "candidate_symbols": int(result["symbol"].nunique()),
        "eligible_rows": int(result["universe_member"].sum()),
        "eligible_dates": int((daily > 0).sum()),
        "average_daily_members": round(float(daily.mean()), 4) if len(daily) else 0.0,
        "max_daily_members": int(daily.max()) if len(daily) else 0,
        "uses_future_data": False,
    }
    return result.sort_values(["date", "symbol"]).reset_index(drop=True), report
