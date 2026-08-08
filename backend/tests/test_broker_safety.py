"""Safety gates prove that broker submission remains impossible by default."""

import unittest
from uuid import uuid4

from pydantic import ValidationError

from backend.app.models.broker import BrokerConnection, LiveReadinessEvaluation
from backend.app.schemas.broker import BrokerConnectionCreate
from backend.app.services.broker_safety import LiveTradingDisabled, broker_adapter, evaluate_paper_stability


class BrokerSafetyTests(unittest.TestCase):
    def stable_stats(self):
        return {"successful_runs": 20, "observation_days": 30, "success_rate": 0.95, "unreviewed_proposals": 0, "open_critical_alerts": 0, "production_model_reliable": True, "credential_reference_valid": True, "dry_run_only": True}

    def test_every_requirement_must_pass(self):
        self.assertTrue(evaluate_paper_stability(self.stable_stats())["eligible"])
        for field in self.stable_stats():
            stats = self.stable_stats()
            stats[field] = False if isinstance(stats[field], bool) else -1
            self.assertFalse(evaluate_paper_stability(stats)["eligible"], field)

    def test_credentials_are_references_not_values(self):
        valid = BrokerConnectionCreate(name="sandbox", paper_account_id=uuid4(), provider="generic", credential_secret_ref="env:QUANT_BROKER_GENERIC_TOKEN")
        self.assertTrue(valid.credential_secret_ref.startswith("env:"))
        with self.assertRaises(ValidationError):
            BrokerConnectionCreate(name="sandbox", paper_account_id=uuid4(), provider="generic", credential_secret_ref="actual-secret-value")

    def test_adapter_can_preview_but_never_submit(self):
        adapter = broker_adapter("generic")
        preview = adapter.preview([{"symbol": "000001", "quantity": 100}])
        self.assertFalse(preview[0]["transmitted"])
        with self.assertRaises(LiveTradingDisabled):
            adapter.submit(preview)

    def test_broker_tables_are_project_scoped(self):
        self.assertFalse(BrokerConnection.__table__.c.project_id.nullable)
        self.assertFalse(LiveReadinessEvaluation.__table__.c.project_id.nullable)


if __name__ == "__main__":
    unittest.main()
