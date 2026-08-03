"""与界面无关、面向 A 股日线策略的回测核心。

可信度约定：
1. T 日收盘数据产生的买入信号只能在 T+1 日开盘成交，避免同周期未来函数。
2. 股票数量按整手向下取整，并模拟最低佣金、滑点和卖出印花税。
3. 买入当天不允许卖出；从下一交易日开始才检查退出，符合 A 股 T+1。
4. 硬止损、移动止损、ATR 止损和止盈使用日线 OHLC 模拟触价成交。
5. 最后一日可执行可配置的强制平仓，相关费用会进入最终净值和绩效指标。

这仍然是日线级研究回测，不等价于券商逐笔撮合。涨跌停、停牌、部分成交和
复权现金流应在后续接入更完整的数据源后继续增强。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = {"open", "high", "low", "close", "signal"}


def get_entry_reason(row: pd.Series, signal_type: str) -> str:
    """根据策略诊断列生成可读的入场原因。"""
    if signal_type == "right":
        reasons: list[str] = []
        if row.get("MA5", 0) > row.get("MA20", 0) > row.get("MA60", 0):
            reasons.append("均线多头")
        if row.get("DIF", 0) > row.get("DEA", 0) and row.get("DIF", 0) > 0:
            reasons.append("MACD金叉")
        if row.get("volume", 0) > row.get("VOL_MA20", np.inf) * 1.5:
            reasons.append("放量")
        if row.get("close", 0) > row.get("MA60", np.inf):
            reasons.append("站上60日线")
        if row.get("K", 0) > row.get("D", 0) and row.get("J", 0) > 20:
            reasons.append("KDJ金叉")
        if 50 < row.get("RSI", 0) < 70:
            reasons.append("RSI强势")
        if row.get("MACD_bar", -np.inf) > row.get("MACD_bar_shift", np.inf):
            reasons.append("MACD放大")
        return " | ".join(reasons) if reasons else "右侧信号"

    if signal_type == "v_shape":
        parts: list[str] = []
        for column, label, scale, digits in (
            ("drop_used", "跌幅", 100, 1),
            ("rebound_used", "反弹", 100, 1),
            ("vol_ratio_used", "量比", 1, 2),
        ):
            value = row.get(column, np.nan)
            if pd.notna(value):
                suffix = "%" if scale == 100 else ""
                parts.append(f"{label}{value * scale:.{digits}f}{suffix}")
        return " | ".join(parts) if parts else "V型反转"

    return "自定义策略" if signal_type == "custom" else "未知信号"


def _commission(notional: float, rate: float, minimum: float) -> float:
    """计算单边佣金；零成交额不收取费用。"""
    return max(notional * rate, minimum) if notional > 0 else 0.0


def _validate_inputs(data: pd.DataFrame, position_pct: float, lot_size: int) -> None:
    """在进入逐日循环前尽早拒绝结构错误或危险参数。"""
    missing = REQUIRED_COLUMNS.difference(data.columns)
    if missing:
        raise ValueError(f"回测数据缺少字段: {', '.join(sorted(missing))}")
    if not 0 < position_pct <= 1:
        raise ValueError("position_pct 必须在 (0, 1] 范围内")
    if lot_size < 1:
        raise ValueError("lot_size 必须大于等于 1")


def run_backtest(
    df: pd.DataFrame,
    initial_cash: float = 100000,
    commission: float = 0.0003,
    slippage: float = 0.001,
    stop_loss: float = 0.08,
    take_profit: float = 0.20,
    trailing_stop: float = 0.05,
    use_atr_stop: bool = False,
    atr_period: int = 14,
    atr_multiple: float = 2.0,
    stamp_duty: float = 0.0005,
    signal_confirm: int = 1,
    max_hold_days: int = 20,
    position_pct: float = 0.30,
    lot_size: int = 100,
    min_commission: float = 5.0,
    liquidate_at_end: bool = True,
) -> tuple[pd.DataFrame | None, pd.Series | None, dict[str, Any]]:
    """运行日线回测并返回交易、每日净值和绩效字典。

    为保持现有页面兼容，返回值仍是旧版的三元组。新增参数均有默认值，因此
    ``optimizer.py``、``portfolio.py`` 等旧调用方不需要修改。
    """
    if df is None or df.empty:
        return None, None, {"error": "无有效数据"}

    data = df.copy()
    try:
        _validate_inputs(data, position_pct, lot_size)
    except ValueError as exc:
        return None, None, {"error": str(exc)}

    data = data[~data.index.duplicated(keep="first")].sort_index()
    data["signal"] = data["signal"].fillna(False).astype(bool)
    if "MA20" not in data.columns:
        data["MA20"] = data["close"].rolling(20).mean()

    if use_atr_stop:
        previous_close = data["close"].shift(1)
        true_range = pd.concat(
            [
                data["high"] - data["low"],
                (data["high"] - previous_close).abs(),
                (data["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        data["ATR"] = true_range.rolling(atr_period).mean()

    if signal_confirm > 1:
        rolling_count = data["signal"].astype(int).rolling(signal_confirm).sum()
        data["signal_confirmed"] = rolling_count.ge(signal_confirm) & data["signal"]
    else:
        data["signal_confirmed"] = data["signal"]

    cash = float(initial_cash)
    position = 0
    entry_price = 0.0
    entry_total_cost = 0.0
    entry_index: int | None = None
    entry_signal_type = "unknown"
    highest_price = 0.0
    pending_entry: dict[str, Any] | None = None
    pending_exit_reason: str | None = None
    trades: list[dict[str, Any]] = []
    daily_equity: list[float] = []

    def close_position(date: Any, raw_price: float, reason: str, hold_days: int) -> None:
        """统一执行卖出，确保每种退出路径使用完全相同的费用口径。"""
        nonlocal cash, position, entry_price, entry_total_cost
        nonlocal entry_index, entry_signal_type, highest_price

        sell_price = max(float(raw_price) * (1 - slippage), 0.0)
        notional = sell_price * position
        sell_commission = _commission(notional, commission, min_commission)
        duty = notional * stamp_duty
        net_proceeds = notional - sell_commission - duty
        pnl = net_proceeds - entry_total_cost
        profit_pct = pnl / entry_total_cost * 100 if entry_total_cost else 0.0
        cash += net_proceeds
        trades.append(
            {
                "date": date,
                "action": "SELL",
                "price": round(sell_price, 3),
                "size": position,
                "commission": round(sell_commission, 2),
                "stamp_duty": round(duty, 2),
                "pnl": round(pnl, 2),
                "profit_pct": round(profit_pct, 2),
                "hold_days": hold_days,
                "reason": reason,
            }
        )
        position = 0
        entry_price = 0.0
        entry_total_cost = 0.0
        entry_index = None
        entry_signal_type = "unknown"
        highest_price = 0.0

    for i, (current_date, row) in enumerate(data.iterrows()):
        open_price = float(row["open"])
        high_price = float(row["high"])
        low_price = float(row["low"])
        close_price = float(row["close"])
        sold_today = False

        # 收盘后生成的趋势/时间退出指令，在下一交易日开盘执行。
        if position > 0 and pending_exit_reason and entry_index is not None and i > entry_index:
            close_position(current_date, open_price, pending_exit_reason, i - entry_index)
            pending_exit_reason = None
            sold_today = True

        # T 日信号延迟至 T+1 开盘成交，彻底断开信号收盘价与成交价。
        if position == 0 and pending_entry and not sold_today:
            buy_price = open_price * (1 + slippage)
            target_value = cash * position_pct
            raw_lots = int(target_value // (buy_price * lot_size))
            size = raw_lots * lot_size
            if size > 0:
                notional = buy_price * size
                buy_commission = _commission(notional, commission, min_commission)
                total_cost = notional + buy_commission
                if total_cost <= cash:
                    cash -= total_cost
                    position = size
                    entry_price = buy_price
                    entry_total_cost = total_cost
                    entry_index = i
                    entry_signal_type = pending_entry["signal_type"]
                    highest_price = buy_price
                    trades.append(
                        {
                            "date": current_date,
                            "action": "BUY",
                            "price": round(buy_price, 3),
                            "size": size,
                            "commission": round(buy_commission, 2),
                            "signal_type": entry_signal_type,
                            "signal_date": pending_entry["signal_date"],
                            "entry_reason": pending_entry["entry_reason"],
                        }
                    )
            pending_entry = None

        # 买入日 elapsed_days=0，不允许卖出；下一交易日起才检查触价退出。
        if position > 0 and entry_index is not None and i - entry_index >= 1:
            elapsed_days = i - entry_index
            stop_candidates: list[tuple[float, str]] = []
            if stop_loss > 0:
                stop_candidates.append((entry_price * (1 - stop_loss), f"硬止损 (-{stop_loss * 100:.0f}%)"))
            if trailing_stop > 0:
                stop_candidates.append((highest_price * (1 - trailing_stop), f"移动止损 (回撤{trailing_stop * 100:.0f}%)"))
            if use_atr_stop and i > 0:
                previous_atr = data["ATR"].iloc[i - 1]
                if pd.notna(previous_atr):
                    stop_candidates.append((highest_price - atr_multiple * previous_atr, f"ATR动态止损 ({atr_multiple:.1f}xATR)"))

            # 多个止损同时有效时选择最高的止损线，即风险控制最严格的一条。
            if stop_candidates:
                stop_price, stop_reason = max(stop_candidates, key=lambda item: item[0])
                if open_price <= stop_price:
                    close_position(current_date, open_price, stop_reason, elapsed_days)
                    sold_today = True
                elif low_price <= stop_price:
                    close_position(current_date, stop_price, stop_reason, elapsed_days)
                    sold_today = True

            # 若同一根日K同时触发止损和止盈，先处理止损属于保守估计。
            if position > 0 and take_profit > 0:
                target_price = entry_price * (1 + take_profit)
                if open_price >= target_price:
                    close_position(current_date, open_price, f"目标止盈 (+{take_profit * 100:.0f}%)", elapsed_days)
                    sold_today = True
                elif high_price >= target_price:
                    close_position(current_date, target_price, f"目标止盈 (+{take_profit * 100:.0f}%)", elapsed_days)
                    sold_today = True

            if position > 0:
                highest_price = max(highest_price, high_price)
                if entry_signal_type == "right" and pd.notna(row.get("MA20")) and close_price < row["MA20"]:
                    pending_exit_reason = "趋势止损 (跌破MA20，次日开盘)"
                elif entry_signal_type == "v_shape" and elapsed_days >= max_hold_days:
                    pending_exit_reason = f"时间止损 (持有{elapsed_days}天，次日开盘)"

        elif position > 0:
            # 买入当日虽然受 T+1 保护不能卖出，但当日最高价属于已经发生的行情，
            # 应成为下一交易日移动止损的历史高点。
            highest_price = max(highest_price, high_price)

        # 空仓时只登记信号；真实买入发生在下一次循环的开盘。
        if position == 0 and not sold_today and pending_entry is None and bool(row["signal_confirmed"]):
            signal_type = str(row.get("signal_type", "unknown"))
            pending_entry = {
                "signal_date": current_date,
                "signal_type": signal_type,
                "entry_reason": get_entry_reason(row, signal_type),
            }

        is_last_bar = i == len(data) - 1
        if is_last_bar and liquidate_at_end and position > 0 and entry_index is not None:
            close_position(current_date, close_price, "期末平仓", i - entry_index)
            pending_exit_reason = None

        daily_equity.append(cash + position * close_price)

    trades_df = pd.DataFrame(trades)
    equity_series = pd.Series(daily_equity, index=data.index, name="equity")
    metrics = calculate_metrics(equity_series, trades, initial_cash=initial_cash)
    return trades_df, equity_series, metrics


def calculate_metrics(
    daily_equity: list[float] | pd.Series,
    trades: list[dict[str, Any]],
    initial_cash: float | None = None,
) -> dict[str, Any]:
    """使用统一的资金口径计算收益、风险和交易统计。

    ``initial_cash`` 是总收益率的正确基准。为兼容旧的直接调用方式，未提供时
    才回退到第一条净值；新版回测引擎始终显式传入该参数。
    """
    equity = pd.Series(daily_equity, dtype=float).dropna().reset_index(drop=True)
    if len(equity) < 2:
        return {"error": "数据不足，至少需要 2 个交易日"}

    base_cash = float(initial_cash if initial_cash is not None else equity.iloc[0])
    # 在净值序列前补上初始现金，使第一天发生的费用也进入日收益。
    equity_with_base = pd.concat([pd.Series([base_cash]), equity], ignore_index=True)
    returns = equity_with_base.pct_change().dropna()
    total_return_ratio = equity.iloc[-1] / base_cash - 1
    annual_return_ratio = (1 + total_return_ratio) ** (250 / len(equity)) - 1

    running_max = equity_with_base.cummax()
    drawdown = (equity_with_base - running_max) / running_max
    max_drawdown_ratio = float(drawdown.min())
    daily_risk_free = 0.03 / 250
    return_std = returns.std()
    sharpe = (returns.mean() - daily_risk_free) / return_std * np.sqrt(250) if return_std > 0 else 0.0
    downside = returns[returns < 0]
    downside_std = downside.std() if len(downside) > 1 else 0.0
    sortino = (returns.mean() - daily_risk_free) / downside_std * np.sqrt(250) if downside_std > 0 else 0.0
    calmar = annual_return_ratio / abs(max_drawdown_ratio) if max_drawdown_ratio else 0.0

    sells = [trade for trade in trades if trade.get("action") == "SELL"]
    wins = [trade for trade in sells if trade.get("pnl", trade.get("profit_pct", 0)) > 0]
    losses = [trade for trade in sells if trade.get("pnl", trade.get("profit_pct", 0)) <= 0]
    pnl_values = [float(trade.get("pnl", trade.get("profit_pct", 0))) for trade in sells]
    win_values = [value for value in pnl_values if value > 0]
    loss_values = [value for value in pnl_values if value <= 0]
    avg_win = float(np.mean([trade.get("profit_pct", 0) for trade in wins])) if wins else 0.0
    avg_loss = abs(float(np.mean([trade.get("profit_pct", 0) for trade in losses]))) if losses else 0.0
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    gross_profit = sum(win_values)
    gross_loss = abs(sum(loss_values))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)

    max_consecutive_loss = 0
    current_loss_streak = 0
    for value in pnl_values:
        current_loss_streak = current_loss_streak + 1 if value <= 0 else 0
        max_consecutive_loss = max(max_consecutive_loss, current_loss_streak)

    return {
        "total_return": round(total_return_ratio * 100, 2),
        "annual_return": round(annual_return_ratio * 100, 2),
        "max_drawdown": round(max_drawdown_ratio * 100, 2),
        "sharpe_ratio": round(float(sharpe), 3),
        "sortino_ratio": round(float(sortino), 3),
        "calmar_ratio": round(float(calmar), 3),
        "total_trades": len(sells),
        "win_trades": len(wins),
        "loss_trades": len(losses),
        "win_rate": round(len(wins) / len(sells) * 100, 2) if sells else 0.0,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_loss_ratio": round(profit_loss_ratio, 3),
        "profit_factor": round(profit_factor, 3),
        "max_consecutive_loss": max_consecutive_loss,
        "avg_hold_days": round(float(np.mean([t.get("hold_days", 0) for t in sells])), 1) if sells else 0.0,
        "final_equity": round(float(equity.iloc[-1]), 2),
    }
