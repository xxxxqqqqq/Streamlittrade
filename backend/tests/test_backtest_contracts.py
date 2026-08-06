"""回测请求契约和演示数据的单元测试。"""

import unittest
from datetime import date
from uuid import uuid4

from pydantic import ValidationError

from backend.app.schemas.backtest import BacktestCreate
from quant_core.demo_data import generate_demo_stock_data


class BacktestRequestTests(unittest.TestCase):
    def test_demo_source_normalizes_symbol(self):
        request = BacktestCreate(symbol="anything", data_source="demo")
        self.assertEqual(request.symbol, "DEMO")

    def test_baostock_requires_six_digit_symbol(self):
        with self.assertRaises(ValidationError):
            BacktestCreate(data_source="baostock", symbol="ABC")

    def test_versioned_backtest_requires_data_version(self):
        with self.assertRaises(ValidationError):
            BacktestCreate(data_source="data_version")

        version_id=uuid4()
        request=BacktestCreate(
            data_source="data_version",
            data_version_id=version_id,
            symbol="600000",
        )
        self.assertEqual(request.data_version_id,version_id)

    def test_unknown_strategy_parameter_is_rejected(self):
        with self.assertRaises(ValidationError):
            BacktestCreate(strategy_parameters={"future_leak": 1})

    def test_backtest_can_bind_an_immutable_strategy_version(self):
        strategy_id = uuid4()
        request = BacktestCreate(strategy_id=strategy_id)

        self.assertEqual(request.strategy_id, strategy_id)

    def test_model_oos_backtest_requires_model_and_normalizes_portfolio(self):
        with self.assertRaises(ValidationError):
            BacktestCreate(signal_source="model_oos")

        model_id = uuid4()
        request = BacktestCreate(
            signal_source="model_oos",
            model_id=model_id,
            run_type="single",
            data_source="demo",
            top_n=8,
            minimum_probability=0.57,
            rebalance_frequency=10,
        )

        self.assertEqual(request.model_id, model_id)
        self.assertEqual(request.run_type, "portfolio")
        self.assertEqual(request.data_source, "data_version")
        self.assertEqual(request.strategy_name, "model_probability")
        self.assertEqual(request.strategy_parameters["top_n"], 8)

    def test_invalid_moving_average_order_is_rejected(self):
        with self.assertRaises(ValidationError):
            BacktestCreate(
                strategy_parameters={"ma_short": 60, "ma_mid": 20, "ma_long": 5}
            )

    def test_execution_costs_are_explicit_and_lot_size_is_validated(self):
        request = BacktestCreate()
        self.assertEqual(request.lot_size, 100)
        self.assertEqual(request.commission, 0.0003)
        self.assertEqual(request.minimum_commission, 5.0)
        self.assertEqual(request.stamp_duty, 0.0005)
        self.assertEqual(request.slippage, 0.001)
        with self.assertRaises(ValidationError):
            BacktestCreate(lot_size=150)

    def test_demo_data_is_reproducible(self):
        first = generate_demo_stock_data(date(2020, 1, 1), date(2021, 1, 1))
        second = generate_demo_stock_data(date(2020, 1, 1), date(2021, 1, 1))
        self.assertTrue(first.equals(second))
        self.assertEqual(list(first.columns), ["open", "high", "low", "close", "volume"])


if __name__ == "__main__":
    unittest.main()
