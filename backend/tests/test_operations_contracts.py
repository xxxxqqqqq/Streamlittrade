"""Production scheduling, drift, and alert contract tests."""

import unittest
from uuid import uuid4

import pandas as pd
from pydantic import ValidationError

from backend.app.models.operations import AlertEvent, DriftRun, PredictionSchedule
from backend.app.schemas.operations import AlertUpdate, ScheduleCreate
from quant_core.monitoring import population_stability_index


class OperationsContractTests(unittest.TestCase):
    def test_schedule_requires_safe_interval_and_reviewed_algorithm(self):
        request = ScheduleCreate(
            name="daily score",
            algorithm="random_forest",
            feature_snapshot_id=uuid4(),
            interval_minutes=1440,
        )

        self.assertEqual(request.interval_minutes, 1440)
        with self.assertRaises(ValidationError):
            ScheduleCreate(
                name="too frequent",
                algorithm="random_forest",
                feature_snapshot_id=uuid4(),
                interval_minutes=1,
            )

    def test_operations_tables_require_project_scope(self):
        for model in (PredictionSchedule, DriftRun, AlertEvent):
            self.assertFalse(model.__table__.c.project_id.nullable)

    def test_alert_lifecycle_only_accepts_auditable_terminal_states(self):
        self.assertEqual(AlertUpdate(status="acknowledged").status, "acknowledged")
        self.assertEqual(AlertUpdate(status="resolved").status, "resolved")
        with self.assertRaises(ValidationError):
            AlertUpdate(status="ignored")

    def test_psi_detects_material_distribution_shift(self):
        reference = pd.Series(range(1, 1001))
        unchanged = pd.Series(range(1, 1001))
        shifted = pd.Series(range(1001, 2001))

        self.assertLess(population_stability_index(reference, unchanged), 0.01)
        self.assertGreater(population_stability_index(reference, shifted), 0.25)


if __name__ == "__main__":
    unittest.main()
