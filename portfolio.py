"""
模块：组合管理 (portfolio.py)
功能：多股票批量回测、仓位分配（等权/风险平价/凯利公式/最大夏普）
依赖：pandas, numpy, scipy.optimize
"""
import pandas as pd
import numpy as np
from scipy.optimize import minimize
from typing import Dict, List, Optional


# ============================================================
# 多股票批量回测
# ============================================================

def batch_backtest(symbols: List[str],
                   fetch_data_func,
                   strategy_func,
                   run_backtest_func,
                   start_date: str,
                   end_date: str,
                   initial_cash: float = 100000,
                   **strategy_kwargs) -> pd.DataFrame:
    """
    对多只股票逐一回测，汇总对比

    Args:
        symbols:            股票代码列表
        fetch_data_func:    数据获取函数
        strategy_func:      策略函数
        run_backtest_func:  回测函数
        start_date/end_date: 日期范围（YYYYMMDD）
        initial_cash:       每只股票的初始资金
        **strategy_kwargs:  策略参数

    Returns:
        pd.DataFrame: 多只股票的绩效对比表
    """
    results = []

    for symbol in symbols:
        try:
            df = fetch_data_func(symbol, start_date, end_date)
            if df is None or df.empty:
                results.append({'股票': symbol, '状态': '数据获取失败'})
                continue

            df_signal = strategy_func(df, **strategy_kwargs)

            trades, equity, metrics = run_backtest_func(df_signal, initial_cash=initial_cash)
            if 'error' in metrics:
                results.append({'股票': symbol, '状态': f"回测失败: {metrics['error']}"})
                continue

            results.append({
                '股票': symbol,
                '总收益率%': round(metrics.get('total_return', 0), 2),
                '年化收益%': round(metrics.get('annual_return', 0), 2),
                '最大回撤%': round(metrics.get('max_drawdown', 0), 2),
                '夏普比率': round(metrics.get('sharpe_ratio', 0), 3),
                '胜率%': round(metrics.get('win_rate', 0), 2),
                '交易次数': metrics.get('total_trades', 0),
                'Calmar': round(metrics.get('calmar_ratio', 0), 3),
                '盈亏因子': round(metrics.get('profit_factor', 0), 3),
                '状态': '成功'
            })
        except Exception as e:
            results.append({'股票': symbol, '状态': str(e)[:50]})

    return pd.DataFrame(results)


# ============================================================
# 仓位分配算法
# ============================================================

def equal_weight(n_assets: int) -> np.ndarray:
    """等权分配"""
    return np.ones(n_assets) / n_assets


def risk_parity(cov_matrix: np.ndarray, max_iter: int = 1000) -> np.ndarray:
    """
    风险平价：每个资产对组合的风险贡献相等

    Args:
        cov_matrix: 协方差矩阵 (n×n)

    Returns:
        np.ndarray: 权重向量
    """
    n = cov_matrix.shape[0]

    def risk_budget_objective(weights):
        portfolio_var = weights @ cov_matrix @ weights
        marginal_contrib = cov_matrix @ weights
        risk_contrib = weights * marginal_contrib / portfolio_var
        # 目标：各风险贡献均等
        target = np.ones(n) / n
        return np.sum((risk_contrib - target) ** 2)

    constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
    bounds = [(0.01, 1.0) for _ in range(n)]
    init_weights = np.ones(n) / n

    result = minimize(risk_budget_objective, init_weights,
                      method='SLSQP', bounds=bounds, constraints=constraints,
                      options={'maxiter': max_iter})

    return result.x / result.x.sum() if result.success else equal_weight(n)


def max_sharpe(returns: np.ndarray, risk_free: float = 0.02, max_iter: int = 1000) -> np.ndarray:
    """
    最大夏普比率组合

    Args:
        returns:  收益矩阵 (T×n)
        risk_free: 无风险利率

    Returns:
        np.ndarray: 权重向量
    """
    n = returns.shape[1]
    mean_ret = np.mean(returns, axis=0)
    cov = np.cov(returns.T)

    def neg_sharpe(weights):
        port_ret = weights @ mean_ret
        port_vol = np.sqrt(weights @ cov @ weights)
        if port_vol == 0:
            return 1e6
        return -(port_ret - risk_free / 252) / port_vol

    constraints = ({'type': 'eq', 'fun': lambda w: np.sum(w) - 1})
    bounds = [(0.0, 1.0) for _ in range(n)]
    init = np.ones(n) / n

    result = minimize(neg_sharpe, init, method='SLSQP',
                      bounds=bounds, constraints=constraints,
                      options={'maxiter': max_iter})
    return result.x / result.x.sum() if result.success else equal_weight(n)


def kelly_allocation(win_rates: np.ndarray,
                     profit_loss_ratios: np.ndarray) -> np.ndarray:
    """
    凯利公式仓位分配（半凯利，更保守）

    f* = win_rate - (1 - win_rate) / (profit / loss)
    使用半凯利 (f*/2) 降低风险

    Args:
        win_rates:           各资产胜率数组
        profit_loss_ratios:  各资产盈亏比数组

    Returns:
        np.ndarray: 建议仓位权重
    """
    half_kelly = []
    for wr, plr in zip(win_rates, profit_loss_ratios):
        if plr <= 0:
            half_kelly.append(0)
        else:
            kelly = wr - (1 - wr) / plr
            half_kelly.append(max(0, min(kelly / 2, 0.25)))  # 半凯利，上限25%

    total = np.sum(half_kelly)
    if total == 0:
        return np.zeros_like(half_kelly)
    return np.array(half_kelly) / total


# ============================================================
# 组合绩效计算
# ============================================================

def compute_portfolio_metrics(weights: np.ndarray,
                              returns: np.ndarray,
                              risk_free: float = 0.02) -> Dict:
    """
    计算组合层面的绩效指标

    Args:
        weights:   权重数组
        returns:   各资产日收益率矩阵 (T×n)
        risk_free: 无风险利率

    Returns:
        dict: 组合绩效指标
    """
    port_returns = returns @ weights
    n_days = len(port_returns)

    total_return = (1 + port_returns).prod() - 1
    annual_return = (1 + total_return) ** (252 / max(n_days, 1)) - 1
    volatility = port_returns.std() * np.sqrt(252)

    sharpe = (annual_return - risk_free) / volatility if volatility > 0 else 0

    # 最大回撤
    cum = (1 + port_returns).cumprod()
    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max
    max_dd = drawdown.min()

    calmar = annual_return / abs(max_dd) if max_dd != 0 else 0
    win_rate = (port_returns > 0).mean()

    # Sortino
    neg_returns = port_returns[port_returns < 0]
    downside_std = neg_returns.std() * np.sqrt(252) if len(neg_returns) > 0 else 0
    sortino = (annual_return - risk_free) / downside_std if downside_std > 0 else 0

    return {
        'total_return': round(total_return * 100, 2),
        'annual_return': round(annual_return * 100, 2),
        'volatility': f"{volatility*100:.2f}%",
        'sharpe_ratio': round(sharpe, 3),
        'sortino_ratio': round(sortino, 3),
        'max_drawdown': f"{max_dd*100:.2f}%",
        'calmar_ratio': round(calmar, 3),
        'win_rate': f"{win_rate*100:.1f}%"
    }
