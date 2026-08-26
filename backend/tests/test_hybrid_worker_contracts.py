"""Contracts for reversible queue routing and bounded factor materialization."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pandas as pd

from backend.app.infrastructure import queue as queue_module
from backend.app.workers.feature_materialization import (
    definition_fingerprint,
    materialize_partitioned_snapshot,
)
from backend.app.workers.local_artifacts import promote_cached_artifact
from backend.app.workers.research import _merge_snapshot_features_and_labels


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

    def test_generated_artifact_is_promoted_to_verified_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cache").mkdir()
            source = root / "staging.parquet"
            source.write_bytes(b"immutable-parquet-placeholder")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch(
                "backend.app.workers.local_artifacts.worker_data_root",
                return_value=root,
            ):
                cached = promote_cached_artifact(source, digest)
                self.assertEqual(cached, root / "cache" / f"{digest}.parquet")
                self.assertEqual(cached.read_bytes(), source.read_bytes())

    def test_dataset_merge_projects_approved_features_and_reports_milestones(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            feature_path, market_path = root / "features.parquet", root / "market.parquet"
            dates = pd.date_range("2025-01-01", periods=4)
            pd.DataFrame({
                "date": dates,
                "symbol": ["000001"] * 4,
                "factor_a": [1.0, 2.0, 3.0, 4.0],
                "unused_factor": [9.0] * 4,
                "universe_member": [True] * 4,
            }).to_parquet(feature_path, index=False)
            pd.DataFrame({
                "date": dates,
                "symbol": ["000001"] * 4,
                "close": [10.0, 11.0, 12.0, 13.0],
                "volume": [1000] * 4,
            }).to_parquet(market_path, index=False)
            progress = []
            read_parquet = pd.read_parquet

            with patch(
                "backend.app.workers.research.pd.read_parquet",
                side_effect=read_parquet,
            ) as reader:
                result, universe_applied = _merge_snapshot_features_and_labels(
                    feature_path, market_path, ["factor_a"], 1, progress.append
                )

            self.assertTrue(universe_applied)
            self.assertEqual(len(result), 3)
            self.assertNotIn("unused_factor", result.columns)
            self.assertNotIn("volume", result.columns)
            self.assertEqual(reader.call_args_list[0].kwargs["columns"], [
                "date", "symbol", "factor_a", "universe_member",
            ])
            self.assertEqual(
                reader.call_args_list[1].kwargs["columns"], ["date", "symbol", "close"]
            )
            self.assertEqual(progress, [34, 42, 48, 55, 62, 68])


if __name__ == "__main__":
    unittest.main()
