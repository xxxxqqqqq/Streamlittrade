import unittest

import numpy as np
import pandas as pd

from quant_core.ml import economic_metrics, purged_walk_forward_splits, three_way_research_split


class WalkForwardTests(unittest.TestCase):
    def test_symbols_on_same_date_never_cross_fold_boundary(self):
        dates = pd.Series(np.repeat(pd.date_range("2020-01-01", periods=120, freq="B"), 3))
        folds = list(purged_walk_forward_splits(dates, n_splits=4, purge_days=5, embargo_days=5))
        self.assertEqual(len(folds), 4)
        for fold in folds:
            train_dates = set(dates.iloc[fold.train_index])
            test_dates = set(dates.iloc[fold.test_index])
            self.assertFalse(train_dates & test_dates)
            self.assertLess(max(train_dates), min(test_dates))
            self.assertGreaterEqual((min(test_dates) - max(train_dates)).days, 10)

    def test_economic_metrics_charge_turnover_cost(self):
        rows = []
        for date in pd.date_range("2024-01-01", periods=5, freq="B"):
            rows.extend([
                {"date": date, "symbol": "A", "probability": 0.9, "future_return": 0.01},
                {"date": date, "symbol": "B", "probability": 0.1, "future_return": -0.01},
            ])
        result = economic_metrics(pd.DataFrame(rows), horizon=5, round_trip_cost_bps=20)
        self.assertGreater(result["rank_ic"], 0)
        self.assertLess(result["cost_adjusted_return"], result["top_quantile_return"])
        self.assertIn("annualized_sharpe", result)

    def test_three_way_split_keeps_sealed_dates_out_of_tuning(self):
        dates = pd.Series(np.repeat(pd.date_range("2018-01-01", periods=500, freq="B"), 4))
        split = three_way_research_split(
            dates, training_fraction=0.55, tuning_fraction=0.25,
            n_tuning_splits=3, purge_days=5, embargo_days=5,
        )
        sealed_dates = set(dates.iloc[split.sealed_index])
        self.assertEqual(len(split.tuning_folds), 3)
        self.assertTrue(sealed_dates)
        for fold in split.tuning_folds:
            self.assertFalse(sealed_dates & set(dates.iloc[fold.train_index]))
            self.assertFalse(sealed_dates & set(dates.iloc[fold.test_index]))
            self.assertLess(max(dates.iloc[fold.train_index]), min(dates.iloc[fold.test_index]))
        self.assertLess(pd.Timestamp(split.tuning_end), pd.Timestamp(split.sealed_start))

    def test_three_way_split_reserves_at_least_ten_percent(self):
        dates = pd.Series(pd.date_range("2020-01-01", periods=300, freq="B"))
        with self.assertRaises(ValueError):
            three_way_research_split(dates, training_fraction=0.7, tuning_fraction=0.25)


if __name__ == "__main__":
    unittest.main()
