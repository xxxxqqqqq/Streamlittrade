"""Shared-cash, daily portfolio backtest with conservative A-share constraints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd

from .backtesting import calculate_metrics
from .market_data import validate_market_dataset


@dataclass
class Position:
    shares: int
    acquired_date: pd.Timestamp
    cost: float
    signal_date: pd.Timestamp | None = None


def _fee(notional: float, rate: float, minimum: float) -> float:
    return max(notional * rate, minimum) if notional else 0.0


def run_portfolio_backtest(
    frames: Mapping[str, pd.DataFrame], *, initial_cash: float = 1_000_000,
    max_positions: int = 10, lot_size: int = 100, commission: float = 0.0003,
    stamp_duty: float = 0.0005, min_commission: float = 5.0, slippage: float = 0.001,
    max_volume_participation: float = 0.05, benchmark: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.Series, dict, dict]:
    """Rebalance at T+1 open from prior-close signals using one shared cash ledger."""
    canonical, quality = validate_market_dataset(frames)
    if not 1 <= max_positions <= 500: raise ValueError("max_positions must be between 1 and 500")
    if not 0 < max_volume_participation <= 1: raise ValueError("max_volume_participation must be in (0, 1]")
    dates = sorted(set().union(*(set(frame.index) for frame in canonical.values())))
    cash, positions = float(initial_cash), {}
    events, equity_values, holdings_history = [], [], []
    previous_targets: list[str] = []

    for date_index, date in enumerate(dates):
        # Apply explicit corporate actions before trading. Adjusted feeds should
        # leave these defaults untouched to prevent double counting.
        for symbol, position in list(positions.items()):
            if date not in canonical[symbol].index: continue
            row = canonical[symbol].loc[date]
            split = float(row["split_ratio"])
            if split > 0 and split != 1:
                position.shares = int(position.shares * split)
                position.cost /= split
            cash += position.shares * float(row["cash_dividend"])

        prior_date = dates[date_index - 1] if date_index else None
        targets = []
        if prior_date is not None:
            scored = []
            for symbol, frame in canonical.items():
                if prior_date in frame.index and bool(frame.loc[prior_date].get("signal", False)):
                    scored.append((float(frame.loc[prior_date].get("score", 1.0)), symbol))
            targets = [symbol for _, symbol in sorted(scored, reverse=True)[:max_positions]]
        previous_targets = targets

        # Sells occur first to release shared cash. T+1 prevents same-day disposal.
        for symbol in list(positions):
            if symbol in targets or date not in canonical[symbol].index: continue
            row, position = canonical[symbol].loc[date], positions[symbol]
            reason = None
            if row["is_suspended"]: reason = "suspended"
            elif float(row["open"]) <= float(row["limit_down"]): reason = "limit_down_locked"
            elif date <= position.acquired_date: reason = "t_plus_one"
            if reason:
                events.append({"date": date, "signal_date": prior_date, "symbol": symbol, "action": "REJECT_SELL", "reason": reason})
                continue
            capacity = int(float(row["volume"]) * max_volume_participation // lot_size) * lot_size
            shares = min(position.shares, capacity)
            if shares <= 0: continue
            price = float(row["open"]) * (1 - slippage)
            notional = shares * price; fee = _fee(notional, commission, min_commission); duty = notional * stamp_duty
            allocated_cost = position.cost * shares / position.shares
            pnl = notional - fee - duty - allocated_cost
            cash += notional - fee - duty
            position.shares -= shares
            position.cost -= allocated_cost
            events.append({"date": date, "signal_date": prior_date, "entry_date": position.acquired_date, "symbol": symbol, "action": "SELL", "price": price, "shares": shares, "commission": fee, "stamp_duty": duty, "pnl": pnl, "profit_pct": pnl / allocated_cost * 100 if allocated_cost else 0.0, "reason": "removed_from_target_basket"})
            if position.shares == 0: del positions[symbol]

        available_targets = [s for s in targets if s not in positions and date in canonical[s].index]
        target_value = (cash + sum(p.shares * float(canonical[s].loc[date, "close"]) for s,p in positions.items() if date in canonical[s].index)) / max(len(targets), 1)
        for symbol in available_targets:
            row = canonical[symbol].loc[date]
            reason = None
            if row["is_suspended"]: reason = "suspended"
            elif float(row["open"]) >= float(row["limit_up"]): reason = "limit_up_locked"
            if reason:
                events.append({"date": date, "signal_date": prior_date, "symbol": symbol, "action": "REJECT_BUY", "reason": reason})
                continue
            price = float(row["open"]) * (1 + slippage)
            capacity = int(float(row["volume"]) * max_volume_participation // lot_size) * lot_size
            affordable = int(min(target_value, cash) // (price * lot_size)) * lot_size
            shares = min(capacity, affordable)
            if shares <= 0: continue
            notional = shares * price; fee = _fee(notional, commission, min_commission)
            while shares > 0 and notional + fee > cash:
                shares -= lot_size; notional = shares * price; fee = _fee(notional, commission, min_commission)
            if shares <= 0: continue
            cash -= notional + fee
            positions[symbol] = Position(shares=shares, acquired_date=date, cost=notional + fee, signal_date=prior_date)
            events.append({"date": date, "symbol": symbol, "action": "BUY", "price": price, "shares": shares, "commission": fee, "signal_date": prior_date})

        market_value = 0.0
        for symbol, position in positions.items():
            frame = canonical[symbol]
            history = frame.loc[frame.index <= date, "close"]
            if not history.empty: market_value += position.shares * float(history.iloc[-1])
            holdings_history.append({"date": date, "symbol": symbol, "shares": position.shares})
        equity_values.append(cash + market_value)

    equity = pd.Series(equity_values, index=pd.DatetimeIndex(dates), name="equity")
    trades = pd.DataFrame(events)
    metrics = calculate_metrics(equity, trades.to_dict("records"), initial_cash=initial_cash)
    returns = pd.concat([pd.Series([initial_cash]), equity.reset_index(drop=True)], ignore_index=True).pct_change().dropna()
    metrics.update({"turnover_events": int(trades.action.isin(["BUY", "SELL"]).sum()) if not trades.empty else 0,
                    "rejected_orders": int(trades.action.str.startswith("REJECT").sum()) if not trades.empty else 0,
                    "max_positions": max_positions, "max_volume_participation": max_volume_participation})
    if benchmark is not None:
        aligned = benchmark.reindex(equity.index).ffill().pct_change().fillna(0)
        active = returns.reset_index(drop=True) - aligned.reset_index(drop=True)
        tracking = float(active.std(ddof=1))
        metrics.update({"benchmark_return": round(float(benchmark.reindex(equity.index).ffill().iloc[-1] / benchmark.reindex(equity.index).ffill().iloc[0] - 1) * 100, 2),
                        "excess_return": round(metrics["total_return"] - float(benchmark.reindex(equity.index).ffill().iloc[-1] / benchmark.reindex(equity.index).ffill().iloc[0] - 1) * 100, 2),
                        "tracking_error": round(tracking * np.sqrt(250), 6),
                        "information_ratio": round(float(active.mean() / tracking * np.sqrt(250)) if tracking else 0.0, 4)})
    audit = {"data_quality": quality.to_dict(), "holdings": holdings_history, "constraint_model": {
        "signal_execution": "next_trading_day_open", "settlement": "T+1", "lot_size": lot_size,
        "limit_lock": True, "suspension": True, "volume_participation": max_volume_participation,
        "commission": commission, "minimum_commission": min_commission,
        "stamp_duty": stamp_duty, "slippage": slippage,
        "corporate_actions": ["cash_dividend", "split_ratio"],
    }}
    return trades, equity, metrics, audit
