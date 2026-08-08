"""数据库模型中的项目隔离约束测试。"""

import unittest

from sqlalchemy import UniqueConstraint

from backend.app.models.paper import PaperAccount
from backend.app.models.research import Dataset, PredictionRun, SealedEvaluation, Strategy


class IsolationContractTests(unittest.TestCase):
    def test_paper_account_requires_project(self):
        column = PaperAccount.__table__.c.project_id

        self.assertFalse(column.nullable)
        self.assertEqual(
            {foreign_key.target_fullname for foreign_key in column.foreign_keys},
            {"projects.id"},
        )

    def test_strategy_version_is_unique_inside_project(self):
        unique_columns = {
            tuple(constraint.columns.keys())
            for constraint in Strategy.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }

        self.assertIn(("project_id", "slug", "version"), unique_columns)
        self.assertNotIn(("slug",), unique_columns)

    def test_prediction_run_requires_project_and_immutable_inputs(self):
        table = PredictionRun.__table__

        for name in ("project_id", "job_id", "model_id", "feature_snapshot_id"):
            self.assertFalse(table.c[name].nullable)

    def test_sealed_holdout_can_only_be_opened_once_per_dataset(self):
        table = SealedEvaluation.__table__
        unique_columns = {
            tuple(constraint.columns.keys())
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        self.assertIn(("dataset_id",), unique_columns)
        self.assertIn(("model_id",), unique_columns)
        for name in ("project_id", "dataset_id", "model_id", "job_id"):
            self.assertFalse(table.c[name].nullable)

    def test_dataset_gate_references_an_immutable_factor_research_run(self):
        column = Dataset.__table__.c.factor_research_id
        self.assertTrue(column.nullable)  # Legacy datasets remain readable.
        self.assertEqual(
            {foreign_key.target_fullname for foreign_key in column.foreign_keys},
            {"factor_research_runs.id"},
        )


if __name__ == "__main__":
    unittest.main()
