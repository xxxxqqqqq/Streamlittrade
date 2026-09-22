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


class ExecutableLabelTests(unittest.TestCase):
    """标签必须使用 T+1 可成交的开盘价口径，且为截面相对强弱。"""

    def _panel(self):
        rows = []
        # 每只股票 8 个交易日，open 与 close 故意拉开隔夜跳空；AAA 增速快于 BBB
        for symbol, base, growth in (("AAA", 100.0, 0.02), ("BBB", 50.0, 0.005)):
            for day in range(8):
                close = base * (1 + growth * day)
                rows.append({"date": pd.Timestamp("2024-01-01") + pd.Timedelta(days=day),
                             "symbol": symbol, "open": close * 1.02, "close": close})
        return pd.DataFrame(rows)

    def test_forward_return_starts_from_next_day_open(self):
        from quant_core.ml import attach_research_labels
        panel = attach_research_labels(self._panel(), horizon=2)
        first = panel[panel["symbol"] == "AAA"].sort_values("date").iloc[0]
        aaa = panel[panel["symbol"] == "AAA"].sort_values("date").reset_index(drop=True)
        expected = aaa["open"].iloc[3] / aaa["open"].iloc[1] - 1
        self.assertAlmostEqual(first["future_return"], expected, places=10)

    def test_label_is_cross_sectional_relative(self):
        from quant_core.ml import attach_research_labels
        panel = attach_research_labels(self._panel(), horizon=1)
        labeled = panel.dropna(subset=["label"])
        # 两只股票同涨时，每日恰有一只跑赢截面中位数
        per_date = labeled.groupby("date")["label"].mean()
        self.assertTrue(((per_date > 0) & (per_date < 1)).all())

    def test_close_fallback_when_open_missing(self):
        from quant_core.ml import attach_research_labels
        panel = self._panel().drop(columns=["open"])
        result = attach_research_labels(panel, horizon=2)
        aaa = result[result["symbol"] == "AAA"].sort_values("date").reset_index(drop=True)
        self.assertAlmostEqual(aaa["future_return"].iloc[0], aaa["close"].iloc[2] / aaa["close"].iloc[0] - 1, places=10)


import pandas as pd
