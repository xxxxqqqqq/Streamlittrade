"""
模块：多因子分析 (factor_analysis.py)
功能：因子计算、IC 分析、分层回测、因子相关性矩阵
依赖：pandas, numpy, scipy
"""
import pandas as pd
import numpy as np
from scipy import stats


# ============================================================
# 因子中英文对照表
# ============================================================

FACTOR_LABELS = {
    'ret_1d': '1日收益率/动量',
    'ret_5d': '5日收益率/动量',
    'ret_20d': '20日收益率/动量',
    'bias_5': '5日均线偏离',
    'bias_20': '20日均线偏离',
    'volatility_5d': '5日波动率',
    'volatility_20d': '20日波动率',
    'vol_ratio_5': '5日量比',
    'vol_ratio_20': '20日量比',
    'vol_change_5d': '5日成交量变化',
    'amplitude': '日内振幅',
    'amplitude_ma5': '5日平均振幅',
    'turnover_proxy': '相对60日量比/流动性',
    'rsi_14': 'RSI(14)',
    'ma_5': '5日均线',
    'ma_20': '20日均线',
    'ma_60': '60日均线',
}


def translate_factor(name):
    """返回 '英文名 / 中文名' 格式"""
    return f"{name} / {FACTOR_LABELS.get(name, '')}" if name in FACTOR_LABELS else name


# ============================================================
# 因子库：计算常用技术因子
# ============================================================

def compute_all_factors(df):
    """
    对 OHLCV DataFrame 批量计算 15+ 个常用因子

    Returns:
        pd.DataFrame: 原始数据 + 各因子列
    """
    data = df.copy()
    close = data['close']
    volume = data['volume']
    high = data['high']
    low = data['low']

    # ---- 动量类因子 ----
    data['ret_1d'] = close.pct_change(1)                              # 1日收益率
    data['ret_5d'] = close.pct_change(5)                              # 5日动量
    data['ret_20d'] = close.pct_change(20)                            # 20日动量

    # ---- 均线偏离 ----
    data['ma_5'] = close.rolling(5).mean()
    data['ma_20'] = close.rolling(20).mean()
    data['ma_60'] = close.rolling(60).mean()
    data['bias_5'] = (close - data['ma_5']) / data['ma_5']            # 5日均线偏离
    data['bias_20'] = (close - data['ma_20']) / data['ma_20']         # 20日均线偏离

    # ---- 波动率因子 ----
    data['volatility_5d'] = data['ret_1d'].rolling(5).std()           # 5日波动率
    data['volatility_20d'] = data['ret_1d'].rolling(20).std()         # 20日波动率

    # ---- 成交量因子 ----
    data['vol_ma_5'] = volume.rolling(5).mean()
    data['vol_ma_20'] = volume.rolling(20).mean()
    data['vol_ratio_5'] = volume / data['vol_ma_5']                   # 5日量比
    data['vol_ratio_20'] = volume / data['vol_ma_20']                 # 20日量比
    data['vol_change_5d'] = volume.pct_change(5)                      # 5日成交量变化

    # ---- 振幅因子 ----
    data['amplitude'] = (high - low) / close.shift(1)                 # 日内振幅
    data['amplitude_ma5'] = data['amplitude'].rolling(5).mean()       # 5日平均振幅

    # ---- 换手率替代（用成交量变化模拟流动性） ----
    data['turnover_proxy'] = volume / volume.rolling(60).mean()       # 相对60日均量的倍数

    # ---- RSI ----
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    data['rsi_14'] = 100 - (100 / (1 + rs))

    # ---- 未来收益（用于 IC 分析，实盘中不可用） ----
    data['forward_ret_5d'] = close.shift(-5) / close - 1              # 5日后收益率
    data['forward_ret_20d'] = close.shift(-20) / close - 1            # 20日后收益率

    return data


# ============================================================
# IC 分析（信息系数）
# ============================================================

def compute_ic_analysis(df_with_factors, forward_period='forward_ret_5d'):
    """
    计算各因子与未来收益的 IC（Rank IC 和 Pearson IC）

    Args:
        df_with_factors: 含有因子列和未来收益列的 DataFrame
        forward_period:  未来收益列名，默认 'forward_ret_5d'

    Returns:
        dict: {
            'ic_summary':   各因子 IC 均值、IR、胜率 的 DataFrame,
            'ic_series':    各因子每日 IC 值时间序列 DataFrame
        }
    """
    # 筛选因子列（排除原始 OHLCV 和未来收益列）
    exclude = ['open', 'high', 'low', 'close', 'volume',
               'forward_ret_5d', 'forward_ret_20d',
               'ma_5', 'ma_20', 'ma_60']
    factor_cols = [c for c in df_with_factors.columns if c not in exclude]

    ic_records = []
    ic_series = {}

    for col in factor_cols:
        if col.startswith('forward_'):
            continue
        # 计算每期（每日）截面 Rank IC
        valid = df_with_factors[[col, forward_period]].dropna()
        if len(valid) < 30:
            continue

        # 滚动窗口计算 IC
        window = 20
        ic_list = []
        for i in range(window, len(valid)):
            x = valid[col].iloc[i - window:i]
            y = valid[forward_period].iloc[i - window:i]
            if x.std() == 0 or y.std() == 0:
                ic_list.append(np.nan)
            else:
                ic_list.append(stats.spearmanr(x, y)[0])  # Rank IC

        ic_series_df = pd.Series(ic_list, index=valid.index[window:])
        ic_series[col] = ic_series_df

        # 汇总统计
        ic_mean = np.nanmean(ic_list)
        ic_std = np.nanstd(ic_list)
        ir = ic_mean / ic_std if ic_std > 0 else 0  # IC_IR
        win_rate = np.nansum(np.array(ic_list) > 0) / max(np.sum(~np.isnan(ic_list)), 1)

        ic_records.append({
            '因子': translate_factor(col),
            'IC均值': round(ic_mean, 4),
            'IC标准差': round(ic_std, 4),
            'IC_IR': round(ir, 4),
            'IC胜率': f"{win_rate*100:.1f}%",
            '有效样本': len(ic_list)
        })

    ic_summary = pd.DataFrame(ic_records).sort_values('IC_IR', ascending=False)
    ic_series_df = pd.DataFrame(ic_series)
    # 翻译 IC 序列列名
    ic_series_df.columns = [translate_factor(c) for c in ic_series_df.columns]

    return {
        'ic_summary': ic_summary,
        'ic_series': ic_series_df
    }


# ============================================================
# 分层回测
# ============================================================

def layer_backtest(df_with_factors, factor_name, n_layers=5, forward_period='forward_ret_5d'):
    """
    按因子值分层，测试各层未来收益表现

    Args:
        df_with_factors: 含因子和未来收益的 DataFrame
        factor_name:     因子列名
        n_layers:        分层数量，默认 5
        forward_period:  未来收益列名

    Returns:
        pd.DataFrame: 各层收益统计
    """
    valid = df_with_factors[[factor_name, forward_period]].dropna()
    if len(valid) < 50:
        return None

    # 按因子值分位数分层
    valid['layer'] = pd.qcut(valid[factor_name].rank(method='first'), n_layers,
                             labels=[f'Q{i+1}' for i in range(n_layers)])

    layer_stats = []
    for layer_name in [f'Q{i+1}' for i in range(n_layers)]:
        layer_data = valid[valid['layer'] == layer_name][forward_period]
        if len(layer_data) == 0:
            continue
        layer_stats.append({
            '分层': layer_name,
            '平均收益': f"{layer_data.mean()*100:.3f}%",
            '收益标准差': f"{layer_data.std()*100:.3f}%",
            '胜率': f"{(layer_data > 0).mean()*100:.1f}%",
            '样本数': len(layer_data),
            '累计收益': f"{(1 + layer_data).prod() - 1:.3%}"
        })

    return pd.DataFrame(layer_stats)


# ============================================================
# 因子相关性矩阵
# ============================================================

def factor_correlation(df_with_factors):
    """
    计算因子间 Spearman 秩相关矩阵，识别冗余因子

    Returns:
        pd.DataFrame: 因子相关性矩阵
    """
    exclude = ['open', 'high', 'low', 'close', 'volume',
               'forward_ret_5d', 'forward_ret_20d',
               'ma_5', 'ma_20', 'ma_60', 'layer']
    factor_cols = [c for c in df_with_factors.columns
                   if c not in exclude and not c.startswith('forward_')]

    if len(factor_cols) < 2:
        return pd.DataFrame()

    corr = df_with_factors[factor_cols].corr(method='spearman')
    # 翻译行列名
    corr.columns = [translate_factor(c) for c in corr.columns]
    corr.index = [translate_factor(c) for c in corr.index]
    return corr
