"""AKShare A-share daily adapter with a stable platform-facing schema."""

from __future__ import annotations

import time
from typing import Any, Callable

import pandas as pd

from .data import MarketDataError


AKSHARE_COLUMNS = {
    "日期": "date", "股票代码": "symbol", "开盘": "open", "收盘": "close",
    "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
}


def normalize_akshare_daily(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Normalize the documented ``stock_zh_a_hist`` response."""
    if frame is None or frame.empty:
        raise MarketDataError(f"AKShare returned no daily bars for {symbol}")
    result = frame.rename(columns=AKSHARE_COLUMNS).copy()
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required.difference(result.columns)
    if missing:
        raise MarketDataError(f"AKShare response missing columns: {sorted(missing)}")
    result["date"] = pd.to_datetime(result["date"], errors="raise")
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in result:
            result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.set_index("date")
    columns = ["open", "high", "low", "close", "volume"]
    if "amount" in result:
        columns.append("amount")
    return result[columns].dropna(subset=["open", "high", "low", "close", "volume"]).sort_index()


def fetch_akshare_stock_data(
    symbol: str, start_date: str, end_date: str, *, adjust: str = "qfq",
    max_retries: int = 3, sleeper: Callable[[float], None] = time.sleep,
    client: Any | None = None,
) -> pd.DataFrame:
    """Fetch and normalize AKShare ``stock_zh_a_hist`` daily bars."""
    symbol = str(symbol).strip()
    if len(symbol) != 6 or not symbol.isdigit():
        raise ValueError("AKShare A-share symbol must be a six-digit code")
    if adjust not in {"", "qfq", "hfq"}:
        raise ValueError("adjust must be one of '', 'qfq', or 'hfq'")
    if client is None:
        try:
            import akshare as client
        except ImportError as exc:
            raise MarketDataError("AKShare is not installed in the worker environment") from exc
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            raw = client.stock_zh_a_hist(
                symbol=symbol, period="daily", start_date=str(start_date),
                end_date=str(end_date), adjust=adjust,
            )
            return normalize_akshare_daily(raw, symbol)
        except Exception as exc:
            last_error = exc
            if attempt < max_retries - 1:
                sleeper(2**attempt)
    raise MarketDataError(f"AKShare failed for {symbol} after {max_retries} attempts: {last_error}") from last_error
