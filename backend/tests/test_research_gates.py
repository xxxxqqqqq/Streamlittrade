"""Factor-to-dataset gate contracts."""

import unittest
from uuid import uuid4

import pandas as pd

from backend.app.schemas.data_catalog import FactorResearchCreate
from backend.app.services.research_gates import factor_gate_snapshot, factor_training_dates, validate_factor_dataset_gate


def valid_gate(**overrides):
    snapshot_id = overrides.pop("snapshot_id", uuid4())
    values = {
        "snapshot_id": snapshot_id,
        "horizon": 5,
        "training_fraction": .55,
        "run_snapshot_id": snapshot_id,
        "run_status": "succeeded",
        "run_parameters": {"forward_period": 5, "training_fraction": .55},
        "run_metrics": {
            "evaluation_scope": "factor_training_only",
            "screening": {"selected": ["value", "quality"]},
            "factors": {"value": {"passed": True}, "quality": {"passed": True}},
        },
        "selected_feature_slugs": ["value", "quality"],
    }
    values.update(overrides)
    return values


class ResearchGateTests(unittest.TestCase):
    def test_factor_research_only_reads_the_training_region(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        research_dates, untouched_start = factor_training_dates(dates, .55, 5)

        self.assertEqual(len(research_dates), 50)
        self.assertEqual(pd.Timestamp(untouched_start), dates[55])
        self.assertLess(pd.Timestamp(research_dates[-1]), pd.Timestamp(untouched_start))
        request = FactorResearchCreate(name="training only", snapshot_id=uuid4())
        self.assertEqual(request.training_fraction, .55)

    def test_only_passed_features_enter_the_dataset(self):
        self.assertEqual(validate_factor_dataset_gate(**valid_gate()), ["value", "quality"])

    def test_gate_rejects_snapshot_and_horizon_mismatches(self):
        with self.assertRaisesRegex(ValueError, "快照不匹配"):
            validate_factor_dataset_gate(**valid_gate(run_snapshot_id=uuid4()))
        with self.assertRaisesRegex(ValueError, "预测周期"):
            validate_factor_dataset_gate(**valid_gate(horizon=20))
        with self.assertRaisesRegex(ValueError, "训练区比例"):
            validate_factor_dataset_gate(**valid_gate(training_fraction=.6))

    def test_gate_rejects_empty_or_inconsistent_approval(self):
        with self.assertRaisesRegex(ValueError, "没有任何通过"):
            validate_factor_dataset_gate(**valid_gate(selected_feature_slugs=[]))
        with self.assertRaisesRegex(ValueError, "审查指标不一致"):
            validate_factor_dataset_gate(**valid_gate(selected_feature_slugs=["value"]))

    def test_legacy_full_sample_research_cannot_open_the_gate(self):
        with self.assertRaisesRegex(ValueError, "调参区或封存区"):
            validate_factor_dataset_gate(**valid_gate(run_metrics={
                "screening": {"selected": ["value", "quality"]},
                "factors": {"value": {"passed": True}, "quality": {"passed": True}},
            }))

    def test_gate_audit_hash_is_deterministic(self):
        run_id, snapshot_id = uuid4(), uuid4()
        kwargs = {
            "run_id": run_id,
            "snapshot_id": snapshot_id,
            "parameters": {"forward_period": 5},
            "metrics": {"screening": {"selected": ["value"]}},
            "selected": ["value"],
        }
        first = factor_gate_snapshot(**kwargs)
        second = factor_gate_snapshot(**kwargs)
        self.assertEqual(first["content_sha256"], second["content_sha256"])
        self.assertEqual(len(first["content_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
