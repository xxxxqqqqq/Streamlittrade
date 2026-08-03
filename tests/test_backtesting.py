"""可信回测关键约束的回归测试。

这些测试使用完全可控的合成日线，不访问网络。它们验证的是交易时间和资金
账本，而不是某个策略能否盈利，因此适合作为后续重构的稳定安全网。
"""

import unittest

import pandas as pd

from quant_core.backtesting import run_backtest


def make_bars(
    opens,
    highs=None,
    lows=None,
    closes=None,
    signals=None,
    signal_type="custom",
):
    """构造字段齐全的日线数据，减少每个测试的样板代码。"""
    count = len(opens)
    closes = closes or opens
    highs = highs or [value + 0.5 for value in opens]
    lows = lows or [value - 0.5 for value in opens]
    signals = signals or [False] * count
    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "signal": signals,
            "signal_type": [signal_type] * count,
        },
        index=pd.date_range("2024-01-02", periods=count, freq="B"),
    )


class BacktestCredibilityTests(unittest.TestCase):
    """验证成交时点、T+1、整手和费用等不可退化的行为。"""

    @staticmethod
    def run_without_costs(data, **kwargs):
        defaults = {
            "initial_cash": 100_000,
            "position_pct": 0.30,
            "commission": 0,
            "min_commission": 0,
            "stamp_duty": 0,
            "slippage": 0,
            "stop_loss": 0,
            "take_profit": 0,
            "trailing_stop": 0,
        }
        defaults.update(kwargs)
        return run_backtest(data, **defaults)

    def test_close_signal_executes_at_next_open(self):
        data = make_bars([10, 12, 13], signals=[True, False, False])
        trades, _, _ = self.run_without_costs(data)

        buy = trades.iloc[0]
        self.assertEqual(buy["action"], "BUY")
        self.assertEqual(buy["date"], data.index[1])
        self.assertEqual(buy["signal_date"], data.index[0])
        self.assertEqual(buy["price"], 12)

    def test_position_is_rounded_down_to_board_lot(self):
        data = make_bars([10, 11, 11], signals=[True, False, False])
        trades, _, _ = self.run_without_costs(data)

        self.assertGreater(trades.iloc[0]["size"], 0)
        self.assertEqual(trades.iloc[0]["size"] % 100, 0)

    def test_buy_day_cannot_trigger_stop_loss(self):
        # 第二根K线开盘买入后虽然最低价触及止损，也必须等到下一交易日才能卖。
        data = make_bars(
            [10, 10, 9],
            highs=[10.5, 10.2, 9.5],
            lows=[9.5, 8.0, 8.5],
            closes=[10, 9, 9],
            signals=[True, False, False],
        )
        trades, _, _ = self.run_without_costs(data, stop_loss=0.05)

        sell = trades[trades["action"] == "SELL"].iloc[0]
        self.assertEqual(sell["date"], data.index[2])
        self.assertEqual(sell["hold_days"], 1)

    def test_forced_liquidation_cost_is_in_final_equity(self):
        data = make_bars([10, 10, 10], signals=[True, False, False])
        trades, equity, metrics = run_backtest(
            data,
            initial_cash=100_000,
            position_pct=0.30,
            commission=0.001,
            min_commission=5,
            stamp_duty=0.001,
            slippage=0,
            stop_loss=0,
            take_profit=0,
            trailing_stop=0,
        )

        self.assertEqual(metrics["final_equity"], round(equity.iloc[-1], 2))
        self.assertLess(metrics["final_equity"], 100_000)
        self.assertLess(metrics["total_return"], 0)
        sell = trades[trades["action"] == "SELL"].iloc[0]
        self.assertGreater(sell["commission"], 0)
        self.assertGreater(sell["stamp_duty"], 0)

    def test_total_return_uses_initial_cash_not_first_daily_value(self):
        data = make_bars([10, 10, 11], closes=[10, 10, 11], signals=[True, False, False])
        _, equity, metrics = self.run_without_costs(data)

        expected = (equity.iloc[-1] / 100_000 - 1) * 100
        self.assertAlmostEqual(metrics["total_return"], round(expected, 2))

    def test_missing_columns_returns_clear_error(self):
        data = pd.DataFrame({"close": [10, 11], "signal": [True, False]})
        trades, equity, metrics = self.run_without_costs(data)

        self.assertIsNone(trades)
        self.assertIsNone(equity)
        self.assertIn("缺少字段", metrics["error"])


if __name__ == "__main__":
    unittest.main()
