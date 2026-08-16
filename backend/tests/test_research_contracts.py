"""数据集与训练实验的输入契约测试。"""

import unittest
from uuid import uuid4

from pydantic import ValidationError

from backend.app.schemas.research import (
    DatasetCreate,
    ExperimentCreate,
    PredictionCreate,
    StrategyCreate,
)


class ResearchContractTests(unittest.TestCase):
    """保证进入异步训练队列前，请求已经被规范化并完成校验。"""

    def test_demo_dataset_expands_to_multiple_reproducible_symbols(self):
        request = DatasetCreate(
            name="demo dataset", data_source="demo", symbols=["ignored"]
        )

        self.assertEqual(request.symbols, ["DEMO1", "DEMO2", "DEMO3"])
        self.assertEqual(request.horizon, 5)

    def test_market_dataset_rejects_invalid_symbol(self):
        with self.assertRaises(ValidationError):
            DatasetCreate(data_source="baostock", symbols=["not-a-stock"])

    def test_formal_dataset_requires_feature_snapshot(self):
        with self.assertRaises(ValidationError):
            DatasetCreate(name="formal dataset", data_source="feature_snapshot")

        snapshot_id, factor_research_id=uuid4(), uuid4()
        with self.assertRaises(ValidationError):
            DatasetCreate(
                name="formal dataset",
                data_source="feature_snapshot",
                feature_snapshot_id=snapshot_id,
            )
        request=DatasetCreate(
            name="formal dataset",
            data_source="feature_snapshot",
            feature_snapshot_id=snapshot_id,
            factor_research_id=factor_research_id,
        )
        self.assertEqual(request.feature_snapshot_id,snapshot_id)
        self.assertEqual(request.factor_research_id,factor_research_id)
        self.assertEqual(request.training_fraction, 0.55)
        self.assertEqual(request.tuning_fraction, 0.25)
        self.assertAlmostEqual(1-request.training_fraction-request.tuning_fraction, 0.20)

    def test_dataset_keeps_a_final_sealed_region(self):
        with self.assertRaises(ValidationError):
            DatasetCreate(
                name="leaky dataset", data_source="demo",
                training_fraction=0.7, tuning_fraction=0.25,
            )

    def test_experiment_has_safe_baseline_defaults(self):
        request = ExperimentCreate(name="baseline", dataset_id=uuid4())

        self.assertEqual(request.algorithm, "hist_gradient_boosting")
        self.assertGreater(request.parameters["max_iter"], 0)

    def test_each_reviewed_algorithm_gets_its_own_defaults(self):
        forest = ExperimentCreate(
            name="forest", dataset_id=uuid4(), algorithm="random_forest"
        )
        extra_trees = ExperimentCreate(
            name="extra trees", dataset_id=uuid4(), algorithm="extra_trees"
        )
        logistic = ExperimentCreate(
            name="logistic", dataset_id=uuid4(), algorithm="logistic_regression"
        )

        self.assertEqual(forest.parameters["n_estimators"], 300)
        self.assertEqual(extra_trees.parameters["n_estimators"], 400)
        self.assertEqual(extra_trees.parameters["max_features"], 0.7)
        self.assertEqual(logistic.parameters["C"], 1.0)
        with self.assertRaises(ValidationError):
            ExperimentCreate(
                name="bad forest",
                dataset_id=uuid4(),
                algorithm="random_forest",
                parameters={"learning_rate": 0.1},
            )

    def test_strategy_versions_validate_the_registered_implementation(self):
        strategy = StrategyCreate(name="trend", slug="trend-v1")

        self.assertEqual(strategy.implementation, "right_trend")
        self.assertEqual(strategy.parameters["ma_long"], 60)
        with self.assertRaises(ValidationError):
            StrategyCreate(
                name="invalid",
                slug="invalid",
                implementation="v_shape",
                parameters={"ma_short": 5},
            )

    def test_prediction_contract_requires_immutable_resource_ids(self):
        model_id, snapshot_id = uuid4(), uuid4()
        request = PredictionCreate(
            name="daily score",
            model_id=model_id,
            feature_snapshot_id=snapshot_id,
        )

        self.assertEqual(request.model_id, model_id)
        self.assertEqual(request.feature_snapshot_id, snapshot_id)


if __name__ == "__main__":
    unittest.main()
