"""
模块：风险模型 (risk_model.py)
功能：VaR/CVaR 计算、压力测试、极值理论、最大回撤分析
依赖：pandas, numpy, scipy
"""
import pandas as pd
import numpy as np
from scipy import stats
from typing import Dict


# ============================================================
# VaR & CVaR 计算
# ============================================================

def compute_var(returns: pd.Series, confidence: float = 0.95,
                method: str = 'historical') -> Dict:
    """
    计算 Value at Risk (在险价值)

    Args:
        returns:    日收益率序列
        confidence: 置信水平，默认 95%
        method:     'historical'(历史模拟) / 'parametric'(参数法) / 'cornish_fisher'(修正)

    Returns:
        dict: VaR 和 CVaR 结果
    """
    returns = returns.dropna()

    if method == 'historical':
        var = np.percentile(returns, (1 - confidence) * 100)
        cvar = returns[returns <= var].mean()

    elif method == 'parametric':
        mu = returns.mean()
        sigma = returns.std()
        z_score = stats.norm.ppf(1 - confidence)
        var = mu - z_score * sigma
        # CVaR for parametric normal distribution
        cvar = mu - sigma * stats.norm.pdf(stats.norm.ppf(1 - confidence)) / (1 - confidence)

    elif method == 'cornish_fisher':
        # Cornish-Fisher 展开，考虑偏度和峰度
        mu = returns.mean()
        sigma = returns.std()
        skew = stats.skew(returns)
        kurt = stats.kurtosis(returns, fisher=True)
        z = stats.norm.ppf(1 - confidence)

        z_cf = z + (skew / 6) * (z**2 - 1) + (kurt / 24) * (z**3 - 3*z) \
               - (skew**2 / 36) * (2*z**3 - 5*z)
        var = mu - z_cf * sigma
        cvar = mu - sigma * stats.norm.pdf(z_cf) / (1 - confidence)

    else:
        raise ValueError(f"未知方法: {method}")

    return {
        'VaR': round(var * 100, 4),        # 百分比
        'CVaR': round(cvar * 100, 4),       # 条件在险价值（期望亏损）
        'VaR_金额': f"每万元日亏损不超过 {abs(var*10000):.0f} 元",
        '置信水平': f"{confidence*100:.0f}%",
        '方法': method
    }


def rolling_var(returns: pd.Series, window: int = 60,
                confidence: float = 0.95) -> pd.Series:
    """
    滚动 VaR 计算：观察风险随时间变化

    Returns:
        pd.Series: 滚动 VaR 时间序列
    """
    return returns.rolling(window).apply(
        lambda x: np.percentile(x.dropna(), (1 - confidence) * 100)
    )


# ============================================================
# 压力测试
# ============================================================

def stress_test(returns: pd.Series) -> Dict:
    """
    极端行情压力测试

    模拟场景：
    - 2008 金融危机级别（-30% 跌幅）
    - 2015 股灾级别（-40% 跌幅）
    - 2020 疫情级别（快速暴跌 + 反弹）
    - 自定义极端场景

    Returns:
        dict: 各场景下的预估亏损
    """
    current_value = 100000  # 基准 10万

    scenarios = {
        '温和回调 (-10%)': -0.10,
        '中度下跌 (-20%)': -0.20,
        '2015股灾 (-40%)': -0.40,
        '2008金融海啸 (-50%)': -0.50,
        '极端暴跌 (-60%)': -0.60,
    }

    results = []
    for name, shock in scenarios.items():
        loss = current_value * shock
        results.append({
            '场景': name,
            '预估亏损': f"{loss:,.0f} 元",
            '剩余资金': f"{current_value + loss:,.0f} 元",
            '跌幅': f"{shock*100:.0f}%"
        })

    # 基于历史最差情况的真实压力测试
    worst_day = returns.min()
    worst_week = returns.rolling(5).sum().min()
    worst_month = returns.rolling(20).sum().min()

    results.append({
        '场景': '历史最差单日',
        '预估亏损': f"{current_value * abs(worst_day):,.0f} 元",
        '剩余资金': f"{current_value * (1 + worst_day):,.0f} 元",
        '跌幅': f"{worst_day*100:.2f}%"
    })
    results.append({
        '场景': '历史最差5日',
        '预估亏损': f"{current_value * abs(worst_week):,.0f} 元",
        '剩余资金': f"{current_value * (1 + worst_week):,.0f} 元",
        '跌幅': f"{worst_week*100:.2f}%"
    })
    results.append({
        '场景': '历史最差20日',
        '预估亏损': f"{current_value * abs(worst_month):,.0f} 元",
        '剩余资金': f"{current_value * (1 + worst_month):,.0f} 元",
        '跌幅': f"{worst_month*100:.2f}%"
    })

    return pd.DataFrame(results)


# ============================================================
# 最大回撤深度与恢复时间分析
# ============================================================

def drawdown_analysis(equity_series: pd.Series) -> Dict:
    """
    深度回撤分析：每个回撤区间的深度、持续时间、恢复时间

    Returns:
        dict: {
            'drawdown_periods': 各回撤周期详情,
            'avg_drawdown_depth': 平均回撤深度,
            'avg_recovery_days': 平均恢复天数,
            'max_drawdown_depth': 最大回撤深度,
            'total_drawdown_ratio': 处于回撤中的时间占比
        }
    """
    cummax = equity_series.cummax()
    drawdown = (equity_series - cummax) / cummax

    # 标记回撤区间
    in_drawdown = drawdown < 0
    periods = []
    start_idx = None

    for i, (in_dd, dd_val) in enumerate(zip(in_drawdown, drawdown)):
        if in_dd and start_idx is None:
            start_idx = i  # 回撤开始
        elif not in_dd and start_idx is not None:
            # 回撤结束（回到新高）
            dd_period = drawdown.iloc[start_idx:i]
            if len(dd_period) > 0:
                periods.append({
                    '开始日期': dd_period.index[0],
                    '结束日期': dd_period.index[-1],
                    '持续天数': len(dd_period),
                    '最大回撤': f"{dd_period.min()*100:.2f}%",
                    '平均回撤': f"{dd_period.mean()*100:.2f}%"
                })
            start_idx = None
        elif dd_val == 0 and start_idx is not None:
            start_idx = None

    # 处理最后一个未完成的回撤
    if start_idx is not None:
        dd_period = drawdown.iloc[start_idx:]
        if len(dd_period) > 0 and dd_period.min() < 0:
            periods.append({
                '开始日期': dd_period.index[0],
                '结束日期': '进行中',
                '持续天数': len(dd_period),
                '最大回撤': f"{dd_period.min()*100:.2f}%",
                '平均回撤': f"{dd_period.mean()*100:.2f}%"
            })

    if not periods:
        return {
            'drawdown_periods': pd.DataFrame(),
            'avg_drawdown_depth': 0,
            'avg_recovery_days': 0,
            'max_drawdown_depth': 0,
            'total_drawdown_ratio': 0
        }

    dd_df = pd.DataFrame(periods)
    avg_depth = dd_df['最大回撤'].apply(lambda x: float(x.replace('%', ''))).mean()
    avg_days = dd_df['持续天数'].mean()
    max_depth = float(dd_df['最大回撤'].iloc[0].replace('%', ''))

    # 处于回撤的时间占比
    total_dd_ratio = in_drawdown.sum() / len(in_drawdown) if len(in_drawdown) > 0 else 0

    return {
        'drawdown_periods': dd_df,
        'avg_drawdown_depth': f"{avg_depth:.2f}%",
        'avg_recovery_days': round(avg_days, 1),
        'max_drawdown_depth': f"{max_depth}%",
        'total_drawdown_ratio': f"{total_dd_ratio*100:.1f}%"
    }


# ============================================================
# 蒙特卡洛模拟
# ============================================================

def monte_carlo_simulation(returns: pd.Series,
                           n_simulations: int = 1000,
                           horizon_days: int = 252,
                           initial_value: float = 100000) -> pd.DataFrame:
    """
    蒙特卡洛模拟：生成多条未来净值路径

    Args:
        returns:        历史日收益率
        n_simulations:  模拟次数
        horizon_days:   预测天数
        initial_value:  初始资产

    Returns:
        pd.DataFrame: n_simulations 条路径 (horizon_days × n_simulations)
    """
    mu = returns.mean()
    sigma = returns.std()

    np.random.seed(42)
    paths = np.zeros((horizon_days, n_simulations))

    for i in range(n_simulations):
        random_returns = np.random.normal(mu, sigma, horizon_days)
        paths[:, i] = initial_value * (1 + random_returns).cumprod()

    # 终值统计
    final_values = paths[-1, :]
    percentiles = [5, 25, 50, 75, 95]

    return pd.DataFrame(paths,
                        columns=[f'模拟{i+1}' for i in range(n_simulations)])
