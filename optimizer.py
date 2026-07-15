"""
模块：参数优化 (optimizer.py)
功能：网格搜索参数优化、前向推进分析(WFA)、避免过拟合的交叉验证
      + 自定义策略参数解析（@PARAMS注释）
依赖：pandas, numpy, itertools, re
"""
import pandas as pd
import numpy as np
import itertools
import re
from typing import Callable, Dict, List, Tuple


# ============================================================
# 自定义策略参数解析
# ============================================================

def parse_strategy_params(code: str) -> Dict[str, list]:
    """
    从策略代码的 # @PARAMS: 注释中提取参数网格

    格式：`# @PARAMS: param1=min,max,step; param2=min,max,step`
    示例：`# @PARAMS: ma_short=3,15,2; vol_ratio=1.0,3.0,0.5`

    Args:
        code: 策略代码字符串

    Returns:
        dict: 参数网格，如 {'ma_short': [3,5,7,9,11,13,15], 'vol_ratio': [1.0,1.5,2.0,2.5,3.0]}
              没有 @PARAMS 时返回空 dict
    """
    match = re.search(r'#\s*@PARAMS:\s*(.+)', code)
    if not match:
        return {}

    param_grid = {}
    param_str = match.group(1).strip()

    for part in param_str.split(';'):
        part = part.strip()
        if not part:
            continue
        try:
            name_range = part.split('=')
            if len(name_range) != 2:
                continue
            name = name_range[0].strip()
            range_parts = name_range[1].split(',')
            if len(range_parts) != 3:
                continue
            min_val = float(range_parts[0].strip())
            max_val = float(range_parts[1].strip())
            step = float(range_parts[2].strip())

            # 生成参数值列表
            values = []
            val = min_val
            while val <= max_val + step * 0.5:
                # 保持整数为int，浮点为float
                if step == int(step) and min_val == int(min_val):
                    values.append(int(round(val)))
                else:
                    values.append(round(val, 2))
                val += step

            if values:
                param_grid[name] = values
        except (ValueError, IndexError):
            continue

    return param_grid


def make_strategy_wrapper(base_func: Callable, code: str) -> Callable:
    """
    为策略函数创建一个 kwargs 透传包装器

    解决新旧策略兼容问题：
    - 旧策略：generate_signal(df)
    - 新策略：generate_signal(df, **kwargs)

    Returns:
        Callable: 接收 (df, **kwargs) 的策略函数
    """
    import inspect
    sig = inspect.signature(base_func)
    params = list(sig.parameters.keys())

    # 如果函数已经接受 kwargs 或超过1个参数
    if 'kwargs' in params or len(params) > 1:
        return base_func

    # 旧式单参数函数，包装一下
    def wrapped(df, **kwargs):
        return base_func(df)

    return wrapped


# ============================================================
# 网格搜索优化
# ============================================================

def grid_search(df: pd.DataFrame,
                strategy_func: Callable,
                param_grid: Dict[str, list],
                run_backtest_func: Callable,
                metric: str = 'sharpe_ratio',
                initial_cash: float = 100000) -> pd.DataFrame:
    """
    对策略参数进行网格搜索，找到最优参数组合

    Args:
        df:                 行情数据
        strategy_func:      策略信号生成函数
        param_grid:         参数网格，如 {'ma_short': [5,10], 'vol_ratio': [1.2,1.5]}
        run_backtest_func:  回测函数（来自 backtest.py 的 run_backtest）
        metric:             优化目标指标，默认 'sharpe_ratio'
        initial_cash:       初始资金

    Returns:
        pd.DataFrame: 所有参数组合的回测结果，按指标降序排列
    """
    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())

    results = []
    total_combos = np.prod([len(v) for v in param_values])

    for idx, combo in enumerate(itertools.product(*param_values)):
        params = dict(zip(param_names, combo))

        # 生成信号
        try:
            df_signal = strategy_func(df, **params)
        except Exception:
            continue

        # 运行回测
        try:
            trades, equity, metrics = run_backtest_func(df_signal, initial_cash=initial_cash)
            if 'error' in metrics:
                continue
        except Exception:
            continue

        # 记录结果
        record = {**params,
                  'total_return': metrics.get('total_return', 0),
                  'sharpe_ratio': metrics.get('sharpe_ratio', 0),
                  'max_drawdown': metrics.get('max_drawdown', 0),
                  'win_rate': metrics.get('win_rate', 0),
                  'calmar_ratio': metrics.get('calmar_ratio', 0),
                  'profit_factor': metrics.get('profit_factor', 0),
                  'total_trades': metrics.get('total_trades', 0)}
        results.append(record)

    if not results:
        return pd.DataFrame()

    result_df = pd.DataFrame(results)
    # 按优化指标排序
    if metric in result_df.columns:
        result_df = result_df.sort_values(metric, ascending=False)

    return result_df.reset_index(drop=True)


# ============================================================
# 前向推进分析 (Walk-Forward Analysis)
# ============================================================

def walk_forward_analysis(df: pd.DataFrame,
                          strategy_func: Callable,
                          run_backtest_func: Callable,
                          param_grid: Dict[str, list],
                          train_months: int = 12,
                          test_months: int = 3,
                          metric: str = 'sharpe_ratio',
                          initial_cash: float = 100000) -> Dict:
    """
    前向推进分析：滚动窗口训练+测试，评估策略鲁棒性

    流程：
    - 用过去 train_months 个月数据做参数优化（训练）
    - 用接下来 test_months 个月数据做样本外验证（测试）
    - 窗口向前滑动 test_months，重复

    Args:
        df:              行情数据
        strategy_func:   策略函数
        run_backtest_func: 回测函数
        param_grid:      参数网格
        train_months:    训练窗口月数
        test_months:     测试窗口月数
        metric:          优化目标指标
        initial_cash:    初始资金

    Returns:
        dict: {
            'wfa_results':  各窗口结果 DataFrame,
            'oos_sharpe':   样本外平均夏普,
            'is_sharpe':    样本内平均夏普,
            'robustness':   鲁棒性评分 (OOS/IS 比值)
        }
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame 必须具有 DatetimeIndex")

    wfa_results = []
    is_sharpes = []
    oos_sharpes = []

    # 按月度滑动窗口
    current = df.index[0]
    end_date = df.index[-1]

    while current + pd.DateOffset(months=train_months + test_months) <= end_date:
        train_start = current
        train_end = current + pd.DateOffset(months=train_months)
        test_start = train_end
        test_end = train_end + pd.DateOffset(months=test_months)

        train_df = df.loc[train_start:train_end]
        test_df = df.loc[test_start:test_end]

        if len(train_df) < 50 or len(test_df) < 10:
            current += pd.DateOffset(months=test_months)
            continue

        # 样本内优化
        opt_result = grid_search(train_df, strategy_func, param_grid,
                                 run_backtest_func, metric, initial_cash)
        if opt_result.empty:
            current += pd.DateOffset(months=test_months)
            continue

        best_params = opt_result.iloc[0].to_dict()
        is_sharpe = best_params.get(metric, 0)

        # 样本外测试
        try:
            param_keys = list(param_grid.keys())
            best_strategy_params = {k: best_params[k] for k in param_keys if k in best_params}
            df_signal = strategy_func(test_df, **best_strategy_params)
            _, _, oos_metrics = run_backtest_func(df_signal, initial_cash=initial_cash)
            oos_sharpe = oos_metrics.get(metric, 0)
        except Exception:
            oos_sharpe = 0

        wfa_results.append({
            '训练起始': train_start.strftime('%Y-%m'),
            '训练结束': train_end.strftime('%Y-%m'),
            '测试结束': test_end.strftime('%Y-%m'),
            '样本内夏普': round(is_sharpe, 3),
            '样本外夏普': round(oos_sharpe, 3),
            '最佳参数': str({k: best_params.get(k) for k in param_grid.keys()})
        })
        is_sharpes.append(is_sharpe)
        oos_sharpes.append(oos_sharpe)

        # 窗口滑动
        current = test_start + pd.DateOffset(months=test_months)

    if not wfa_results:
        return {'wfa_results': pd.DataFrame(), 'oos_sharpe': 0, 'is_sharpe': 0, 'robustness': 0}

    avg_is = np.mean(is_sharpes)
    avg_oos = np.mean(oos_sharpes)
    robustness = min(avg_oos / avg_is, 1.0) if avg_is > 0 else 0

    return {
        'wfa_results': pd.DataFrame(wfa_results),
        'oos_sharpe': round(avg_oos, 3),
        'is_sharpe': round(avg_is, 3),
        'robustness': round(robustness, 3)
    }


# ============================================================
# 夏普衰变分析（参数敏感度）
# ============================================================

def parameter_sensitivity(df: pd.DataFrame,
                          strategy_func: Callable,
                          run_backtest_func: Callable,
                          base_params: Dict[str, float],
                          param_name: str,
                          test_range: Tuple[float, float],
                          n_points: int = 10,
                          metric: str = 'sharpe_ratio',
                          initial_cash: float = 100000) -> pd.DataFrame:
    """
    单参数敏感度分析：在最优参数附近微调，观察指标变化

    Args:
        base_params:         基准参数
        param_name:          要测试的参数名
        test_range:          测试范围 (min, max)
        n_points:            采样点数

    Returns:
        pd.DataFrame: 参数值 vs 指标值
    """
    results = []
    test_values = np.linspace(test_range[0], test_range[1], n_points)

    for val in test_values:
        params = base_params.copy()
        params[param_name] = val

        try:
            df_signal = strategy_func(df, **params)
            _, _, metrics = run_backtest_func(df_signal, initial_cash=initial_cash)
            results.append({
                '参数值': val,
                '夏普比率': round(metrics.get('sharpe_ratio', 0), 3),
                '最大回撤': f"{metrics.get('max_drawdown', 0):.2f}%",
                '总收益': f"{metrics.get('total_return', 0):.2f}%"
            })
        except Exception:
            results.append({'参数值': val, '夏普比率': None, '最大回撤': None, '总收益': None})

    return pd.DataFrame(results)
