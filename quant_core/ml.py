"""Leakage-safe feature engineering and time-series model evaluation tools."""

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pandas as pd


FEATURES = [
    "ret_1d", "ret_5d", "ret_20d", "ma_bias_5", "ma_bias_20",
    "volatility_20", "volume_ratio_20", "rsi_14",
]


@dataclass(frozen=True)
class TimeFold:
    """One expanding-window fold separated by purge and embargo date gaps."""

    fold: int
    train_index: np.ndarray
    test_index: np.ndarray
    train_start: str
    train_end: str
    test_start: str
    test_end: str


@dataclass(frozen=True)
class ThreeWayResearchSplit:
    """Immutable train/tuning/sealed partition on whole trading dates."""

    training_index: np.ndarray
    development_index: np.ndarray
    tuning_folds: tuple[TimeFold, ...]
    sealed_index: np.ndarray
    training_start: str
    training_end: str
    tuning_start: str
    tuning_end: str
    sealed_start: str
    sealed_end: str


def three_way_research_split(
    dates: pd.Series,
    *,
    training_fraction: float = 0.55,
    tuning_fraction: float = 0.25,
    n_tuning_splits: int = 3,
    purge_days: int = 5,
    embargo_days: int = 5,
) -> ThreeWayResearchSplit:
    """Create expanding tuning folds while keeping the final region sealed.

    Fractions are applied to unique trading dates, never individual symbol
    rows.  A purge/embargo gap separates training from tuning and development
    from the sealed holdout so forward labels cannot cross a boundary.
    """
    if not 0.3 <= training_fraction <= 0.8:
        raise ValueError("training_fraction must be between 0.3 and 0.8")
    if not 0.1 <= tuning_fraction <= 0.4:
        raise ValueError("tuning_fraction must be between 0.1 and 0.4")
    if training_fraction + tuning_fraction > 0.9:
        raise ValueError("at least 10% of dates must remain sealed")
    if n_tuning_splits < 2:
        raise ValueError("n_tuning_splits must be at least 2")

    normalized = pd.to_datetime(dates).dt.normalize()
    unique_dates = np.array(sorted(normalized.unique()))
    gap = purge_days + embargo_days
    training_end_pos = int(len(unique_dates) * training_fraction)
    tuning_end_pos = int(len(unique_dates) * (training_fraction + tuning_fraction))
    tuning_start_pos = training_end_pos + gap
    sealed_start_pos = tuning_end_pos + gap
    tuning_dates = unique_dates[tuning_start_pos:tuning_end_pos]
    sealed_dates = unique_dates[sealed_start_pos:]
    if len(unique_dates[:training_end_pos]) < 20 or len(tuning_dates) < n_tuning_splits or len(sealed_dates) < 20:
        raise ValueError("Not enough unique dates for train/tuning/sealed research")

    chunks = [chunk for chunk in np.array_split(tuning_dates, n_tuning_splits) if len(chunk)]
    folds: list[TimeFold] = []
    for fold_number, test_dates in enumerate(chunks, start=1):
        test_start_pos = int(np.searchsorted(unique_dates, test_dates[0]))
        train_dates = unique_dates[: max(0, test_start_pos - gap)]
        if len(train_dates) < 20:
            raise ValueError("Training region is too short after leakage gap")
        folds.append(
            TimeFold(
                fold=fold_number,
                train_index=np.flatnonzero(normalized.isin(train_dates).to_numpy()),
                test_index=np.flatnonzero(normalized.isin(test_dates).to_numpy()),
                train_start=str(pd.Timestamp(train_dates[0]).date()),
                train_end=str(pd.Timestamp(train_dates[-1]).date()),
                test_start=str(pd.Timestamp(test_dates[0]).date()),
                test_end=str(pd.Timestamp(test_dates[-1]).date()),
            )
        )

    training_dates = unique_dates[:training_end_pos]
    development_dates = unique_dates[:tuning_end_pos]
    return ThreeWayResearchSplit(
        training_index=np.flatnonzero(normalized.isin(training_dates).to_numpy()),
        development_index=np.flatnonzero(normalized.isin(development_dates).to_numpy()),
        tuning_folds=tuple(folds),
        sealed_index=np.flatnonzero(normalized.isin(sealed_dates).to_numpy()),
        training_start=str(pd.Timestamp(training_dates[0]).date()),
        training_end=str(pd.Timestamp(training_dates[-1]).date()),
        tuning_start=str(pd.Timestamp(tuning_dates[0]).date()),
        tuning_end=str(pd.Timestamp(tuning_dates[-1]).date()),
        sealed_start=str(pd.Timestamp(sealed_dates[0]).date()),
        sealed_end=str(pd.Timestamp(sealed_dates[-1]).date()),
    )


def purged_walk_forward_splits(
    dates: pd.Series,
    *,
    n_splits: int = 4,
    purge_days: int = 5,
    embargo_days: int = 5,
    minimum_train_fraction: float = 0.5,
) -> Iterator[TimeFold]:
    """Split unique dates, keeping every symbol for a date in the same fold."""
    normalized = pd.to_datetime(dates).dt.normalize()
    unique_dates = np.array(sorted(normalized.unique()))
    gap = purge_days + embargo_days
    minimum_train = max(20, int(len(unique_dates) * minimum_train_fraction))
    available = len(unique_dates) - minimum_train - gap
    if n_splits < 2 or available < n_splits:
        raise ValueError("Not enough unique dates for purged walk-forward validation")
    test_size = available // n_splits
    for fold in range(n_splits):
        test_start_pos = minimum_train + gap + fold * test_size
        test_end_pos = len(unique_dates) if fold == n_splits - 1 else test_start_pos + test_size
        train_end_pos = test_start_pos - gap
        train_dates = unique_dates[:train_end_pos]
        test_dates = unique_dates[test_start_pos:test_end_pos]
        train_index = np.flatnonzero(normalized.isin(train_dates).to_numpy())
        test_index = np.flatnonzero(normalized.isin(test_dates).to_numpy())
        yield TimeFold(
            fold=fold + 1,
            train_index=train_index,
            test_index=test_index,
            train_start=str(pd.Timestamp(train_dates[0]).date()),
            train_end=str(pd.Timestamp(train_dates[-1]).date()),
            test_start=str(pd.Timestamp(test_dates[0]).date()),
            test_end=str(pd.Timestamp(test_dates[-1]).date()),
        )


def economic_metrics(
    predictions: pd.DataFrame,
    *,
    horizon: int,
    top_fraction: float = 0.2,
    round_trip_cost_bps: float = 20.0,
) -> dict[str, float]:
    """Calculate cross-sectional IC and a cost-aware top-score portfolio proxy."""
    required = {"date", "symbol", "probability", "future_return"}
    missing = required.difference(predictions.columns)
    if missing:
        raise ValueError(f"Missing prediction columns: {sorted(missing)}")
    frame = predictions.copy().sort_values(["date", "probability"], ascending=[True, False])
    daily_ic: list[float] = []
    gross_returns: list[float] = []
    benchmark_returns: list[float] = []
    turnovers: list[float] = []
    previous_symbols: set[str] = set()
    for _, group in frame.groupby("date", sort=True):
        if len(group) > 1:
            ic = group["probability"].corr(group["future_return"], method="spearman")
            if pd.notna(ic):
                daily_ic.append(float(ic))
        count = max(1, int(np.ceil(len(group) * top_fraction)))
        selected = group.head(count)
        symbols = set(selected["symbol"].astype(str))
        turnover = 1.0 if not previous_symbols else 1 - len(symbols & previous_symbols) / max(len(symbols), 1)
        previous_symbols = symbols
        turnovers.append(float(turnover))
        gross_returns.append(float(selected["future_return"].mean()))
        benchmark_returns.append(float(group["future_return"].mean()))
    cost_rate = round_trip_cost_bps / 10_000
    net = np.asarray(gross_returns) - np.asarray(turnovers) * cost_rate
    benchmark = np.asarray(benchmark_returns)
    periods = 252 / max(horizon, 1)
    volatility = float(np.std(net, ddof=1)) if len(net) > 1 else 0.0
    ic_std = float(np.std(daily_ic, ddof=1)) if len(daily_ic) > 1 else 0.0
    return {
        "rank_ic": round(float(np.mean(daily_ic)) if daily_ic else 0.0, 6),
        "icir": round(float(np.mean(daily_ic) / ic_std) if ic_std else 0.0, 6),
        "top_quantile_return": round(float(np.mean(gross_returns)), 6),
        "cost_adjusted_return": round(float(np.mean(net)), 6),
        "excess_return": round(float(np.mean(net - benchmark)), 6),
        "annualized_return": round(float(np.mean(net) * periods), 6),
        "annualized_sharpe": round(float(np.mean(net) / volatility * np.sqrt(periods)) if volatility else 0.0, 6),
        "win_rate": round(float(np.mean(net > 0)), 6),
        "turnover": round(float(np.mean(turnovers)), 6),
        "round_trip_cost_bps": round(float(round_trip_cost_bps), 2),
    }


def build_training_frame(data: pd.DataFrame, symbol: str, horizon: int = 5) -> pd.DataFrame:
    """Build past-only features and retain the forward return used by the label."""
    frame = data.copy().sort_index()
    close, volume = frame["close"], frame["volume"]
    ret = close.pct_change()
    frame["ret_1d"] = ret
    frame["ret_5d"] = close.pct_change(5)
    frame["ret_20d"] = close.pct_change(20)
    frame["ma_bias_5"] = close / close.rolling(5).mean() - 1
    frame["ma_bias_20"] = close / close.rolling(20).mean() - 1
    frame["volatility_20"] = ret.rolling(20).std()
    frame["volume_ratio_20"] = volume / volume.rolling(20).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    frame["rsi_14"] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    future_return = close.shift(-horizon) / close - 1
    frame["future_return"] = future_return
    frame["label"] = (future_return > 0).where(future_return.notna())
    frame["symbol"] = symbol
    frame["date"] = frame.index
    result = frame[["date", "symbol", *FEATURES, "future_return", "label"]].dropna().copy()
    result["label"] = result["label"].astype(int)
    return result.reset_index(drop=True)
