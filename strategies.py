"""
模块：内置策略信号生成 (strategies.py)
功能：包含右侧趋势策略和 V 型反转策略的信号生成函数
      每个函数接收 OHLCV DataFrame，返回带 signal 列的增强 DataFrame
依赖：pandas, numpy
"""
import pandas as pd
import numpy as np


# ============================================================
# 策略一：增强版右侧趋势策略
# ============================================================

def generate_right_signal(df,
                          ma_short=5,
                          ma_mid=20,
                          ma_long=60,
                          vol_ratio=1.5,
                          rsi_period=14,
                          rsi_upper=70,
                          rsi_lower=50,
                          kdj_n=9,
                          kdj_m1=3,
                          kdj_m2=3):
    """
    增强版右侧趋势策略 —— 多条件共振买入信号

    核心逻辑：均线多头排列 + MACD 零上金叉 + 放量突破 + 站上 60 日生命线
             同时满足 RSI 强势 或 MACD 红柱放大（二选一）

    Args:
        df:          原始 OHLCV DataFrame（索引为日期）
        ma_short:    短期均线周期，默认 5
        ma_mid:      中期均线周期，默认 20
        ma_long:     长期均线周期（生命线），默认 60
        vol_ratio:   放量倍数阈值，默认 1.5
        rsi_period:  RSI 计算周期，默认 14
        rsi_upper:   RSI 强势上限，默认 70
        rsi_lower:   RSI 强势下限，默认 50
        kdj_n/kdj_m1/kdj_m2: KDJ 指标参数

    Returns:
        pd.DataFrame: 包含 signal(布尔), signal_type('right'), score 的增强数据
    """
    # ---- 数据预处理 ----
    data = df.copy()
    data = data[~data.index.duplicated(keep='first')].sort_index()

    # ---- 均线系统 ----
    data['MA5'] = data['close'].rolling(ma_short).mean()
    data['MA20'] = data['close'].rolling(ma_mid).mean()
    data['MA60'] = data['close'].rolling(ma_long).mean()

    # ---- MACD 指标 ----
    exp1 = data['close'].ewm(span=12, adjust=False).mean()   # 快线 EMA(12)
    exp2 = data['close'].ewm(span=26, adjust=False).mean()   # 慢线 EMA(26)
    data['DIF'] = exp1 - exp2                                 # DIF 线
    data['DEA'] = data['DIF'].ewm(span=9, adjust=False).mean()  # DEA 线（信号线）
    data['MACD_bar'] = (data['DIF'] - data['DEA']) * 2       # MACD 柱
    data['MACD_bar_shift'] = data['MACD_bar'].shift(1)        # 前一日 MACD 柱

    # ---- 成交量 ----
    data['VOL_MA20'] = data['volume'].rolling(20).mean()

    # ---- RSI（相对强弱指标）----
    delta = data['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))

    # ---- KDJ 指标 ----
    low_min = data['low'].rolling(kdj_n).min()
    high_max = data['high'].rolling(kdj_n).max()
    data['RSV'] = (data['close'] - low_min) / (high_max - low_min) * 100
    data['K'] = data['RSV'].ewm(span=kdj_m1, adjust=False).mean()
    data['D'] = data['K'].ewm(span=kdj_m2, adjust=False).mean()
    data['J'] = 3 * data['K'] - 2 * data['D']

    # ---- 七维条件判断 ----
    cond1 = (data['MA5'] > data['MA20']) & (data['MA20'] > data['MA60'])   # 均线多头排列
    cond2 = (data['DIF'] > data['DEA']) & (data['DIF'] > 0)                # MACD 零上金叉
    cond3 = data['volume'] > data['VOL_MA20'] * vol_ratio                  # 放量突破
    cond4 = data['close'] > data['MA60']                                   # 站上 60 日生命线
    cond5 = (data['K'] > data['D']) & (data['J'] > 20)                     # KDJ 金叉
    cond6 = (data['RSI'] > rsi_lower) & (data['RSI'] < rsi_upper)          # RSI 强势区间
    cond7 = data['MACD_bar'] > data['MACD_bar_shift']                      # MACD 红柱放大

    # ---- 综合评分与信号 ----
    # 核心条件（必须全部满足）
    core_signal = cond1 & cond2 & cond3 & cond4
    # 综合评分（7 个条件满足多少个）
    data['score'] = (cond1.astype(int) + cond2.astype(int) + cond3.astype(int) +
                     cond4.astype(int) + cond5.astype(int) + cond6.astype(int) + cond7.astype(int))
    # 最终信号：核心条件 + (RSI 强势 或 MACD 放大)
    data['signal'] = core_signal & (cond6 | cond7)
    data['signal_type'] = 'right'

    return data


# ============================================================
# 策略二：V 型反转策略
# ============================================================

def generate_v_shape_signal(df, lookback=10, drop_threshold=0.15,
                            rebound_threshold=0.01, vol_ratio=1.3, confirm_days=2):
    """
    V 型反转策略 —— 捕捉急跌后的放量反弹信号

    核心逻辑：在回看窗口内识别急跌（跌幅超阈值）→ 企稳（不再创新低）
             → 放量反弹（涨幅 + 成交量同时满足条件）

    Args:
        df:                原始 OHLCV DataFrame
        lookback:          回看天数，默认 10
        drop_threshold:    最小跌幅阈值（相对于窗口最高价），默认 0.15（15%）
        rebound_threshold: 最小反弹幅度，默认 0.01（1%）
        vol_ratio:         放量倍数（相对于 20 日均量），默认 1.3
        confirm_days:      企稳确认天数（新低后不再破位），默认 2

    Returns:
        pd.DataFrame: 包含 signal, signal_type('v_shape') 及触发诊断列的 DataFrame
    """
    # ---- 数据预处理 ----
    data = df.copy()
    data = data[~data.index.duplicated(keep='first')].sort_index()
    data['signal'] = False
    data['signal_type'] = 'v_shape'
    data['VOL_MA20'] = data['volume'].rolling(20).mean()

    # 存储触发参数，供回测引擎生成买入原因描述
    data['drop_used'] = np.nan
    data['rebound_used'] = np.nan
    data['vol_ratio_used'] = np.nan

    # ---- 逐日扫描 V 型反转信号 ----
    for i in range(lookback + confirm_days + 5, len(data)):
        # 取回看窗口 [i-lookback, i]
        window = data.iloc[i - lookback: i + 1]
        if len(window) < lookback + 1:
            continue

        # 条件1：窗口内最大跌幅 ≥ 阈值
        recent_high = window['high'].max()
        recent_low = window['low'].min()
        max_drawdown = (recent_high - recent_low) / recent_high
        if max_drawdown < drop_threshold:
            continue

        # 条件2：最低点后企稳（confirm_days 天内不创新低）
        low_idx = window['low'].idxmin()
        low_price = window.loc[low_idx, 'low']
        low_pos = window.index.get_loc(low_idx)

        after_low = window.iloc[low_pos + 1:]
        if len(after_low) < confirm_days:
            continue
        if after_low['low'].iloc[:confirm_days].min() <= low_price:
            continue

        # 条件3：当前收盘价从最低点反弹 ≥ 阈值
        current_close = data.iloc[i]['close']
        rebound = (current_close - low_price) / low_price
        if rebound < rebound_threshold:
            continue

        # 条件4：当日成交量放量 ≥ 阈值
        vol_ratio_curr = data.iloc[i]['volume'] / data.iloc[i]['VOL_MA20']
        if vol_ratio_curr < vol_ratio:
            continue

        # ---- 全部条件满足 → 触发买入信号 ----
        data.iloc[i, data.columns.get_loc('signal')] = True
        data.iloc[i, data.columns.get_loc('drop_used')] = max_drawdown
        data.iloc[i, data.columns.get_loc('rebound_used')] = rebound
        data.iloc[i, data.columns.get_loc('vol_ratio_used')] = vol_ratio_curr

    return data
