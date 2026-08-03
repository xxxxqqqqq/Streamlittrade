import unittest

import numpy as np
import pandas as pd

from quant_core.ml import economic_metrics, purged_walk_forward_splits


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


if __name__ == "__main__":
    unittest.main()
