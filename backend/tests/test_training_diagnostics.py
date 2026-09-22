"""训练侧算法深化契约：HGB 小网格搜索、折叠级 IC 衰减与口径标注。

这些用例不依赖外部数据库：`train_experiment` 用最小会话替身与内存产物跑完整
流程，验证写入 Experiment/ModelVersion 的 metrics 与 reproducibility 契约。
"""

import io
import unittest
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import numpy as np
import pandas as pd

from backend.app.models.job import Job
from backend.app.models.research import Dataset, Experiment
from backend.app.workers import research
from backend.tests.worker_fakes import FakeSessionFactory, fake_job
from quant_core.ml import FEATURES, cross_sectional_rank_features, economic_metrics, three_way_research_split

HORIZON = 5


def _synthetic_frame(*, symbols: int = 4, days: int = 240, seed: int = 11) -> pd.DataFrame:
    """构造截面可比的合成数据集：标签沿用"跑赢当日截面中位数"口径。"""

    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-02", periods=days)
    records = []
    for date in dates:
        values = rng.normal(0, 1, size=(symbols, len(FEATURES)))
        forward = values[:, 0] * 0.01 + rng.normal(0, 0.02, size=symbols)
        for index in range(symbols):
            records.append({
                "date": date,
                "symbol": f"{index:06d}",
                **{
                    feature: float(values[index, position])
                    for position, feature in enumerate(FEATURES)
                },
                "future_return": float(forward[index]),
            })
    frame = pd.DataFrame(records).sort_values(["date", "symbol"]).reset_index(drop=True)
    median = frame.groupby("date")["future_return"].transform("median")
    frame["label"] = (frame["future_return"] > median).astype(int)
    return frame


def _first_fold_features(frame: pd.DataFrame):
    split = three_way_research_split(
        frame["date"], training_fraction=0.55, tuning_fraction=0.25,
        n_tuning_splits=3, purge_days=HORIZON, embargo_days=HORIZON,
    )
    fold = split.tuning_folds[0]
    train, test = frame.iloc[fold.train_index], frame.iloc[fold.test_index]
    return fold, train, test, cross_sectional_rank_features(train, FEATURES), cross_sectional_rank_features(test, FEATURES)


def _run_train_experiment(*, frame: pd.DataFrame, parameters: dict, algorithm: str = "hist_gradient_boosting"):
    """在内存里跑完整 train_experiment，返回被写回的 Experiment 记录。"""

    buffer = io.BytesIO()
    frame.to_parquet(buffer, index=False)
    artifact = buffer.getvalue()
    job_id, experiment_id, dataset_id = uuid4(), uuid4(), uuid4()
    job = fake_job(id=job_id, payload={"experiment_id": str(experiment_id)})
    dataset = SimpleNamespace(
        id=dataset_id, project_id=job.project_id, status="ready",
        artifact_uri="s3://quant-artifacts/datasets/synthetic/features.parquet",
        specification={
            "horizon": HORIZON, "training_fraction": 0.55, "tuning_fraction": 0.25, "tuning_folds": 3,
        },
        metadata_snapshot={
            "schema_version": 2, "features": list(FEATURES),
            "research_protocol": {"training_fraction": 0.55, "tuning_fraction": 0.25, "tuning_folds": 3},
        },
        row_count=len(frame), feature_count=len(FEATURES),
    )
    experiment = SimpleNamespace(
        id=experiment_id, project_id=job.project_id, dataset_id=dataset_id, name="合成实验",
        algorithm=algorithm, parameters=dict(parameters), status="queued",
        metrics=None, reproducibility=None, error_message=None,
    )
    store = {(Job, job_id): job, (Experiment, experiment_id): experiment, (Dataset, dataset_id): dataset}
    with mock.patch.object(research, "SyncSessionFactory", FakeSessionFactory(store)), \
            mock.patch.object(research, "download_bytes", lambda uri: artifact), \
            mock.patch.object(research, "upload_bytes", lambda name, content, content_type: f"s3://quant-artifacts/{name}"):
        research.train_experiment(str(job_id))
    return experiment


class GridSearchContractTests(unittest.TestCase):
    """网格搜索默认关闭，开启后候选与最优参数必须可复现地留档。"""

    def test_grid_search_is_disabled_without_the_switch(self):
        parameters = {"max_iter": 30, "max_depth": 4, "learning_rate": 0.05}

        resolved, report = research._resolve_training_parameters("hist_gradient_boosting", parameters)

        self.assertIsNone(report)
        self.assertEqual(resolved, parameters)
        self.assertIsNot(resolved, parameters)

    def test_grid_search_only_applies_to_hist_gradient_boosting(self):
        self.assertTrue(research._grid_search_enabled("hist_gradient_boosting", {"grid_search": True}))
        self.assertFalse(research._grid_search_enabled("hist_gradient_boosting", {"grid_search": False}))
        self.assertFalse(research._grid_search_enabled("hist_gradient_boosting", {}))
        self.assertFalse(research._grid_search_enabled("random_forest", {"grid_search": True}))

    def test_grid_offers_nine_candidates_and_keeps_other_parameters(self):
        candidates = research._hgb_grid_candidates(
            {"max_iter": 60, "max_depth": 4, "learning_rate": 0.2, "grid_search": True}
        )

        self.assertEqual(len(candidates), 9)
        self.assertEqual(
            {(item["learning_rate"], item["max_leaf_nodes"]) for item in candidates},
            {(rate, leaves) for rate in (0.03, 0.05, 0.1) for leaves in (15, 31, 63)},
        )
        for candidate in candidates:
            self.assertEqual(candidate["max_iter"], 60)
            self.assertEqual(candidate["max_depth"], 4)
            self.assertNotIn("grid_search", candidate)

    def test_grid_control_switch_never_reaches_the_estimator(self):
        with self.assertRaises(TypeError):
            research._build_estimator("hist_gradient_boosting", {"max_iter": 5, "grid_search": True}).fit(
                pd.DataFrame({"a": [0.0, 1.0], "b": [1.0, 0.0]}), [0, 1]
            )
        self.assertEqual(
            research._estimator_parameters({"max_iter": 5, "grid_search": True}), {"max_iter": 5}
        )

    def test_grid_search_selects_the_best_candidate_by_fold_rank_ic(self):
        frame = _synthetic_frame(days=200)
        fold, train, test, train_features, test_features = _first_fold_features(frame)

        resolved, report = research._resolve_training_parameters(
            "hist_gradient_boosting",
            {"max_iter": 30, "max_depth": 4, "learning_rate": 0.05, "grid_search": True},
            train_frame=train, train_features=train_features,
            test_frame=test, test_features=test_features, fold=fold, horizon=HORIZON,
        )

        self.assertEqual(len(report["candidates"]), 9)
        self.assertEqual(report["selection_metric"], "tuning_fold_rank_ic")
        self.assertEqual(report["selection_fold"]["fold"], fold.fold)
        self.assertEqual(report["grid"], {"learning_rate": [0.03, 0.05, 0.1], "max_leaf_nodes": [15, 31, 63]})
        observed = [item["rank_ic"] for item in report["candidates"]]
        self.assertTrue(all(value is not None for value in observed))
        selected = report["selected"]
        self.assertEqual(selected["rank_ic"], max(observed))
        self.assertEqual(selected["parameters"], report["candidates"][observed.index(max(observed))]["parameters"])
        # 最优参数覆盖基础参数，控制开关不进入估计器参数
        self.assertEqual(resolved["learning_rate"], selected["parameters"]["learning_rate"])
        self.assertEqual(resolved["max_leaf_nodes"], selected["parameters"]["max_leaf_nodes"])
        self.assertEqual(resolved["max_iter"], 30)
        self.assertNotIn("grid_search", resolved)

    def test_grid_search_never_recomputes_the_feature_matrix(self):
        frame = _synthetic_frame(days=200)
        fold, train, test, train_features, test_features = _first_fold_features(frame)

        with mock.patch.object(
            research, "cross_sectional_rank_features",
            side_effect=AssertionError("网格搜索不得重复计算截面 rank 特征"),
        ):
            _, report = research._resolve_training_parameters(
                "hist_gradient_boosting",
                {"max_iter": 20, "max_depth": 3, "grid_search": True},
                train_frame=train, train_features=train_features,
                test_frame=test, test_features=test_features, fold=fold, horizon=HORIZON,
            )

        self.assertEqual(len(report["candidates"]), 9)


class RankIcDecayTests(unittest.TestCase):
    def test_cross_sectional_rank_ic_is_a_daily_spearman_mean(self):
        dates = pd.to_datetime(["2024-01-02"] * 3 + ["2024-01-03"] * 3)
        scores = [0.1, 0.2, 0.9, 0.9, 0.2, 0.1]
        forward = [-0.05, 0.0, 0.05, 0.05, 0.0, -0.05]

        value = research._cross_sectional_rank_ic(dates, scores, forward)

        self.assertEqual(value, 1.0)
        self.assertEqual(research._cross_sectional_rank_ic(dates, scores, [-item for item in forward]), -1.0)

    def test_cross_sectional_rank_ic_ignores_single_stock_dates(self):
        dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-03"])
        scores = [0.5, 0.1, 0.9]
        forward = [0.01, -0.02, 0.03]

        self.assertEqual(research._cross_sectional_rank_ic(dates, scores, forward), 1.0)
        self.assertIsNone(research._cross_sectional_rank_ic(dates[:1], scores[:1], forward[:1]))

    def test_fold_rank_ic_matches_the_economic_metric_definition(self):
        predictions = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-02"] * 3 + ["2024-01-03"] * 3),
            "symbol": ["A", "B", "C"] * 2,
            "probability": [0.9, 0.5, 0.2, 0.1, 0.4, 0.8],
            "future_return": [0.03, 0.01, -0.02, -0.03, 0.0, 0.04],
        })

        self.assertEqual(
            research._cross_sectional_rank_ic(
                predictions["date"], predictions["probability"], predictions["future_return"]
            ),
            economic_metrics(predictions, horizon=HORIZON)["rank_ic"],
        )

    def test_fold_summary_reports_mean_and_first_to_last_decay(self):
        folds = [{"fold": 1, "rank_ic": 0.05}, {"fold": 2, "rank_ic": 0.02}, {"fold": 3, "rank_ic": -0.01}]

        summary = research._fold_rank_ic_summary(folds)

        self.assertEqual(set(summary), {"rank_ic_mean", "rank_ic_decay"})
        self.assertAlmostEqual(summary["rank_ic_mean"], 0.02, places=6)
        self.assertAlmostEqual(summary["rank_ic_decay"], 0.06, places=6)

    def test_fold_summary_tolerates_folds_without_a_usable_cross_section(self):
        summary = research._fold_rank_ic_summary([{"fold": 1, "rank_ic": None}, {"fold": 2, "rank_ic": 0.03}])

        self.assertAlmostEqual(summary["rank_ic_mean"], 0.03, places=6)
        self.assertIsNone(summary["rank_ic_decay"])
        self.assertEqual(
            research._fold_rank_ic_summary([{"fold": 1, "rank_ic": None}]),
            {"rank_ic_mean": None, "rank_ic_decay": None},
        )


class TrainingSummaryContractTests(unittest.TestCase):
    """默认关闭时训练行为不变，但新增的 IC 衰减与口径标注必须落库。"""

    @classmethod
    def setUpClass(cls):
        cls.frame = _synthetic_frame()
        cls.baseline_parameters = {"max_iter": 30, "max_depth": 4, "learning_rate": 0.05}

    def test_baseline_training_exposes_rank_ic_decay_and_estimate_kind(self):
        experiment = _run_train_experiment(frame=self.frame, parameters=self.baseline_parameters)
        metrics = experiment.metrics

        self.assertEqual(len(metrics["folds"]), 3)
        for fold in metrics["folds"]:
            self.assertIn("rank_ic", fold)
        self.assertIn("rank_ic_mean", metrics)
        self.assertIn("rank_ic_decay", metrics)
        self.assertAlmostEqual(
            metrics["rank_ic_mean"],
            round(float(np.mean([fold["rank_ic"] for fold in metrics["folds"]])), 6),
            places=6,
        )
        self.assertAlmostEqual(
            metrics["rank_ic_decay"],
            round(float(metrics["folds"][0]["rank_ic"] - metrics["folds"][-1]["rank_ic"]), 6),
            places=6,
        )
        self.assertEqual(metrics["estimate_kind"], "research_proxy")
        # 既有键结构不变：只有新增键，没有改名或改语义
        for key in ("accuracy", "balanced_accuracy", "roc_auc", "calibration", "folds", "rank_ic", "icir"):
            self.assertIn(key, metrics)
        self.assertNotIn("grid_search", experiment.reproducibility)
        self.assertEqual(experiment.reproducibility["parameters"], self.baseline_parameters)
        self.assertEqual(experiment.reproducibility["algorithm"], "hist_gradient_boosting")

    def test_enabled_grid_search_lands_in_reproducibility(self):
        experiment = _run_train_experiment(
            frame=self.frame,
            parameters={**self.baseline_parameters, "grid_search": True},
        )

        grid = experiment.reproducibility["grid_search"]
        self.assertEqual(len(grid["candidates"]), 9)
        self.assertEqual(grid["selection_metric"], "tuning_fold_rank_ic")
        selected = grid["selected"]["parameters"]
        self.assertIn(selected["learning_rate"], research.HGB_GRID_LEARNING_RATES)
        self.assertIn(selected["max_leaf_nodes"], research.HGB_GRID_MAX_LEAF_NODES)
        self.assertNotIn("grid_search", selected)
        observed = [item["rank_ic"] for item in grid["candidates"] if item["rank_ic"] is not None]
        self.assertTrue(observed)
        self.assertEqual(grid["selected"]["rank_ic"], max(observed))
        # 登记模型使用的就是网格选中的超参
        for key, value in selected.items():
            self.assertEqual(experiment.reproducibility["parameters"][key], value)
        self.assertEqual(experiment.metrics["estimate_kind"], "research_proxy")
        self.assertIn("rank_ic_mean", experiment.metrics)


if __name__ == "__main__":
    unittest.main()
