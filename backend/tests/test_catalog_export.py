"""Contracts for spreadsheet-friendly immutable data version exports."""

import unittest

import pandas as pd

from backend.app.services.catalog_export import version_frame_to_csv


class CatalogExportTests(unittest.TestCase):
    def test_export_has_excel_encoding_canonical_columns_and_all_rows(self):
        frame = pd.DataFrame({
            "close": [11.0, 10.0], "symbol": ["000002", "000001"],
            "date": pd.to_datetime(["2024-01-02", "2024-01-01"]),
            "volume": [200, 100], "open": [10.5, 9.5], "high": [11.5, 10.5],
            "low": [10.0, 9.0], "universe_member": [True, False],
        })

        content = version_frame_to_csv(frame)
        decoded = content.decode("utf-8-sig").splitlines()

        self.assertEqual(decoded[0].split(",")[:8], [
            "date", "symbol", "open", "high", "low", "close", "volume", "universe_member",
        ])
        self.assertEqual(len(decoded), 3)
        self.assertTrue(decoded[1].startswith("2024-01-01,000001"))


if __name__ == "__main__":
    unittest.main()
