"""Model-to-paper policy and persistence contracts."""

import unittest
from datetime import date

from backend.app.models.operations import PaperAutomationRun, PaperAutomationSchedule
from backend.app.services.paper_automation import build_target_portfolio, next_business_day, snapshot_supports_features


class PaperAutomationTests(unittest.TestCase):
    def test_snapshot_requires_every_model_feature(self):
        lineage = {"definitions": [{"slug": "quality_roe"}, {"slug": "return_20d"}]}
        self.assertTrue(snapshot_supports_features(lineage, ["return_20d", "quality_roe"]))
        self.assertFalse(snapshot_supports_features(lineage, ["return_20d", "missing_factor"]))

    def test_target_portfolio_is_ranked_capped_and_board_lotted(self):
        targets = build_target_portfolio(
            [{"symbol": "000001", "probability": 0.70}, {"symbol": "000002", "probability": 0.60}, {"symbol": "000003", "probability": 0.51}],
            {"000001": 10.0, "000002": 20.0, "000003": 5.0},
            100_000,
            threshold=0.55, top_n=2, gross_exposure=0.95, max_position_ratio=0.30,
        )
        self.assertEqual([item["symbol"] for item in targets], ["000001", "000002"])
        self.assertTrue(all(item["target_quantity"] % 100 == 0 for item in targets))
        self.assertTrue(all(item["target_weight"] <= 0.30 for item in targets))

    def test_signal_and_intended_trade_dates_are_separate(self):
        self.assertEqual(next_business_day(date(2026, 8, 7)), date(2026, 8, 10))

    def test_tables_are_project_scoped_and_idempotent(self):
        self.assertFalse(PaperAutomationSchedule.__table__.c.project_id.nullable)
        self.assertFalse(PaperAutomationRun.__table__.c.project_id.nullable)
        constraints = {item.name for item in PaperAutomationRun.__table__.constraints}
        self.assertIn("uq_paper_automation_schedule_snapshot", constraints)


if __name__ == "__main__":
    unittest.main()
