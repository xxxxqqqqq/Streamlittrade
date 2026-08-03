"""用于平台连通性测试的确定性日线数据。

演示数据只验证任务链路，绝不能作为策略有效性或投资收益的证据。
"""

from datetime import date

import numpy as np
import pandas as pd


def generate_demo_stock_data(start_date: date, end_date: date, seed: int = 42) -> pd.DataFrame:
    """生成结果可重复、字段与真实行情一致的工作日日线。"""
    index = pd.date_range(start_date, end_date, freq="B")
    if len(index) < 80:
        raise ValueError("演示回测至少需要80个工作日")

    rng = np.random.default_rng(seed)
    # 周期趋势叠加小幅随机扰动，便于内置策略产生可观察的信号。
    cycle = 0.0025 * np.sin(np.arange(len(index)) / 13)
    returns = 0.00035 + cycle + rng.normal(0, 0.012, len(index))
    close = 20 * np.exp(np.cumsum(returns))
    previous_close = np.concatenate(([close[0]], close[:-1]))
    open_price = previous_close * (1 + rng.normal(0, 0.003, len(index)))
    high = np.maximum(open_price, close) * (1 + rng.uniform(0.002, 0.018, len(index)))
    low = np.minimum(open_price, close) * (1 - rng.uniform(0.002, 0.018, len(index)))
    volume = rng.integers(300_000, 2_000_000, len(index)).astype(float)
    volume[::17] *= 3

    return pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )
