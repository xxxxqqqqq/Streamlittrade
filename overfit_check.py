"""
模块：过拟合检测 (overfit_check.py)
功能：样本外测试、进度敏感性分析、白噪声检验、回测过拟合概率（PBO）
依赖：pandas, numpy, scipy
"""
import pandas as pd
import numpy as np
from scipy import stats
from typing import Dict, List, Tuple


# ============================================================
# 样本外 / 样本内分割测试
# ============================================================

def train_test_split_test(df: pd.DataFrame,
                          strategy_func,
                          run_backtest_func,
                          train_ratio: float = 0.7,
                          initial_cash: float = 100000,
                          **strategy_kwargs) -> Dict:
    """
    样本内/样本外分割测试：策略在训练集上开发，测试集上验证

    Returns:
        dict: IS 和 OOS 的核心指标对比
    """
    n = len(df)
    split_idx = int(n * train_ratio)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    # 样本内
    try:
        df_is = strategy_func(train_df, **strategy_kwargs)
        _, _, metrics_is = run_backtest_func(df_is, initial_cash=initial_cash)
    except Exception as e:
        metrics_is = {'error': str(e)}

    # 样本外
    try:
        df_oos = strategy_func(test_df, **strategy_kwargs)
        _, _, metrics_oos = run_backtest_func(df_oos, initial_cash=initial_cash)
    except Exception as e:
        metrics_oos = {'error': str(e)}

    return {
        '样本内(IS)': metrics_is,
        '样本外(OOS)': metrics_oos,
        'IS天数': len(train_df),
        'OOS天数': len(test_df)
    }


# ============================================================
# 进度敏感性分析（CSCV - Combinatorial Purged CV）
# ============================================================

def cscv_analysis(df: pd.DataFrame,
                  strategy_func,
                  run_backtest_func,
                  n_splits: int = 10,
                  initial_cash: float = 100000,
                  **strategy_kwargs) -> Dict:
    """
    CSCV 组合交叉验证：检测策略对时间窗口的敏感度

    流程：
    1. 将回测期拆成 N 段
    2. 每段独立回测
    3. 比较各段绩效的分布 — 如果方差很大，说明策略不稳定

    Returns:
        dict: 各段绩效 + 稳定性评分
    """
    n = len(df)
    split_size = n // n_splits

    segment_metrics = []
    for i in range(n_splits):
        start = i * split_size
        end = (i + 1) * split_size if i < n_splits - 1 else n
        segment = df.iloc[start:end]

        if len(segment) < 20:
            continue

        try:
            df_signal = strategy_func(segment, **strategy_kwargs)
            _, _, metrics = run_backtest_func(df_signal, initial_cash=initial_cash)
            segment_metrics.append({
                '分段': i + 1,
                '起始日': str(segment.index[0])[:10],
                '天数': len(segment),
                '总收益%': round(metrics.get('total_return', 0), 2),
                '夏普比率': round(metrics.get('sharpe_ratio', 0), 3),
                '最大回撤%': round(metrics.get('max_drawdown', 0), 2),
                '胜率%': round(metrics.get('win_rate', 0), 2)
            })
        except Exception:
            continue

    if not segment_metrics:
        return {'segments': pd.DataFrame(), 'stability_score': 0,
                'warning': '数据不足，无法进行分析'}

    seg_df = pd.DataFrame(segment_metrics)
    sharpe_values = seg_df['夏普比率'].values

    # 稳定性评分：夏普均值 / 夏普标准差，越高越稳定
    stability = np.mean(sharpe_values) / np.std(sharpe_values) if np.std(sharpe_values) > 0 else 999

    # 负夏普占比
    neg_ratio = (sharpe_values < 0).mean()

    return {
        'segments': seg_df,
        'stability_score': round(stability, 2),
        'neg_sharpe_ratio': f"{neg_ratio*100:.0f}%",
        'warning': '⚠️ 策略极不稳定，建议回炉' if stability < 0.5 or neg_ratio > 0.5
                   else '⚠️ 策略稳定性一般' if stability < 1.5
                   else '✅ 策略表现稳定'
    }


# ============================================================
# 回测过拟合概率 (PBO)
# ============================================================

def compute_pbo(param_results: pd.DataFrame,
                metric_col: str = 'sharpe_ratio',
                n_resamples: int = 1000) -> Dict:
    """
    回测过拟合概率 (Probability of Backtest Overfitting) — CSCV 方法

    原理（Bailey et al.）：
    1. 将参数扫描结果随机分成 IS/OOS 两组
    2. 在 IS 中找最优参数，在 OOS 中看其排名
    3. 如果最优 IS 参数在 OOS 中排名靠后（低于中位数），说明过拟合
    4. 重复 N 次，PBO = 排名低于中位数的比例

    Args:
        param_results: 网格搜索结果（来自 optimizer.grid_search）
        metric_col:    绩效指标列名
        n_resamples:   重采样次数

    Returns:
        dict: PBO 分析结果
    """
    if param_results.empty or metric_col not in param_results.columns:
        return {'PBO': None, 'warning': '数据不足'}

    values = param_results[metric_col].dropna().values
    if len(values) < 10:
        return {'PBO': None, 'warning': '参数组合太少，至少需要10组'}

    n = len(values)
    half = n // 2
    best_rank = np.argmax(values)
    overfit_count = 0
    np.random.seed(42)

    for _ in range(n_resamples):
        # 随机分成 IS 和 OOS 各一半
        shuffled = np.random.permutation(n)
        is_idx = shuffled[:half]
        oos_idx = shuffled[half:]

        is_values = values[is_idx]
        oos_values = values[oos_idx]

        # IS 中最优参数的索引（在原始 values 中的位置）
        best_is_local_idx = np.argmax(is_values)
        best_is_global_idx = is_idx[best_is_local_idx]

        # 该参数在 OOS 中的表现
        if best_is_global_idx in oos_idx:
            # 最优 IS 参数碰巧也在 OOS 中 → 它在 OOS 中的值
            oos_value_for_best = values[best_is_global_idx]
        else:
            # 最优 IS 参数不在 OOS 中 → 用它在原始值中的表现
            oos_value_for_best = values[best_is_global_idx]

        # OOS 中位数
        oos_median = np.median(oos_values)

        # 如果最优 IS 参数在 OOS 的表现差于中位数 → 过拟合
        if oos_value_for_best < oos_median:
            overfit_count += 1

    pbo = overfit_count / n_resamples

    # 解释
    if pbo < 0.1:
        level = '✅ 过拟合风险极低'
    elif pbo < 0.3:
        level = '✅ 过拟合风险较低'
    elif pbo < 0.5:
        level = '⚠️ 存在过拟合风险'
    else:
        level = '❌ 过拟合风险较高，建议减少参数自由度'

    return {
        'PBO': round(pbo, 4),
        'PBO_解释': f'有 {pbo*100:.1f}% 的概率最优IS参数在OOS表现差于OOS中位数',
        '风险等级': level,
        '参数组合数': n,
        '最优指标': round(values[best_rank], 4),
        '方法': 'CSCV (Combinatorial Purged Cross Validation)'
    }


# ============================================================
# 白噪声检验（Ljung-Box）
# ============================================================

def white_noise_test(returns: pd.Series, lags: List[int] = None) -> pd.DataFrame:
    """
    检验收益率序列是否为白噪声（无预测能力）

    如果 p 值 > 0.05，则序列接近白噪声，技术分析可能无效

    Returns:
        pd.DataFrame: 各滞后阶数的检验结果
    """
    if lags is None:
        lags = [1, 5, 10, 20]

    results = []
    for lag in lags:
        if len(returns) <= lag + 5:
            continue

        try:
            # scipy >= 1.12: acorr_ljungbox
            lb_result = stats.acorr_ljungbox(returns.dropna(), lags=[lag])
            # Returns DataFrame with 'lb_stat' and 'lb_pvalue' columns
            stat_val = float(lb_result['lb_stat'].iloc[0])
            p_val = float(lb_result['lb_pvalue'].iloc[0])
        except AttributeError:
            # scipy < 1.12: diag_ljungbox (deprecated)
            try:
                lb_stat, lb_pvalue = stats.diag_ljungbox(returns.dropna(), lags=[lag],
                                                           model_df=0)
                stat_val = float(lb_stat.iloc[0]) if hasattr(lb_stat, 'iloc') else float(lb_stat)
                p_val = float(lb_pvalue.iloc[0]) if hasattr(lb_pvalue, 'iloc') else float(lb_pvalue)
            except AttributeError:
                # Fallback: old statsmodels or custom implementation
                results.append({
                    '滞后阶数': lag,
                    'LB统计量': 'N/A',
                    'p值': 'N/A',
                    '结论': '⚠️ 无法计算，scipy版本不兼容'
                })
                continue

        results.append({
            '滞后阶数': lag,
            'LB统计量': round(stat_val, 3),
            'p值': round(p_val, 4),
            '结论': '✅ 存在自相关，可预测' if p_val < 0.05 else '❌ 接近白噪声，难以预测'
        })

    return pd.DataFrame(results)
