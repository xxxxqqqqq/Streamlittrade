"""Contracts that keep catalog inputs bounded and feature execution allow-listed."""

import unittest
from datetime import date

import pandas as pd
from pydantic import ValidationError

from backend.app.schemas.data_catalog import FeatureCreate, SyncCreate
from backend.app.services.factors import compute_factor, evaluate_expression, factor_library_payload


class DataCatalogContractTests(unittest.TestCase):
    def test_sync_rejects_reversed_dates(self):
        with self.assertRaises(ValidationError):
            SyncCreate(
                source_id="00000000-0000-0000-0000-000000000001",
                symbols=["600000"],
                start_date=date(2024, 1, 2),
                end_date=date(2024, 1, 1),
            )

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
        self.assertGreaterEqual(len(library), 12)
        self.assertIn("momentum", {item["family"] for item in library})
        self.assertIn("liquidity", {item["family"] for item in library})
        self.assertIn("risk", {item["family"] for item in library})

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


if __name__ == "__main__":
    unittest.main()
