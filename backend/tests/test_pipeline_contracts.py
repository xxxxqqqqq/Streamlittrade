"""一键研究流水线的输入契约与编排状态机测试。"""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from pydantic import ValidationError

from backend.app.models.backtest import BacktestRun
from backend.app.models.data_catalog import FactorResearchRun, FeatureSnapshot
from backend.app.models.job import Job
from backend.app.models.research import Experiment
from backend.app.schemas.research import QuickResearchCreate
from backend.app.services.pipeline import (
    PIPELINE_STEPS,
    advance_pipeline_record,
    build_pipeline_spec,
)


def _inputs(**overrides):
    values = {
        "horizon": 20,
        "training_fraction": 0.55,
        "algorithm": "hist_gradient_boosting",
        "algorithm_parameters": {},
        "top_n": 5,
        "minimum_probability": 0.55,
        "rebalance_frequency": 5,
        "initial_cash": 1_000_000,
        "data_version_id": str(uuid4()),
    }
    values.update(overrides)
    return values


def _pipeline(step: str, spec: dict | None = None):
    return SimpleNamespace(
        id=uuid4(),
        project_id=uuid4(),
        owner_id=uuid4(),
        name="快速研究",
        status="running",
        current_step=step,
        current_job_id=uuid4(),
        error_message=None,
        completed_at=None,
        spec=spec or build_pipeline_spec(_inputs(), step),
    )


def _job(status: str):
    return SimpleNamespace(status=status, error_message="boom" if status == "failed" else None)


class QuickResearchContractTests(unittest.TestCase):
    """进入编排前，请求必须且只能选择一个不可变数据来源。"""

    def test_requires_exactly_one_source(self):
        with self.assertRaises(ValidationError):
            QuickResearchCreate(name="快速研究")
        with self.assertRaises(ValidationError):
            QuickResearchCreate(name="快速研究", data_version_id=uuid4(), feature_snapshot_id=uuid4())

    def test_recommended_defaults_cover_the_whole_chain(self):
        request = QuickResearchCreate(name="快速研究", data_version_id=uuid4())

        self.assertEqual(request.horizon, 20)
        self.assertEqual(request.algorithm, "hist_gradient_boosting")
        self.assertEqual(request.top_n, 5)
        self.assertEqual(request.minimum_probability, 0.55)
        self.assertEqual(request.initial_cash, 1_000_000)


class PipelineSpecTests(unittest.TestCase):
    def test_steps_before_the_first_one_are_marked_skipped(self):
        spec = build_pipeline_spec(_inputs(), "factor_research")

        self.assertEqual(spec["steps"]["materialize"]["status"], "skipped")
        self.assertEqual(spec["steps"]["factor_research"]["status"], "pending")
        self.assertEqual(set(spec["steps"].keys()), set(PIPELINE_STEPS))


class AdvancePipelineTests(unittest.TestCase):
    def _session(self, job):
        session = MagicMock()
        session.get.return_value = job
        return session

    def test_running_job_leaves_pipeline_untouched(self):
        pipeline = _pipeline("materialize")

        self.assertFalse(advance_pipeline_record(self._session(_job("running")), pipeline))
        self.assertEqual(pipeline.status, "running")
        self.assertEqual(pipeline.current_step, "materialize")

    def test_failed_step_fails_the_whole_pipeline(self):
        pipeline = _pipeline("dataset")

        self.assertTrue(advance_pipeline_record(self._session(_job("failed")), pipeline))
        self.assertEqual(pipeline.status, "failed")
        self.assertIn("研究数据集", pipeline.error_message)
        self.assertEqual(pipeline.spec["steps"]["dataset"]["status"], "failed")
        self.assertIsNotNone(pipeline.completed_at)

    def test_missing_job_fails_pipeline(self):
        pipeline = _pipeline("training")

        self.assertTrue(advance_pipeline_record(self._session(None), pipeline))
        self.assertEqual(pipeline.status, "failed")

    def test_materialize_success_enqueues_factor_research(self):
        pipeline = _pipeline("materialize")
        pipeline.spec["steps"]["materialize"]["resource_id"] = str(uuid4())
        session = self._session(_job("succeeded"))

        self.assertTrue(advance_pipeline_record(session, pipeline))
        self.assertEqual(pipeline.current_step, "factor_research")
        self.assertEqual(pipeline.spec["steps"]["materialize"]["status"], "succeeded")
        self.assertEqual(pipeline.spec["steps"]["factor_research"]["status"], "queued")
        added_types = {type(call.args[0]) for call in session.add.call_args_list}
        self.assertIn(Job, added_types)
        self.assertIn(FactorResearchRun, added_types)

    def test_factor_research_without_approved_factors_fails_pipeline(self):
        run = SimpleNamespace(
            id=uuid4(), snapshot_id=uuid4(), status="succeeded",
            parameters={"forward_period": 20, "training_fraction": 0.55},
            metrics={"evaluation_scope": "factor_training_only"},
            selected_feature_slugs=[],
        )
        session = MagicMock()
        session.get.side_effect = lambda cls, _id: _job("succeeded") if cls is Job else run
        pipeline = _pipeline("factor_research")
        pipeline.spec["steps"]["factor_research"]["resource_id"] = str(run.id)

        self.assertTrue(advance_pipeline_record(session, pipeline))
        self.assertEqual(pipeline.status, "failed")
        self.assertIn("无法继续", pipeline.error_message)

    def test_training_success_enqueues_tuning_oos_backtest(self):
        experiment_id = uuid4()
        model = SimpleNamespace(
            id=uuid4(), prediction_artifact_uri="s3://predictions.parquet",
            metrics={
                "evaluation_scope": "tuning_oos",
                "research_split": {"tuning": {"start": "2022-09-26", "end": "2024-06-11"}},
            },
        )
        experiment = SimpleNamespace(id=experiment_id, dataset_id=uuid4())
        dataset = SimpleNamespace(id=experiment.dataset_id, feature_snapshot_id=uuid4())
        snapshot = SimpleNamespace(id=dataset.feature_snapshot_id, status="ready", data_version_id=uuid4())
        version = SimpleNamespace(specification={"symbols": ["AAA", "BBB"]})
        records = {
            Job: _job("succeeded"),
            Experiment: experiment,
        }
        session = MagicMock()
        session.get.side_effect = lambda cls, _id: records.get(cls) or {
            "Dataset": dataset, "FeatureSnapshot": snapshot, "DataVersion": version,
        }.get(cls.__name__)
        session.scalar.return_value = model
        pipeline = _pipeline("training")
        pipeline.spec["steps"]["training"]["resource_id"] = str(experiment_id)

        self.assertTrue(advance_pipeline_record(session, pipeline))
        self.assertEqual(pipeline.current_step, "backtest")
        backtests = [call.args[0] for call in session.add.call_args_list if isinstance(call.args[0], BacktestRun)]
        self.assertEqual(len(backtests), 1)
        run = backtests[0]
        self.assertEqual(run.signal_source, "model_oos")
        self.assertEqual(run.portfolio_construction["prediction_scope"], "tuning_oos")
        self.assertEqual(str(run.start_date), "2022-09-26")
        self.assertEqual(str(run.end_date), "2024-06-11")

    def test_backtest_success_completes_pipeline(self):
        pipeline = _pipeline("backtest")

        self.assertTrue(advance_pipeline_record(self._session(_job("succeeded")), pipeline))
        self.assertEqual(pipeline.status, "succeeded")
        self.assertEqual(pipeline.current_step, "done")
        self.assertIsNotNone(pipeline.completed_at)


if __name__ == "__main__":
    unittest.main()
