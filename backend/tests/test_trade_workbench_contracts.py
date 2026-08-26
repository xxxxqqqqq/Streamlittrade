import unittest
import shutil
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from pydantic import ValidationError

from backend.app.schemas.trade_workbench import SnapshotBacktestCreate
from backend.app.services.trade_workbench import factor_rows, market_rows, read_parquet


class TradeWorkbenchContractTests(unittest.TestCase):
    def test_snapshot_backtest_has_explicit_execution_defaults(self):
        request = SnapshotBacktestCreate()
        self.assertEqual(request.top_n, 5)
        self.assertEqual(request.lot_size, 100)
        self.assertEqual(request.commission, 0.0003)

    def test_snapshot_backtest_rejects_invalid_window_and_board_lot(self):
        with self.assertRaises(ValidationError):
            SnapshotBacktestCreate(
                start_date=date(2024, 2, 1), end_date=date(2024, 1, 1)
            )
        with self.assertRaises(ValidationError):
            SnapshotBacktestCreate(lot_size=250)

    def test_parquet_reader_projects_columns_and_filters_before_dataframe_load(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.parquet"
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2025-01-02", "2025-01-02"]),
                    "symbol": ["000001", "000002"],
                    "factor_a": [1.0, 2.0],
                    "unused_factor": [3.0, 4.0],
                }
            ).to_parquet(source, index=False)

            def copy_artifact(_uri, destination):
                shutil.copyfile(source, destination)
                return Path(destination)

            with patch(
                "backend.app.services.trade_workbench.download_file",
                side_effect=copy_artifact,
            ):
                frame = read_parquet(
                    "s3://quant-artifacts/test.parquet",
                    columns=["date", "symbol", "factor_a"],
                    filters=[("symbol", "==", "000002")],
                )

        self.assertEqual(frame.columns.tolist(), ["date", "symbol", "factor_a"])
        self.assertEqual(frame["symbol"].tolist(), ["000002"])

    def test_timeline_reads_only_registered_model_features_for_one_symbol(self):
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2025-01-02", "2025-01-03"]),
                "symbol": ["000002", "000002"],
                "factor_a": [1.0, 2.0],
            }
        )
        chain = SimpleNamespace(
            dataset=SimpleNamespace(metadata_snapshot={"features": ["factor_a"]}),
            snapshot=SimpleNamespace(artifact_uri="s3://quant-artifacts/features.parquet"),
        )
        with patch(
            "backend.app.services.trade_workbench.read_parquet",
            return_value=frame,
        ) as reader:
            rows = factor_rows(chain, "000002", "2025-01-02", "2025-01-03")

        reader.assert_called_once_with(
            chain.snapshot.artifact_uri,
            columns=["date", "symbol", "factor_a"],
            filters=[("symbol", "==", "000002")],
        )
        self.assertEqual(set(rows[0]), {"date", "factor_a"})

    def test_market_timeline_tolerates_optional_columns_missing_from_artifact(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "market.parquet"
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2025-01-02", "2025-01-02"]),
                    "symbol": ["000001", "000002"],
                    "open": [10.0, 20.0], "high": [11.0, 21.0],
                    "low": [9.0, 19.0], "close": [10.5, 20.5],
                    "volume": [1000, 2000],
                }
            ).to_parquet(source, index=False)

            def copy_artifact(_uri, destination):
                shutil.copyfile(source, destination)
                return Path(destination)

            chain = SimpleNamespace(
                version=SimpleNamespace(artifact_uri="s3://quant-artifacts/market.parquet")
            )
            with patch(
                "backend.app.services.trade_workbench.download_file",
                side_effect=copy_artifact,
            ):
                rows = market_rows(chain, "000002", "2025-01-01", "2025-01-03")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["close"], 20.5)
        self.assertNotIn("amount", rows[0])


if __name__ == "__main__":
    unittest.main()
