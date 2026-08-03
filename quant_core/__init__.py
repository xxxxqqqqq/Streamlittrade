"""量化研究平台的纯 Python 核心包。

这个包中的模块不得依赖 Streamlit、FastAPI 等界面框架。这样同一套行情、
策略和回测逻辑可以同时被本地脚本、Web API、异步训练 Worker 和测试代码复用。
"""

from .backtesting import calculate_metrics, get_entry_reason, run_backtest
from .data import MarketDataError, fetch_stock_data
from .demo_data import generate_demo_stock_data
from .strategy_runtime import resolve_strategy
from .market_data import DataQualityReport, standardize_market_frame, validate_market_dataset
from .portfolio_backtesting import run_portfolio_backtest
from .model_portfolio import build_model_signal_frames
from .akshare_data import fetch_akshare_stock_data, normalize_akshare_daily

__all__ = [
    "MarketDataError",
    "calculate_metrics",
    "fetch_stock_data",
    "get_entry_reason",
    "generate_demo_stock_data",
    "resolve_strategy",
    "run_backtest",
    "DataQualityReport",
    "standardize_market_frame",
    "validate_market_dataset",
    "run_portfolio_backtest",
    "build_model_signal_frames",
    "fetch_akshare_stock_data",
    "normalize_akshare_daily",
]
