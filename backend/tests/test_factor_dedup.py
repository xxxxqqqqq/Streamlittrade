"""因子入选去冗余契约：贪心去相关只能剔除冗余因子，并且必须留痕。"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import numpy as np
import pandas as pd

from backend.app.models.data_catalog import DataVersion, FactorResearchRun, FeatureSnapshot
from backend.app.models.job import Job
from backend.app.services.research_gates import validate_factor_dataset_gate
from backend.app.workers import data_catalog
from backend.app.workers.data_catalog import (
    DEDUP_CORRELATION_THRESHOLD,
    _abs_pair_correlation,
    _apply_dedup,
    _greedy_dedup,
)
from backend.tests.worker_fakes import FakeSessionFactory, fake_job

HORIZON = 5
RESEARCH_PARAMETERS = {
    "forward_period": HORIZON, "training_fraction": 0.55, "quantiles": 5,
    "min_coverage": 0.7, "min_abs_rank_ic": 0.02, "min_ic_ir": 0.2,
    "false_discovery_rate": 0.05, "min_ic_observations": 30,
}
FEATURE_SLUGS = ["alpha_momentum", "alpha_twin", "alpha_noise"]


def _factors(strengths):
    return {
        slug: {"rank_ic_mean": value, "passed": True, "reasons": []}
        for slug, value in strengths.items()
    }


def _correlation(slugs, pairs):
    """由 {(左,右): ρ} 构造对称的截面 Spearman 相关矩阵（未给出的对按 0 处理）。"""

    matrix = {slug: {other: 0.0 for other in slugs} for slug in slugs}
    for slug in slugs:
        matrix[slug][slug] = 1.0
    for (left, right), value in pairs.items():
        matrix[left][right] = value
        matrix[right][left] = value
    return matrix


class FactorDedupTests(unittest.TestCase):
    def test_threshold_defaults_to_point_seven(self):
        self.assertEqual(DEDUP_CORRELATION_THRESHOLD, 0.7)

    def test_highly_correlated_factor_loses_to_the_stronger_rank_ic(self):
        factors = _factors({"momentum": -0.09, "turnover": 0.05, "noise": 0.02})
        correlation = _correlation(
            ["momentum", "turnover", "noise"], {("momentum", "turnover"): -0.86}
        )

        kept, dropped = _greedy_dedup(factors, correlation, ["turnover", "momentum", "noise"])

        # 保留顺序按|RankIC|降序：|-0.09| 的动量因子胜出，弱相关噪声因子不受影响
        self.assertEqual(kept, ["momentum", "noise"])
        self.assertEqual(dropped, {"turnover": "momentum"})

    def test_apply_dedup_records_reason_and_keeps_snapshot_order(self):
        factors = _factors({"momentum": -0.09, "turnover": 0.05, "noise": 0.02})
        correlation = _correlation(
            ["momentum", "turnover", "noise"], {("momentum", "turnover"): -0.86}
        )

        selected, dedup = _apply_dedup(
            factors, correlation, ["turnover", "momentum", "noise"]
        )

        self.assertEqual(selected, ["momentum", "noise"])
        self.assertEqual(
            dedup,
            {
                "method": "greedy_abs_spearman_v1",
                "threshold": 0.7,
                "dropped": {"turnover": "momentum"},
            },
        )
        self.assertFalse(factors["turnover"]["passed"])
        self.assertEqual(factors["turnover"]["dedup_dropped_by"], "momentum")
        self.assertAlmostEqual(factors["turnover"]["dedup_abs_correlation"], 0.86)
        self.assertIn("与已入选因子 momentum 高度相关", factors["turnover"]["reasons"])
        # 胜出因子不被污染：门禁要求每个 selected 的 passed 仍为真
        self.assertTrue(factors["momentum"]["passed"])
        self.assertEqual(factors["momentum"]["reasons"], [])
        self.assertTrue(all(factors[slug]["passed"] for slug in selected))

    def test_correlation_at_the_threshold_is_still_kept(self):
        factors = _factors({"strong": 0.09, "weak": 0.05})

        kept, dropped = _greedy_dedup(
            factors, _correlation(["strong", "weak"], {("strong", "weak"): 0.7}), ["strong", "weak"]
        )
        self.assertEqual(kept, ["strong", "weak"])
        self.assertEqual(dropped, {})

        kept, dropped = _greedy_dedup(
            factors, _correlation(["strong", "weak"], {("strong", "weak"): 0.7001}), ["strong", "weak"]
        )
        self.assertEqual(kept, ["strong"])
        self.assertEqual(dropped, {"weak": "strong"})

    def test_missing_correlation_is_treated_as_uncorrelated(self):
        factors = _factors({"strong": 0.09, "unmeasured": 0.05, "broken": 0.04})
        correlation = _correlation(["strong", "unmeasured", "broken"], {})
        correlation["strong"]["unmeasured"] = None
        correlation["unmeasured"]["strong"] = None
        correlation["strong"]["broken"] = float("nan")
        correlation["broken"]["strong"] = float("nan")

        kept, dropped = _greedy_dedup(factors, correlation, ["strong", "unmeasured", "broken"])

        self.assertEqual(kept, ["strong", "unmeasured", "broken"])
        self.assertEqual(dropped, {})
        self.assertEqual(_abs_pair_correlation(correlation, "strong", "unmeasured"), 0.0)
        self.assertEqual(_abs_pair_correlation(correlation, "strong", "broken"), 0.0)
        self.assertEqual(_abs_pair_correlation(None, "strong", "broken"), 0.0)

    def test_greedy_only_compares_against_survivors(self):
        """链式高相关（A~B~C）不应连带剔除只与落选因子相关的 C。"""

        factors = _factors({"factor_a": 0.10, "factor_b": 0.08, "factor_c": 0.06})
        correlation = _correlation(
            ["factor_a", "factor_b", "factor_c"],
            {("factor_a", "factor_b"): 0.93, ("factor_b", "factor_c"): 0.88, ("factor_a", "factor_c"): 0.12},
        )

        kept, dropped = _greedy_dedup(
            factors, correlation, ["factor_a", "factor_b", "factor_c"]
        )

        self.assertEqual(kept, ["factor_a", "factor_c"])
        self.assertEqual(dropped, {"factor_b": "factor_a"})

    def test_equal_rank_ic_ties_break_deterministically(self):
        factors = _factors({"alpha": 0.05, "beta": 0.05})
        correlation = _correlation(["alpha", "beta"], {("alpha", "beta"): 0.99})

        first = _greedy_dedup(factors, correlation, ["alpha", "beta"])
        second = _greedy_dedup(factors, correlation, ["beta", "alpha"])

        self.assertEqual(first, second)
        self.assertEqual(first, (["alpha"], {"beta": "alpha"}))


def _write_research_artifacts(directory: Path, *, days: int = 200, symbols: int = 8, seed: int = 23):
    """写出行情与特征快照产物：两个高相关的有效因子 + 一个纯噪声因子。"""

    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=days)
    records = []
    for index in range(symbols):
        walk = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, days)))
        records.extend({
            "date": date, "symbol": f"{index:06d}",
            "open": float(walk[offset]), "close": float(walk[offset]),
        } for offset, date in enumerate(dates))
    market = pd.DataFrame(records).sort_values(["symbol", "date"]).reset_index(drop=True)
    open_price = market.groupby("symbol")["open"]
    market["forward_return"] = open_price.shift(-(1 + HORIZON)) / open_price.shift(-1) - 1
    labeled = market.dropna(subset=["forward_return"])[["date", "symbol", "forward_return"]].copy()
    scale = float(labeled["forward_return"].std())
    # alpha_momentum 与未来收益强相关，alpha_twin 是它的高相关近亲（|ρ|>0.7），
    # alpha_noise 只是噪声：去冗余应当只留下前两者中 RankIC 更强的那一个。
    labeled["alpha_momentum"] = labeled["forward_return"] + rng.normal(0, 0.15 * scale, len(labeled))
    labeled["alpha_twin"] = labeled["alpha_momentum"] + rng.normal(0, 0.25 * scale, len(labeled))
    labeled["alpha_noise"] = rng.normal(0, scale, len(labeled))
    labeled[["date", "symbol", *FEATURE_SLUGS]].to_parquet(directory / "features.parquet", index=False)
    market[["date", "symbol", "open", "close"]].to_parquet(directory / "market.parquet", index=False)
    return directory / "features.parquet", directory / "market.parquet"


class FactorScreeningIntegrationTests(unittest.TestCase):
    """研究 worker 端到端：去冗余后的 screening 必须仍然自洽并通过门禁。"""

    def test_screening_drops_the_redundant_factor_and_keeps_the_gate_valid(self):
        job_id, run_id, snapshot_id, version_id = uuid4(), uuid4(), uuid4(), uuid4()
        with TemporaryDirectory() as directory:
            feature_path, market_path = _write_research_artifacts(Path(directory))
            job = fake_job(id=job_id, payload={"factor_research_id": str(run_id)})
            run = SimpleNamespace(
                id=run_id, project_id=job.project_id, snapshot_id=snapshot_id, name="因子研究",
                status="queued", parameters=dict(RESEARCH_PARAMETERS),
                selected_feature_slugs=[], metrics=None, error_message=None,
            )
            snapshot = SimpleNamespace(
                id=snapshot_id, project_id=job.project_id, data_version_id=version_id, status="ready",
                artifact_uri="s3://quant-artifacts/snapshots/features.parquet", content_sha256="0" * 64,
                lineage={"definitions": [{"slug": slug} for slug in FEATURE_SLUGS]},
            )
            version = SimpleNamespace(
                id=version_id, project_id=job.project_id, status="ready",
                artifact_uri="s3://quant-artifacts/versions/market.parquet", content_sha256="1" * 64,
            )
            store = {
                (Job, job_id): job,
                (FactorResearchRun, run_id): run,
                (FeatureSnapshot, snapshot_id): snapshot,
                (DataVersion, version_id): version,
            }
            artifacts = {snapshot.artifact_uri: feature_path, version.artifact_uri: market_path}
            with mock.patch.object(data_catalog, "SyncSessionFactory", FakeSessionFactory(store)), \
                    mock.patch.object(data_catalog, "cached_artifact", lambda uri, digest: artifacts[uri]):
                result = data_catalog.research_factors(str(job_id))

        metrics = run.metrics
        screening = metrics["screening"]
        selected = run.selected_feature_slugs
        self.assertEqual(selected, screening["selected"])
        self.assertEqual(result["selected"], selected)
        # 两个高相关因子只保留一个，另一个记明被谁挤掉
        self.assertEqual(len(set(selected) & {"alpha_momentum", "alpha_twin"}), 1)
        self.assertEqual(len(screening["dedup"]["dropped"]), 1)
        loser, winner = next(iter(screening["dedup"]["dropped"].items()))
        self.assertIn(winner, selected)
        self.assertEqual(winner, next(iter(set(selected) & {"alpha_momentum", "alpha_twin"})))
        self.assertEqual(loser, next(iter({"alpha_momentum", "alpha_twin"} - {winner})))
        self.assertEqual(screening["dedup"]["threshold"], DEDUP_CORRELATION_THRESHOLD)
        self.assertEqual(screening["dedup"]["method"], "greedy_abs_spearman_v1")
        # 保留下来的是 |RankIC| 更强的一个，且 |ρ| 确实超过阈值
        factors = metrics["factors"]
        self.assertGreater(abs(factors[winner]["rank_ic_mean"]), abs(factors[loser]["rank_ic_mean"]))
        self.assertGreater(abs(metrics["correlation"][winner][loser]), DEDUP_CORRELATION_THRESHOLD)
        # 纯噪声因子与相关因子在统计门禁上都不通过
        self.assertNotIn("alpha_noise", selected)
        self.assertIn("alpha_noise", screening["rejected"])
        # 被剔除的因子留痕且不再是"通过"状态
        self.assertFalse(factors[loser]["passed"])
        self.assertEqual(factors[loser]["dedup_dropped_by"], winner)
        self.assertIn(f"与已入选因子 {winner} 高度相关", factors[loser]["reasons"])
        self.assertTrue(all(factors[slug]["passed"] for slug in selected))
        # 门禁契约不变：selected 与审查指标一致，且仍能生成数据集特征清单
        self.assertEqual(
            validate_factor_dataset_gate(
                snapshot_id=snapshot_id,
                horizon=HORIZON,
                training_fraction=0.55,
                run_snapshot_id=snapshot_id,
                run_status=run.status,
                run_parameters=run.parameters,
                run_metrics=metrics,
                selected_feature_slugs=selected,
            ),
            selected,
        )


if __name__ == "__main__":
    unittest.main()
