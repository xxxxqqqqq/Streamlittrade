import unittest

import pandas as pd

from quant_core.market_data import validate_market_dataset
from quant_core.portfolio_backtesting import run_portfolio_backtest


def bars(prices, signals, *, volume=100_000, **extra):
    count = len(prices)
    values = {
        "open": prices, "high": [p * 1.02 for p in prices], "low": [p * 0.98 for p in prices],
        "close": prices, "volume": [volume] * count, "signal": signals,
    }
    values.update(extra)
    return pd.DataFrame(values, index=pd.date_range("2024-01-02", periods=count, freq="B"))


class MarketDataGovernanceTests(unittest.TestCase):
    def test_quality_gate_rejects_invalid_ohlc(self):
        data = bars([10, 11], [False, False])
        data.loc[data.index[1], "high"] = 5
        with self.assertRaisesRegex(ValueError, "quality gate"):
            validate_market_dataset({"A": data})

    def test_quality_report_detects_unbalanced_calendar(self):
        first = bars([10, 11, 12], [False] * 3)
        second = bars([20, 21], [False] * 2)
        _, report = validate_market_dataset({"A": first, "B": second})
        self.assertEqual(report.missing_calendar_rows, 1)
        self.assertIn("unbalanced_symbol_calendar", report.warnings)


class PortfolioCredibilityTests(unittest.TestCase):
    def test_symbols_share_cash_and_orders_use_next_open(self):
        frames = {"A": bars([10, 10, 10], [True, True, False]), "B": bars([20, 20, 20], [True, True, False])}
        trades, equity, metrics, audit = run_portfolio_backtest(
            frames, initial_cash=100_000, max_positions=2, commission=0, min_commission=0,
            stamp_duty=0, slippage=0, max_volume_participation=1,
        )
        buys = trades[trades.action == "BUY"]
        self.assertEqual(set(buys.symbol), {"A", "B"})
        self.assertTrue((pd.to_datetime(buys.date) == frames["A"].index[1]).all())
        self.assertLessEqual(sum(buys.price * buys.shares), 100_000)
        self.assertEqual(audit["constraint_model"]["settlement"], "T+1")
        self.assertEqual(audit["constraint_model"]["slippage"], 0)
        self.assertAlmostEqual(equity.iloc[-1], 100_000)

    def test_sell_event_keeps_signal_and_entry_lineage(self):
        data = bars([10, 10, 11, 11], [True, False, False, False])
        trades, _, _, _ = run_portfolio_backtest(
            {"A": data}, commission=0, min_commission=0,
            stamp_duty=0, slippage=0, max_volume_participation=1,
        )
        sell = trades[trades.action == "SELL"].iloc[0]
        self.assertEqual(sell.signal_date, data.index[1])
        self.assertEqual(sell.entry_date, data.index[1])
        self.assertEqual(sell.reason, "removed_from_target_basket")

    def test_suspension_and_limit_up_reject_buys(self):
        a = bars([10, 10, 10], [True, False, False], is_suspended=[False, True, False])
        b = bars([10, 11, 11], [True, False, False], limit_up=[None, 11, 12])
        trades, _, metrics, _ = run_portfolio_backtest({"A": a, "B": b}, commission=0, min_commission=0, stamp_duty=0, slippage=0)
        rejected = trades[trades.action == "REJECT_BUY"]
        self.assertEqual(set(rejected.reason), {"suspended", "limit_up_locked"})
        self.assertEqual(metrics["rejected_orders"], 2)

    def test_volume_capacity_limits_fills_to_board_lots(self):
        data = bars([10, 10, 10], [True, True, False], volume=1_000)
        trades, _, _, _ = run_portfolio_backtest({"A": data}, max_volume_participation=0.1, commission=0, min_commission=0, stamp_duty=0, slippage=0)
        buy = trades[trades.action == "BUY"].iloc[0]
        self.assertEqual(buy.shares, 100)


if __name__ == "__main__":
    unittest.main()
