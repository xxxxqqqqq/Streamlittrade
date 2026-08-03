"""Convert leakage-safe model probabilities into auditable portfolio signals."""

from __future__ import annotations

from typing import Mapping

import pandas as pd


REQUIRED_PREDICTION_COLUMNS = {"date", "symbol", "probability"}


def build_model_signal_frames(
    market_frames: Mapping[str, pd.DataFrame],
    predictions: pd.DataFrame,
    *,
    top_n: int = 10,
    minimum_probability: float = 0.5,
    rebalance_frequency: int = 5,
) -> tuple[dict[str, pd.DataFrame], dict]:
    """Build persistent Top-N holdings from point-in-time model probabilities.

    A probability observed at the close of day ``t`` becomes a signal on day
    ``t``.  The execution engine consumes that signal at the next trading day's
    open, so no same-bar execution or future return is used for order creation.
    Between rebalance dates the last selected basket is held.  If a scheduled
    rebalance date has no OOS predictions, positions are cleared rather than
    silently carrying stale scores through a validation gap.
    """
    missing = REQUIRED_PREDICTION_COLUMNS.difference(predictions.columns)
    if missing:
        raise ValueError(f"Prediction artifact is missing columns: {sorted(missing)}")
    if not 1 <= top_n <= 100:
        raise ValueError("top_n must be between 1 and 100")
    if not 0 <= minimum_probability <= 1:
        raise ValueError("minimum_probability must be between 0 and 1")
    if not 1 <= rebalance_frequency <= 60:
        raise ValueError("rebalance_frequency must be between 1 and 60")

    frames = {symbol: frame.copy().sort_index() for symbol, frame in market_frames.items()}
    for frame in frames.values():
        frame["signal"] = False
        frame["score"] = 0.0

    scored = predictions[["date", "symbol", "probability"]].copy()
    scored["date"] = pd.to_datetime(scored["date"]).dt.normalize()
    scored["symbol"] = scored["symbol"].astype(str)
    scored["probability"] = pd.to_numeric(scored["probability"], errors="coerce")
    scored = scored.dropna(subset=["date", "symbol", "probability"])
    if scored.duplicated(["date", "symbol"]).any():
        raise ValueError("Prediction artifact contains duplicate date/symbol rows")
    scored = scored.loc[scored["symbol"].isin(frames)]
    if scored.empty:
        raise ValueError("No predictions overlap the selected market-data universe")

    market_dates = sorted(set().union(*(set(frame.index) for frame in frames.values())))
    by_date = {date: group for date, group in scored.groupby("date", sort=True)}
    current_targets: dict[str, float] = {}
    last_rebalance_index: int | None = None
    rebalance_log: list[dict] = []
    signal_rows = 0

    for index, date in enumerate(market_dates):
        due = last_rebalance_index is None or index - last_rebalance_index >= rebalance_frequency
        if due:
            candidates = by_date.get(pd.Timestamp(date).normalize())
            if candidates is None:
                current_targets = {}
            else:
                selected = (
                    candidates.loc[candidates["probability"] >= minimum_probability]
                    .sort_values(["probability", "symbol"], ascending=[False, True])
                    .head(top_n)
                )
                current_targets = {
                    str(row.symbol): float(row.probability)
                    for row in selected.itertuples(index=False)
                }
                rebalance_log.append(
                    {
                        "date": pd.Timestamp(date).date().isoformat(),
                        "selected": list(current_targets),
                        "scores": {key: round(value, 8) for key, value in current_targets.items()},
                    }
                )
            last_rebalance_index = index

        for symbol, probability in current_targets.items():
            frame = frames.get(symbol)
            if frame is not None and date in frame.index:
                frame.loc[date, "signal"] = True
                frame.loc[date, "score"] = probability
                signal_rows += 1

    if not rebalance_log or not any(item["selected"] for item in rebalance_log):
        raise ValueError("Portfolio construction produced no eligible model selections")

    audit = {
        "method": "cross_sectional_top_n",
        "weighting": "equal_weight",
        "top_n": top_n,
        "minimum_probability": minimum_probability,
        "rebalance_frequency": rebalance_frequency,
        "prediction_rows": int(len(scored)),
        "prediction_dates": int(scored["date"].nunique()),
        "signal_rows": signal_rows,
        "rebalance_count": len(rebalance_log),
        "rebalances": rebalance_log,
        "execution_lag": "next_trading_day_open",
        "out_of_sample_only": True,
    }
    return frames, audit
