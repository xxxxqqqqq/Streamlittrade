import unittest

import pandas as pd

from quant_core.model_portfolio import build_model_signal_frames


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


if __name__ == "__main__":
    unittest.main()
