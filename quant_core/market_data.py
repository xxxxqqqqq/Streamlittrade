"""Canonical daily-bar contract and auditable market-data quality checks."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Mapping

import numpy as np
import pandas as pd


REQUIRED_MARKET_COLUMNS = ("open", "high", "low", "close", "volume")
OPTIONAL_DEFAULTS = {
    "amount": np.nan,
    "adj_factor": 1.0,
    "is_suspended": False,
    "is_st": False,
    "limit_up": np.nan,
    "limit_down": np.nan,
    "cash_dividend": 0.0,
    "split_ratio": 1.0,
}


@dataclass(frozen=True)
class DataQualityReport:
    symbol_count: int
    row_count: int
    date_min: str
    date_max: str
    duplicate_rows: int
    missing_values: int
    invalid_ohlc_rows: int
    nonpositive_price_rows: int
    suspended_rows: int
    missing_calendar_rows: int
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def standardize_market_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Validate and normalize one symbol without silently repairing bad prices."""
    if frame is None or frame.empty:
        raise ValueError(f"{symbol}: market data is empty")
    missing = set(REQUIRED_MARKET_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"{symbol}: missing market columns: {sorted(missing)}")
    result = frame.copy()
    result.index = pd.DatetimeIndex(pd.to_datetime(result.index)).normalize()
    result.index.name = "date"
    result["symbol"] = symbol
    for column, default in OPTIONAL_DEFAULTS.items():
        if column not in result:
            result[column] = default
    numeric = [*REQUIRED_MARKET_COLUMNS, "amount", "adj_factor", "limit_up", "limit_down", "cash_dividend", "split_ratio"]
    for column in numeric:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["is_suspended"] = result["is_suspended"].fillna(False).astype(bool) | result["volume"].fillna(0).le(0)
    result["is_st"] = result["is_st"].fillna(False).astype(bool)
    previous_close = result["close"].shift(1)
    limit_ratio = np.where(result["is_st"], 0.05, 0.10)
    result["limit_up"] = result["limit_up"].fillna(pd.Series(previous_close * (1 + limit_ratio), index=result.index))
    result["limit_down"] = result["limit_down"].fillna(pd.Series(previous_close * (1 - limit_ratio), index=result.index))
    return result.sort_index()


def validate_market_dataset(frames: Mapping[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], DataQualityReport]:
    """Return canonical frames plus a dataset-level quality report."""
    if not frames:
        raise ValueError("Market dataset must contain at least one symbol")
    canonical = {symbol: standardize_market_frame(frame, symbol) for symbol, frame in frames.items()}
    all_dates = sorted(set().union(*(set(frame.index) for frame in canonical.values())))
    duplicate_rows = missing_values = invalid_ohlc = nonpositive = suspended = missing_calendar = 0
    for frame in canonical.values():
        duplicate_rows += int(frame.index.duplicated(keep=False).sum())
        missing_values += int(frame[list(REQUIRED_MARKET_COLUMNS)].isna().sum().sum())
        invalid_ohlc += int(((frame["high"] < frame[["open", "close", "low"]].max(axis=1)) | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))).sum())
        nonpositive += int((frame[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
        suspended += int(frame["is_suspended"].sum())
        missing_calendar += len(set(all_dates).difference(frame.index))
    warnings = []
    if duplicate_rows: warnings.append("duplicate_dates")
    if missing_values: warnings.append("missing_required_values")
    if invalid_ohlc: warnings.append("invalid_ohlc")
    if nonpositive: warnings.append("nonpositive_prices")
    if missing_calendar: warnings.append("unbalanced_symbol_calendar")
    report = DataQualityReport(
        symbol_count=len(canonical), row_count=sum(len(frame) for frame in canonical.values()),
        date_min=str(pd.Timestamp(all_dates[0]).date()), date_max=str(pd.Timestamp(all_dates[-1]).date()),
        duplicate_rows=duplicate_rows, missing_values=missing_values, invalid_ohlc_rows=invalid_ohlc,
        nonpositive_price_rows=nonpositive, suspended_rows=suspended,
        missing_calendar_rows=missing_calendar, warnings=warnings,
    )
    if duplicate_rows or missing_values or invalid_ohlc or nonpositive:
        raise ValueError(f"Market data failed quality gate: {report.to_dict()}")
    return canonical, report
