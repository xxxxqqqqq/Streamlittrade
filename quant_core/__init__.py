"""Pure-Python quantitative research core with lazy public imports.

The API image intentionally carries fewer data-vendor and model-training
dependencies than the worker image.  Lazy exports preserve the established
``from quant_core import ...`` interface without making every process import
every optional runtime dependency at package initialization time.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS = {
    "calculate_metrics": (".backtesting", "calculate_metrics"),
    "get_entry_reason": (".backtesting", "get_entry_reason"),
    "run_backtest": (".backtesting", "run_backtest"),
    "MarketDataError": (".data", "MarketDataError"),
    "fetch_stock_data": (".data", "fetch_stock_data"),
    "generate_demo_stock_data": (".demo_data", "generate_demo_stock_data"),
    "resolve_strategy": (".strategy_runtime", "resolve_strategy"),
    "DataQualityReport": (".market_data", "DataQualityReport"),
    "standardize_market_frame": (".market_data", "standardize_market_frame"),
    "validate_market_dataset": (".market_data", "validate_market_dataset"),
    "run_portfolio_backtest": (".portfolio_backtesting", "run_portfolio_backtest"),
    "build_model_signal_frames": (".model_portfolio", "build_model_signal_frames"),
    "rank_model_predictions": (".model_portfolio", "rank_model_predictions"),
    "fetch_akshare_stock_data": (".akshare_data", "fetch_akshare_stock_data"),
    "normalize_akshare_daily": (".akshare_data", "normalize_akshare_daily"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value
