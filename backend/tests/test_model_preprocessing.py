"""Point-in-time model preprocessing contracts."""

import unittest

import pandas as pd

from quant_core.ml import cross_sectional_rank_features


class ModelPreprocessingTests(unittest.TestCase):
    def test_daily_rank_is_cross_sectional_and_cannot_see_future_dates(self):
        frame = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-02"] * 3 + ["2024-01-03"] * 3),
            "factor": [1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
        })
        baseline = cross_sectional_rank_features(frame, ["factor"])
        changed = frame.copy()
        changed.loc[changed["date"] == pd.Timestamp("2024-01-03"), "factor"] *= 1000
        revised = cross_sectional_rank_features(changed, ["factor"])

        pd.testing.assert_series_equal(baseline.iloc[:3, 0], revised.iloc[:3, 0])
        self.assertAlmostEqual(float(baseline.iloc[0, 0]), -1 / 3)
        self.assertAlmostEqual(float(baseline.iloc[2, 0]), 1.0)


if __name__ == "__main__":
    unittest.main()
