import unittest

import pandas as pd

from quant_core.model_portfolio import build_model_signal_frames, rank_model_predictions


def market(symbol: str) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=8, freq="B")
    return pd.DataFrame(
        {
            "open": [10.0] * len(dates),
            "high": [10.2] * len(dates),
            "low": [9.8] * len(dates),
            "close": [10.0] * len(dates),
            "volume": [100_000] * len(dates),
        },
        index=dates,
    )


class ModelPortfolioConstructionTests(unittest.TestCase):
    def test_cross_sectional_rank_uses_stable_symbol_tie_breaker(self):
        date = pd.Timestamp("2024-01-02")
        ranked = rank_model_predictions(pd.DataFrame([
            {"date": date, "symbol": "B", "probability": 0.8},
            {"date": date, "symbol": "A", "probability": 0.8},
            {"date": date, "symbol": "C", "probability": 0.7},
        ]))
        self.assertEqual(ranked.symbol.tolist(), ["A", "B", "C"])
        self.assertEqual(ranked["rank"].tolist(), [1, 2, 3])
        self.assertEqual(ranked["universe_size"].tolist(), [3, 3, 3])

    def test_top_n_signals_persist_until_next_rebalance(self):
        dates = pd.date_range("2024-01-02", periods=8, freq="B")
        predictions = pd.DataFrame(
            [
                {"date": date, "symbol": symbol, "probability": probability}
                for date in dates
                for symbol, probability in (("A", 0.8), ("B", 0.6), ("C", 0.4))
            ]
        )
        frames, audit = build_model_signal_frames(
            {"A": market("A"), "B": market("B"), "C": market("C")},
            predictions,
            top_n=1,
            minimum_probability=0.5,
            rebalance_frequency=5,
        )

        self.assertTrue(frames["A"]["signal"].all())
        self.assertFalse(frames["B"]["signal"].any())
        self.assertEqual(audit["rebalance_count"], 2)
        self.assertTrue(audit["out_of_sample_only"])
        self.assertEqual(audit["rebalances"][0]["ranks"], {"A": 1})

    def test_rejects_duplicate_prediction_rows(self):
        date = pd.Timestamp("2024-01-02")
        predictions = pd.DataFrame(
            [
                {"date": date, "symbol": "A", "probability": 0.8},
                {"date": date, "symbol": "A", "probability": 0.7},
            ]
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_model_signal_frames({"A": market("A")}, predictions)

    def test_no_probability_above_threshold_is_a_valid_cash_portfolio(self):
        dates = pd.date_range("2024-01-02", periods=8, freq="B")
        predictions = pd.DataFrame([
            {"date": date, "symbol": "A", "probability": 0.49}
            for date in dates
        ])
        frames, audit = build_model_signal_frames(
            {"A": market("A")}, predictions,
            top_n=1, minimum_probability=0.55, rebalance_frequency=5,
        )
        self.assertFalse(frames["A"]["signal"].any())
        self.assertFalse(audit["has_eligible_selections"])
        self.assertIn("remained in cash", audit["selection_warning"])


if __name__ == "__main__":
    unittest.main()
