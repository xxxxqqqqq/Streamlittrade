"""Contracts that keep catalog inputs bounded and feature execution allow-listed."""

import unittest
from datetime import date
from types import SimpleNamespace

import pandas as pd
import numpy as np
from pydantic import ValidationError

from backend.app.schemas.data_catalog import FeatureCreate, SyncCreate
from backend.app.services.factors import compute_factor, evaluate_expression, factor_library_payload
from backend.app.workers.data_catalog import _compute_feature_column


class DataCatalogContractTests(unittest.TestCase):
    def test_sync_rejects_reversed_dates(self):
        with self.assertRaises(ValidationError):
            SyncCreate(
                source_id="00000000-0000-0000-0000-000000000001",
                symbols=["600000"],
                start_date=date(2024, 1, 2),
                end_date=date(2024, 1, 1),
            )

    def test_sync_has_a_short_version_name(self):
        request = SyncCreate(
            name="主板蓝筹研究数据",
            source_id="00000000-0000-0000-0000-000000000001",
            symbols=["600000"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 1),
        )
        self.assertEqual(request.name, "主板蓝筹研究数据")

    def test_feature_implementation_is_allow_listed(self):
        with self.assertRaises(ValidationError):
            FeatureCreate(
                name="unsafe feature",
                slug="unsafe",
                implementation="arbitrary_python",
            )

    def test_registered_feature_accepts_versionable_parameters(self):
        item = FeatureCreate(
            name="20-day return",
            slug="return_20d",
            implementation="return",
            parameters={"window": 20},
        )
        self.assertEqual(item.parameters["window"], 20)

    def test_factor_library_exposes_multiple_families(self):
        library = factor_library_payload()
        self.assertEqual(len(library), 1000)
        self.assertEqual(len({item["slug"] for item in library}), 1000)
        self.assertIn("momentum", {item["family"] for item in library})
        self.assertIn("liquidity", {item["family"] for item in library})
        self.assertIn("risk", {item["family"] for item in library})
        self.assertIn("candlestick", {item["family"] for item in library})

    def test_sync_accepts_a_two_hundred_symbol_research_universe(self):
        request = SyncCreate(
            name="沪深300历史成分200股研究行情",
            source_id="00000000-0000-0000-0000-000000000001",
            symbols=[f"{index:06d}" for index in range(200)],
            start_date=date(2020, 1, 1),
            end_date=date(2024, 1, 1),
        )
        self.assertEqual(len(request.symbols), 200)

    def test_immutable_asset_name_rejects_encoding_loss_markers(self):
        with self.assertRaises(ValidationError):
            SyncCreate(
                name="20日????研究数据",
                source_id="00000000-0000-0000-0000-000000000001",
                symbols=["600000"],
                start_date=date(2020, 1, 1),
                end_date=date(2024, 1, 1),
            )

    def test_expression_rejects_arbitrary_python(self):
        with self.assertRaises(ValidationError):
            FeatureCreate(
                name="unsafe expression",
                slug="unsafe_expression",
                implementation="expression",
                parameters={"expression": "__import__('os').system('whoami')"},
            )

    def test_expression_factor_uses_approved_rolling_operators(self):
        frame = pd.DataFrame(
            {
                "open": [10, 11, 12, 13],
                "high": [11, 12, 13, 14],
                "low": [9, 10, 11, 12],
                "close": [10, 11, 13, 12],
                "volume": [100, 120, 90, 150],
            }
        )
        result = evaluate_expression(frame, "close / mean(close, 2) - 1")
        self.assertAlmostEqual(result.iloc[-1], 12 / 12.5 - 1)

    def test_new_builtin_factor_computes_price_position(self):
        frame = pd.DataFrame(
            {
                "open": [10, 11, 12],
                "high": [11, 13, 14],
                "low": [9, 10, 11],
                "close": [10, 12, 13],
                "volume": [100, 120, 90],
            }
        )
        result = compute_factor(frame, "price_position", {"window": 3})
        self.assertAlmostEqual(result.iloc[-1], (13 - 9) / (14 - 9))

    def test_advanced_factor_variants_are_past_only(self):
        length = 50
        frame = pd.DataFrame({
            "open": np.linspace(10, 15, length), "high": np.linspace(11, 16, length),
            "low": np.linspace(9, 14, length), "close": np.linspace(10.2, 15.2, length),
            "volume": np.linspace(1000, 3000, length),
        })
        revised = frame.copy()
        revised.loc[length - 1, ["close", "volume"]] = [99, 999999]
        for implementation in (
            "price_efficiency", "return_kurtosis", "up_day_ratio", "max_daily_return",
            "min_daily_return", "volume_volatility", "volume_momentum", "upper_shadow",
        ):
            baseline = compute_factor(frame, implementation, {"window": 10})
            changed = compute_factor(revised, implementation, {"window": 10})
            pd.testing.assert_series_equal(baseline.iloc[:-1], changed.iloc[:-1])

    def test_materialized_factor_is_one_column_for_multiple_symbols(self):
        """A multi-symbol return factor must remain assignable to one column."""

        frame = pd.DataFrame(
            {
                "symbol": ["000001", "000001", "000002", "000002"],
                "date": pd.to_datetime(["2024-01-01", "2024-01-02"] * 2),
                "open": [10, 11, 20, 22],
                "high": [11, 12, 21, 23],
                "low": [9, 10, 19, 21],
                "close": [10, 11, 20, 22],
                "volume": [100, 110, 200, 220],
            }
        )
        definition = SimpleNamespace(slug="return_20d", implementation="return", parameters={"window": 1})

        column = _compute_feature_column(frame, definition)

        self.assertIsInstance(column, pd.Series)
        frame[definition.slug] = column
        self.assertAlmostEqual(frame.loc[1, definition.slug], 0.1)
        self.assertAlmostEqual(frame.loc[3, definition.slug], 0.1)

    def test_materialized_factor_replaces_infinity_with_missing_value(self):
        frame = pd.DataFrame(
            {
                "symbol": ["000001"] * 3,
                "date": pd.date_range("2024-01-01", periods=3),
                "open": [10, 10, 10], "high": [10, 10, 10],
                "low": [10, 10, 10], "close": [10, 10, 10],
                "volume": [0, 0, 100],
            }
        )
        definition = SimpleNamespace(slug="unsafe", implementation="volume_ratio", parameters={"window": 2})

        column = _compute_feature_column(frame, definition)

        self.assertFalse(np.isinf(column).any())


if __name__ == "__main__":
    unittest.main()
