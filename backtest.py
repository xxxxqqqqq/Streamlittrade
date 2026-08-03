"""旧导入路径的兼容层。

量化回测实现已迁移到 :mod:`quant_core.backtesting`。保留这个文件可以让现有
Streamlit 页面、优化器和用户策略继续使用 ``from backtest import ...``，同时
未来的 FastAPI 与训练 Worker 可直接依赖 ``quant_core``。
"""

from quant_core.backtesting import calculate_metrics, get_entry_reason, run_backtest

__all__ = ["calculate_metrics", "get_entry_reason", "run_backtest"]
