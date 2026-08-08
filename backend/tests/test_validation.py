"""Calibration and multiple-testing primitives."""

import unittest

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from quant_core.validation import benjamini_hochberg, fit_time_ordered_sigmoid, mean_significance, probability_diagnostics


class ValidationTests(unittest.TestCase):
    def test_daily_ic_significance_uses_a_two_sided_t_test(self):
        significant = mean_significance([.03, .04, .02, .05, .01] * 10)
        centered = mean_significance([-.02, .02, -.01, .01] * 10)
        self.assertLess(significant["p_value"], .01)
        self.assertGreater(centered["p_value"], .5)

    def test_benjamini_hochberg_is_monotone_and_penalizes_many_trials(self):
        adjusted = benjamini_hochberg({"a": .001, "b": .02, "c": .04, "missing": None})
        self.assertEqual(adjusted["a"], .003)
        self.assertGreaterEqual(adjusted["b"], .02)
        self.assertGreaterEqual(adjusted["c"], adjusted["b"])
        self.assertIsNone(adjusted["missing"])

    def test_probability_diagnostics_report_proper_scores_and_reliability_bins(self):
        result = probability_diagnostics([0, 0, 1, 1], [.1, .3, .7, .9], raw_probability=[.2, .4, .6, .8])
        self.assertLess(result["brier_score"], result["raw_brier_score"])
        self.assertGreater(len(result["bins"]), 0)
        self.assertIn("expected_calibration_error", result)

    def test_sigmoid_calibration_uses_time_ordered_slice_and_returns_probabilities(self):
        rows = 240
        dates = pd.date_range("2020-01-01", periods=120, freq="D").repeat(2)
        feature = np.sin(np.arange(rows) / 5)
        frame = pd.DataFrame({"x": feature})
        labels = (feature + np.sin(np.arange(rows)) * .2 > 0).astype(int)
        estimator = fit_time_ordered_sigmoid(
            lambda: LogisticRegression(max_iter=500, random_state=42), frame, labels, dates, purge_days=2
        )
        probabilities = estimator.predict_proba(frame)
        self.assertEqual(probabilities.shape, (rows, 2))
        self.assertTrue(np.allclose(probabilities.sum(axis=1), 1))


if __name__ == "__main__":
    unittest.main()
