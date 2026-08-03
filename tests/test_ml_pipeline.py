"""机器学习特征与标签构建测试。"""

import unittest
from datetime import date

from quant_core.demo_data import generate_demo_stock_data
from quant_core.ml import FEATURES, build_training_frame


class MachineLearningPipelineTests(unittest.TestCase):
    def test_training_frame_contains_declared_features_and_binary_label(self):
        prices = generate_demo_stock_data(date(2020, 1, 1), date(2022, 1, 1))
        frame = build_training_frame(prices, symbol="DEMO1", horizon=5)

        self.assertFalse(frame.empty)
        self.assertTrue(set(FEATURES).issubset(frame.columns))
        self.assertEqual(set(frame["label"].unique()).difference({0, 1}), set())
        self.assertEqual(frame[FEATURES].isna().sum().sum(), 0)

    def test_last_horizon_rows_are_excluded_because_future_is_unknown(self):
        horizon = 7
        prices = generate_demo_stock_data(date(2020, 1, 1), date(2022, 1, 1))
        frame = build_training_frame(prices, symbol="DEMO1", horizon=horizon)

        self.assertLessEqual(frame["date"].max(), prices.index[-horizon - 1])


if __name__ == "__main__":
    unittest.main()
