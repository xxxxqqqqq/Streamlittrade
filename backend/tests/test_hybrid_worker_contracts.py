"""Contracts for reversible queue routing and bounded factor materialization."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd

from backend.app.infrastructure import queue as queue_module
from backend.app.workers.feature_materialization import (
    definition_fingerprint,
    materialize_partitioned_snapshot,
)


class HybridQueueRoutingTests(unittest.TestCase):
    def test_legacy_mode_keeps_every_task_on_original_queue(self):
        original = queue_module.settings.queue_mode
        try:
            queue_module.settings.queue_mode = "legacy"
            self.assertEqual(
                queue_module.queue_name_for_task(
                    "backend.app.workers.data_catalog.materialize_features"
                ),
                queue_module.settings.legacy_queue_name,
            )
        finally:
            queue_module.settings.queue_mode = original

    def test_split_mode_routes_factor_materialization_to_heavy_queue(self):
        original = queue_module.settings.queue_mode
        try:
            queue_module.settings.queue_mode = "split"
            self.assertEqual(
                queue_module.queue_name_for_task(
                    "backend.app.workers.data_catalog.materialize_features"
                ),
                queue_module.settings.heavy_queue_name,
            )
            self.assertEqual(
                queue_module.queue_name_for_task(
                    "backend.app.workers.automation.run_paper_automation"
                ),
                queue_module.settings.light_queue_name,
            )
        finally:
            queue_module.settings.queue_mode = original


class PartitionedMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.definitions = [
            SimpleNamespace(
                id=uuid4(), slug="return_1d", version=1,
                implementation="return", parameters={"window": 1},
            ),
            SimpleNamespace(
                id=uuid4(), slug="volatility_3d", version=1,
                implementation="volatility", parameters={"window": 3},
            ),
        ]
        rows = []
        for symbol, offset in (("000001", 0), ("000002", 10)):
            for index, date in enumerate(pd.date_range("2024-01-01", periods=8)):
                close = 10 + offset + index
                rows.append(
                    {
                        "date": date,
                        "symbol": symbol,
                        "open": close - 0.2,
                        "high": close + 0.3,
                        "low": close - 0.4,
                        "close": close,
                        "volume": 1000 + index,
                        "universe_member": True,
                        "universe_rank": index + 1,
                    }
                )
        self.frame = pd.DataFrame(rows)

    def test_partitioned_output_matches_group_factor_values_and_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.parquet", root / "output.parquet"
            checkpoint = root / "checkpoint"
            checkpoint.mkdir()
            self.frame.to_parquet(source, index=False)
            fingerprint = definition_fingerprint("a" * 64, self.definitions)
            progress = []

            first = materialize_partitioned_snapshot(
                source, output, checkpoint, self.definitions, fingerprint, {}, progress.append
            )
            actual = pd.read_parquet(output).sort_values(["symbol", "date"]).reset_index(drop=True)

            self.assertEqual(first.row_count, len(self.frame))
            self.assertEqual(first.computed_partitions, 2)
            self.assertEqual(first.resumed_partitions, 0)
            self.assertEqual(list(actual.columns)[-2:], ["return_1d", "volatility_3d"])
            for symbol, group in actual.groupby("symbol"):
                source_group = self.frame.loc[self.frame["symbol"] == symbol].sort_values("date")
                expected_return = source_group["close"].pct_change(1)
                pd.testing.assert_series_equal(
                    group["return_1d"].reset_index(drop=True),
                    expected_return.astype("float32").reset_index(drop=True),
                    check_names=False,
                )
            self.assertTrue(progress)
            self.assertEqual(first.profile["materialization"]["partitions"], 2)

            second_output = root / "output-second.parquet"
            second = materialize_partitioned_snapshot(
                source, second_output, checkpoint, self.definitions, fingerprint, {}
            )
            self.assertEqual(second.resumed_partitions, 2)
            self.assertEqual(second.computed_partitions, 0)
            pd.testing.assert_frame_equal(
                pd.read_parquet(output), pd.read_parquet(second_output)
            )

    def test_interrupted_run_resumes_completed_symbol_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source.parquet", root / "output.parquet"
            checkpoint = root / "checkpoint"
            checkpoint.mkdir()
            self.frame.to_parquet(source, index=False)
            fingerprint = definition_fingerprint("b" * 64, self.definitions)

            def interrupt_after_first(_progress):
                raise RuntimeError("simulated disconnect")

            with self.assertRaisesRegex(RuntimeError, "simulated disconnect"):
                materialize_partitioned_snapshot(
                    source, output, checkpoint, self.definitions, fingerprint, {},
                    interrupt_after_first,
                )

            resumed = materialize_partitioned_snapshot(
                source, output, checkpoint, self.definitions, fingerprint, {}
            )
            self.assertEqual(resumed.resumed_partitions, 1)
            self.assertEqual(resumed.computed_partitions, 1)
            self.assertEqual(resumed.row_count, len(self.frame))


if __name__ == "__main__":
    unittest.main()
