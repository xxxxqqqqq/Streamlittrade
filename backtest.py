"""
模块：回测引擎与绩效评估 (backtest.py)
功能：事件驱动回测引擎 —— 模拟逐日交易、风险管理（止损/止盈/移动止损/ATR动态止损）、
      交易成本（佣金+印花税+滑点）、信号确认过滤，以及全面的绩效指标计算
依赖：pandas, numpy
"""
import pandas as pd
import numpy as np


# ============================================================
# 辅助函数：买入原因描述生成
# ============================================================

def get_entry_reason(row, signal_type):
    """
    根据信号类型和该行的技术指标数据，生成可读的买入原因描述
    用于回测结果中的交易明细展示

    Args:
        row:          触发信号所在行的 Series（含技术指标列）
        signal_type:  信号类型，'right' / 'v_shape' / 'custom'

    Returns:
        str: 买入原因描述，如 "均线多头 | MACD金叉 | 放量 | RSI强势"
    """
    if signal_type == 'right':
        # 右侧趋势策略：汇总满足的各条件
        reasons = []
        if row.get('MA5', 0) > row.get('MA20', 0) and row.get('MA20', 0) > row.get('MA60', 0):
            reasons.append('均线多头')
        if row.get('DIF', 0) > row.get('DEA', 0) and row.get('DIF', 0) > 0:
            reasons.append('MACD金叉')
        if row.get('volume', 0) > row.get('VOL_MA20', 1) * 1.5:
            reasons.append('放量')
        if row.get('close', 0) > row.get('MA60', 0):
            reasons.append('站上60日线')
        if row.get('K', 0) > row.get('D', 0) and row.get('J', 0) > 20:
            reasons.append('KDJ金叉')
        if 'RSI' in row and 50 < row['RSI'] < 70:
            reasons.append('RSI强势')
        if 'MACD_bar' in row and 'MACD_bar_shift' in row and row['MACD_bar'] > row['MACD_bar_shift']:
            reasons.append('MACD放大')
        return ' | '.join(reasons) if reasons else '右侧信号'

    elif signal_type == 'v_shape':
        # V 型反转策略：展示跌幅、反弹幅度、量比
        parts = []
        if not np.isnan(row.get('drop_used', np.nan)):
            parts.append(f"跌幅{row['drop_used'] * 100:.1f}%")
        if not np.isnan(row.get('rebound_used', np.nan)):
            parts.append(f"反弹{row['rebound_used'] * 100:.1f}%")
        if not np.isnan(row.get('vol_ratio_used', np.nan)):
            parts.append(f"量比{row['vol_ratio_used']:.2f}")
        return ' | '.join(parts) if parts else 'V型反转'

    elif signal_type == 'custom':
        return '自定义策略'

    else:
        return '未知信号'


# ============================================================
# 核心回测引擎
# ============================================================

def run_backtest(df, initial_cash=100000, commission=0.0003, slippage=0.001,
                 stop_loss=0.08, take_profit=0.20, trailing_stop=0.05,
                 use_atr_stop=False, atr_period=14, atr_multiple=2.0,
                 stamp_duty=0.0005, signal_confirm=1,
                 max_hold_days=20, position_pct=0.30):
    """
    事件驱动回测引擎（专业版）

    核心特性：
    - ATR 动态止损：基于真实波动幅度自适应调整止损位
    - 印花税模拟：A 股卖出单边征收（默认 0.05%）
    - 信号确认机制：要求信号持续 N 天才触发买入，过滤假突破
    - T+1 交易制度：买入后次日才能卖出
    - 多种止损策略：硬止损 / 移动止损 / ATR 动态止损 / 趋势止损 / 时间止损

    Args:
        df:              包含 signal 列和 signal_type 列的 DataFrame
        initial_cash:    初始资金，默认 100,000
        commission:       佣金费率，默认 0.03%（万三）
        slippage:         滑点比例，默认 0.1%
        stop_loss:        硬止损比例，默认 8%
        take_profit:      目标止盈比例，默认 20%
        trailing_stop:    移动止损回撤比例，默认 5%
        use_atr_stop:     是否启用 ATR 动态止损
        atr_period:       ATR 计算周期，默认 14
        atr_multiple:     ATR 止损倍数，默认 2.0
        stamp_duty:       印花税率（卖出单边），默认 0.05%
        signal_confirm:   信号确认天数，默认 1（不确认）
        max_hold_days:    最大持仓天数（V 型反转专用），默认 20
        position_pct:     单次建仓资金比例，默认 30%

    Returns:
        tuple: (trades_df, equity_series, metrics_dict)
    """
    # ---- 数据预处理 ----
    data = df.copy()
    data = data[data['signal'].notna()]  # 过滤无信号行
    if data.empty:
        return None, None, {'error': '无有效数据'}

    # 确保存在 MA20 列（用于趋势止损判断）
    if 'MA20' not in data.columns:
        data['MA20'] = data['close'].rolling(20).mean()

    # ---- ATR（Average True Range）计算 —— 用于动态止损 ----
    if use_atr_stop:
        # True Range = max(H-L, |H-C_prev|, |L-C_prev|)
        data['TR'] = np.maximum(
            data['high'] - data['low'],
            np.maximum(
                abs(data['high'] - data['close'].shift(1)),
                abs(data['low'] - data['close'].shift(1))
            )
        )
        data['ATR'] = data['TR'].rolling(atr_period).mean()

    # ---- 信号确认：连续 N 天出信号才算有效信号 ----
    if signal_confirm > 1:
        # 计算过去 N 天信号总和，等于 N 说明连续 N 天都有信号
        confirm_count = data['signal'].astype(int).rolling(signal_confirm).sum()
        data['signal_confirmed'] = (confirm_count >= signal_confirm) & data['signal']
    else:
        data['signal_confirmed'] = data['signal']

    # ---- 初始化账户状态 ----
    cash = initial_cash          # 现金余额
    position = 0                 # 持仓数量（股）
    entry_price = 0              # 买入均价
    highest_price = 0            # 持仓期间最高价（用于移动止损）
    hold_days = 0                # 持仓天数
    in_position = False          # 是否持仓
    trades = []                  # 交易记录列表
    daily_equity = []            # 每日权益序列

    # ---- 逐日模拟交易 ----
    for i in range(len(data)):
        current_date = data.index[i]
        current_price = data.iloc[i]['close']
        current_high = data.iloc[i]['high']
        signal_type = data.iloc[i].get('signal_type', 'unknown')
        sold_this_step = False   # 当日是否已卖出（防止同日买卖）

        # ================================================================
        # 持仓状态 → 判断是否需要卖出
        # ================================================================
        if in_position:
            hold_days += 1
            highest_price = max(highest_price, current_high)  # 更新持仓最高价
            should_sell = False
            sell_reason = ""

            if hold_days >= 2:  # A 股 T+1 规则：买入次日才能卖
                # 优先级1：ATR 动态止损（覆盖固定比例移动止损）
                if use_atr_stop and not np.isnan(data.iloc[i].get('ATR', np.nan)):
                    atr_stop_price = highest_price - atr_multiple * data.iloc[i]['ATR']
                    if current_price <= atr_stop_price:
                        should_sell = True
                        sell_reason = f"ATR动态止损 ({atr_multiple:.1f}xATR)"

                # 优先级2：硬止损（绝对亏损比例）
                elif current_price <= entry_price * (1 - stop_loss):
                    should_sell = True
                    sell_reason = f"硬止损 (-{stop_loss * 100:.0f}%)"

                # 优先级3：移动止损（从最高点回撤）
                elif current_price <= highest_price * (1 - trailing_stop):
                    should_sell = True
                    sell_reason = f"移动止损 (回撤{trailing_stop * 100:.0f}%)"

                # 优先级4：目标止盈
                elif current_price >= entry_price * (1 + take_profit):
                    should_sell = True
                    sell_reason = f"目标止盈 (+{take_profit * 100:.0f}%)"

                # 优先级5：趋势止损（右侧趋势策略专用）
                elif signal_type == 'right' and current_price < data.iloc[i]['MA20']:
                    should_sell = True
                    sell_reason = "趋势止损 (跌破MA20)"

                # 优先级6：时间止损（V 型反转策略专用）
                elif signal_type == 'v_shape' and hold_days >= max_hold_days:
                    should_sell = True
                    sell_reason = f"时间止损 (持有{hold_days}天)"

            # ---- 执行卖出 ----
            if should_sell:
                sell_price = current_price * (1 - slippage)                   # 扣除滑点
                fee = sell_price * position * (commission + stamp_duty)        # 佣金 + 印花税
                cash += sell_price * position - fee                           # 回笼资金
                profit = (sell_price - entry_price) / entry_price              # 计算盈亏比

                trades.append({
                    'date': current_date,
                    'action': 'SELL',
                    'price': round(sell_price, 3),
                    'profit_pct': round(profit * 100, 2),
                    'hold_days': hold_days,
                    'reason': sell_reason
                })

                # 重置持仓状态
                position = 0
                in_position = False
                entry_price = 0
                sold_this_step = True

        # ================================================================
        # 空仓状态 → 判断是否需要买入
        # ================================================================
        if not in_position and not sold_this_step and data.iloc[i]['signal_confirmed']:
            buy_price = current_price * (1 + slippage)                       # 含滑点的买入价
            portfolio_value = cash + position * buy_price                     # 当前组合总价值
            target_value = portfolio_value * position_pct                     # 目标买入金额
            size = int(target_value / buy_price)                              # 可买股数（整手）

            # 检查资金是否足够
            if size > 0 and cash > buy_price * size:
                fee = buy_price * size * commission                           # 买入佣金（无印花税）
                if cash >= buy_price * size + fee:
                    cash -= buy_price * size + fee
                    position = size
                    entry_price = buy_price
                    highest_price = buy_price
                    hold_days = 0
                    in_position = True

                    # 生成买入原因描述
                    entry_reason = get_entry_reason(data.iloc[i], signal_type)
                    trades.append({
                        'date': current_date,
                        'action': 'BUY',
                        'price': round(buy_price, 3),
                        'size': size,
                        'signal_type': signal_type,
                        'entry_reason': entry_reason
                    })

        # ---- 记录当日权益（市值 + 现金）----
        equity = cash + position * current_price if in_position else cash
        daily_equity.append(equity)

    # ================================================================
    # 期末处理：强制平仓
    # ================================================================
    if in_position and position > 0:
        last_price = data.iloc[-1]['close'] * (1 - slippage)
        fee = last_price * position * (commission + stamp_duty)
        cash += last_price * position - fee
        profit = (last_price - entry_price) / entry_price
        trades.append({
            'date': data.index[-1],
            'action': 'SELL',
            'price': round(last_price, 3),
            'profit_pct': round(profit * 100, 2),
            'hold_days': hold_days,
            'reason': '期末平仓'
        })

    # ---- 构建返回值 ----
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    equity_series = pd.Series(daily_equity, index=data.index)
    metrics = calculate_metrics(daily_equity, trades)
    return trades_df, equity_series, metrics


# ============================================================
# 绩效指标计算
# ============================================================

def calculate_metrics(daily_equity, trades):
    """
    根据每日权益序列和交易记录计算综合绩效指标

    包含：总收益、年化收益、最大回撤、夏普比率、Sortino 比率、
          Calmar 比率、胜率、盈亏比、盈亏因子、最大连续亏损、平均持仓天数

    Args:
        daily_equity: 每日权益列表
        trades:       交易记录列表（含 BUY/SELL 明细）

    Returns:
        dict: 绩效指标字典
    """
    # ---- 数据有效性检查 ----
    if not daily_equity or len(daily_equity) < 2:
        return {'error': '数据不足，至少需要 2 个交易日'}

    equity_series = pd.Series(daily_equity)
    returns = equity_series.pct_change().dropna()   # 日收益率序列

    # ---- 收益指标 ----
    total_return = (equity_series.iloc[-1] / equity_series.iloc[0] - 1) * 100
    days = len(daily_equity)
    annual_return = ((1 + total_return / 100) ** (250 / days) - 1) * 100 if days > 0 else 0

    # ---- 风险指标 ----
    cum_max = equity_series.expanding().max()        # 滚动历史最大值
    drawdown = (equity_series - cum_max) / cum_max   # 回撤序列
    max_drawdown = drawdown.min() * 100              # 最大回撤（%）

    # 无风险利率（年化 3%，按日折算）
    risk_free = 0.03 / 250

    # ---- 风险调整收益 ----
    # 夏普比率（Sharpe Ratio）
    sharpe = (returns.mean() - risk_free) / returns.std() * np.sqrt(250) if returns.std() > 0 else 0

    # Sortino 比率（仅使用下行标准差）
    downside_returns = returns[returns < 0]
    downside_std = downside_returns.std() if len(downside_returns) > 1 else 0
    sortino = (returns.mean() - risk_free) / downside_std * np.sqrt(250) if downside_std > 0 else 0

    # Calmar 比率（年化收益 / 最大回撤绝对值）
    calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0

    # ---- 交易统计 ----
    sell_trades = [t for t in trades if t['action'] == 'SELL']
    total_trades = len(sell_trades)

    # 胜率与盈亏
    win_trades = [t for t in sell_trades if t['profit_pct'] > 0]
    loss_trades = [t for t in sell_trades if t['profit_pct'] <= 0]
    win_rate = len(win_trades) / total_trades * 100 if total_trades > 0 else 0

    avg_win = np.mean([t['profit_pct'] for t in win_trades]) if win_trades else 0
    avg_loss = abs(np.mean([t['profit_pct'] for t in loss_trades])) if loss_trades else 1
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0  # 平均盈亏比

    # 盈亏因子（总盈利金额 / 总亏损金额）
    total_win = sum([t['profit_pct'] for t in win_trades]) if win_trades else 0
    total_loss = abs(sum([t['profit_pct'] for t in loss_trades])) if loss_trades else 1
    profit_factor = total_win / total_loss if total_loss > 0 else 0

    # 最大连续亏损次数
    max_consecutive_loss = 0
    current_streak = 0
    for t in sell_trades:
        if t['profit_pct'] <= 0:
            current_streak += 1
            max_consecutive_loss = max(max_consecutive_loss, current_streak)
        else:
            current_streak = 0

    # 平均持仓天数
    avg_hold_days = np.mean([t['hold_days'] for t in sell_trades]) if sell_trades else 0

    # ---- 汇总返回 ----
    return {
        # 核心收益指标
        'total_return': round(total_return, 2),
        'annual_return': round(annual_return, 2),
        'max_drawdown': round(max_drawdown, 2),
        # 风险调整指标
        'sharpe_ratio': round(sharpe, 3),
        'sortino_ratio': round(sortino, 3),
        'calmar_ratio': round(calmar, 3),
        # 交易统计
        'total_trades': total_trades,
        'win_trades': len(win_trades),
        'loss_trades': len(loss_trades),
        'win_rate': round(win_rate, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_loss_ratio': round(profit_loss_ratio, 3),
        'profit_factor': round(profit_factor, 3),
        'max_consecutive_loss': max_consecutive_loss,
        'avg_hold_days': round(avg_hold_days, 1),
        'final_equity': round(equity_series.iloc[-1], 2)
    }
