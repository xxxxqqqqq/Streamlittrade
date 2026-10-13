"""基本面时点（PIT）对齐契约测试。

覆盖三件事：季度财务字段映射与公告日解析、as-of 对齐不会泄漏未来信息、
增强 Worker 能落出一个绑定父版本的新数据版本。
"""

import ast
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest import mock

import numpy as np
import pandas as pd

from backend.app.models.data_catalog import DataVersion
from backend.app.models.job import Job
from backend.app.schemas.data_catalog import FeatureCreate
from backend.app.services.factors import (
    ALLOWED_IMPLEMENTATIONS,
    FACTOR_LIBRARY,
    POINT_IN_TIME_IMPLEMENTATIONS,
    compute_factor,
    validate_expression,
)
from backend.app.workers import data_catalog, local_artifacts
from backend.tests.worker_fakes import FakeSessionFactory, fake_job
from quant_core.fundamental_data import (
    DAILY_FUNDAMENTAL_COLUMNS,
    LONG_COLUMNS,
    PIPELINE_VERSION,
    fetch_quarterly_fundamentals,
    fundamentals_to_daily,
)


class FakeQuarterlyClient:
    """预置表驱动的季度客户端：键是 (表, baostock 代码, 年, 季)。"""

    def __init__(self, tables):
        self.tables, self.calls = tables, []

    def fetch(self, table, code, year, quarter):
        self.calls.append((table, code, year, quarter))
        return self.tables.get((table, code, year, quarter), pd.DataFrame()).copy()


class SessionClient(FakeQuarterlyClient):
    """记录登录/登出次数，用来验证会话归属约定。"""

    def __init__(self, tables):
        super().__init__(tables)
        self.logins, self.logouts = 0, 0

    def login(self):
        self.logins += 1

    def logout(self):
        self.logouts += 1


def _row(**values):
    return pd.DataFrame([values])


def _four_tables(code, year, quarter, *, stat_date, pub_date, **overrides):
    """一次完整公告的四张表原始返回。"""
    profit = {"roeAvg": "0.05", "npMargin": "0.20", "gpMargin": "0.25", "netProfit": "1000", "MBRevenue": "10000"}
    growth = {"YOYNI": "0.30"}
    balance = {"liabilityToAsset": "0.40", "assetToEquity": "2.0"}
    cash_flow = {"CFOToNP": "1.5"}
    profit.update(overrides.get("profit") or {})
    growth.update(overrides.get("growth") or {})
    balance.update(overrides.get("balance") or {})
    cash_flow.update(overrides.get("cash_flow") or {})
    return {
        ("profit", code, year, quarter): _row(pubDate=pub_date, statDate=stat_date, **profit),
        ("growth", code, year, quarter): _row(pubDate=pub_date, statDate=stat_date, **growth),
        ("balance", code, year, quarter): _row(pubDate=pub_date, statDate=stat_date, **balance),
        ("cash_flow", code, year, quarter): _row(pubDate=pub_date, statDate=stat_date, **cash_flow),
    }


def _long_frame(rows):
    """直接构造长表，用于纯对齐测试（不经过任何数据源）。"""
    frame = pd.DataFrame(rows)
    frame["symbol"] = frame["symbol"].astype(str)
    frame["stat_date"] = pd.to_datetime(frame["stat_date"])
    frame["pub_date"] = pd.to_datetime(frame["pub_date"])
    return frame.reindex(columns=list(LONG_COLUMNS) + ["revenue_yoy", "accruals"])


class FundamentalFetchTests(unittest.TestCase):
    def test_quarterly_tables_map_to_a_pit_long_frame(self):
        tables = {}
        tables.update(
            _four_tables(
                "sh.600000", 2023, 4, stat_date="2023-12-31", pub_date="2024-04-30",
                profit={"roeAvg": "0.051598", "gpMargin": "0.25", "npMargin": "0.215811"},
            )
        )
        tables.update(
            _four_tables(
                "sh.600000", 2022, 4, stat_date="2022-12-31", pub_date="2023-04-28",
                profit={"roeAvg": "0.06", "gpMargin": "0.30", "npMargin": "0.20", "MBRevenue": "8000"},
            )
        )
        client = FakeQuarterlyClient(tables)

        frame = fetch_quarterly_fundamentals(["600000"], 2022, 2023, client=client, sleeper=lambda _: None)

        self.assertEqual(list(frame.columns), list(LONG_COLUMNS) + ["revenue_yoy", "accruals"])
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(frame["pub_date"]))
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(frame["stat_date"]))
        latest = frame.iloc[-1]
        # gpMargin 映射到 gross_margin（不是 npMargin），YOYNI 映射到 profit_yoy
        self.assertAlmostEqual(latest["gross_margin"], 0.25)
        self.assertAlmostEqual(latest["np_margin"], 0.215811)
        self.assertAlmostEqual(latest["profit_yoy"], 0.30)
        self.assertAlmostEqual(latest["cfo_to_np"], 1.5)
        self.assertAlmostEqual(latest["liability_to_asset"], 0.40)
        self.assertAlmostEqual(latest["roe_avg"], 0.051598)
        # 营收同比 = 10000 / 8000 - 1，且只能用上年同期
        self.assertAlmostEqual(latest["revenue_yoy"], 0.25)
        # 应计利润 = (1 - 1.5) * 0.051598 / 2.0
        self.assertAlmostEqual(latest["accruals"], -0.5 * 0.051598 / 2.0)
        self.assertEqual(frame.attrs["warnings"]["symbols_with_fundamentals"], ["600000"])
        # 缺的季度返回空表，只计数不报错
        self.assertGreater(frame.attrs["warnings"]["empty_queries"], 0)

    def test_rows_without_publication_date_are_dropped_and_counted(self):
        client = FakeQuarterlyClient(
            _four_tables("sh.600000", 2023, 4, stat_date="2023-12-31", pub_date="", profit={"roeAvg": "0.05"})
        )

        frame = fetch_quarterly_fundamentals(["600000"], 2023, 2023, client=client, sleeper=lambda _: None)

        self.assertEqual(frame.attrs["warnings"]["missing_pub_date_rows"], 4)
        self.assertTrue(frame.empty)
        self.assertEqual(frame.attrs["warnings"]["symbols_with_fundamentals"], [])

    def test_invalid_symbol_is_rejected_before_any_query(self):
        client = FakeQuarterlyClient({})

        with self.assertRaises(ValueError):
            fetch_quarterly_fundamentals(["60000"], 2023, 2023, client=client, sleeper=lambda _: None)

        self.assertEqual(client.calls, [])

    def test_session_belongs_to_whoever_created_the_client(self):
        tables = _four_tables("sh.600000", 2023, 4, stat_date="2023-12-31", pub_date="2024-04-30")
        injected = SessionClient(tables)

        fetch_quarterly_fundamentals(["600000"], 2023, 2023, client=injected, sleeper=lambda _: None)

        # 外部注入的客户端由调用方关闭：批量逐股取数可以只登录一次
        self.assertEqual((injected.logins, injected.logouts), (0, 0))

        created = SessionClient(tables)
        with mock.patch("quant_core.fundamental_data.baostock_quarterly_client", lambda: created):
            fetch_quarterly_fundamentals(["600000"], 2023, 2023, sleeper=lambda _: None)

        # 函数自己创建的客户端由函数负责登出，避免留下悬挂会话
        self.assertEqual(created.logouts, 1)


class PointInTimeAlignmentTests(unittest.TestCase):
    def _trading(self, dates, symbols=("600000",)):
        return pd.DataFrame(
            [(symbol, date) for symbol in symbols for date in pd.to_datetime(dates)],
            columns=["symbol", "date"],
        )

    def test_metric_is_missing_before_its_publication_date(self):
        long = _long_frame(
            [{"symbol": "600000", "stat_date": "2023-12-31", "pub_date": "2024-04-30", "roe_avg": 0.05}]
        )
        trading = self._trading(["2024-01-02", "2024-04-29", "2024-04-30", "2024-05-06"])

        daily = fundamentals_to_daily(long, trading)

        self.assertEqual(list(daily.columns), ["symbol", "date", *DAILY_FUNDAMENTAL_COLUMNS, "fundamental_pub_date"])
        values = daily.set_index("date")["roe_avg"]
        # 报告期 2023-12-31 在样本区间内，但公告日之前一律为空：绝不按 stat_date 对齐
        self.assertTrue(pd.isna(values.loc["2024-01-02"]))
        self.assertTrue(pd.isna(values.loc["2024-04-29"]))
        self.assertAlmostEqual(values.loc["2024-04-30"], 0.05)
        self.assertAlmostEqual(values.loc["2024-05-06"], 0.05)
        self.assertEqual(daily["fundamental_pub_date"].dropna().unique().tolist(), [pd.Timestamp("2024-04-30")])

    def test_revision_is_only_visible_after_its_own_announcement(self):
        long = _long_frame(
            [
                {"symbol": "600000", "stat_date": "2023-12-31", "pub_date": "2024-04-30", "roe_avg": 0.05},
                {"symbol": "600000", "stat_date": "2023-12-31", "pub_date": "2024-08-30", "roe_avg": 0.07},
            ]
        )
        trading = self._trading(["2024-05-06", "2024-08-29", "2024-09-02"])

        values = fundamentals_to_daily(long, trading).set_index("date")["roe_avg"]

        self.assertAlmostEqual(values.loc["2024-05-06"], 0.05)
        self.assertAlmostEqual(values.loc["2024-08-29"], 0.05)
        self.assertAlmostEqual(values.loc["2024-09-02"], 0.07)

    def test_symbols_without_fundamentals_stay_missing(self):
        long = _long_frame(
            [{"symbol": "600000", "stat_date": "2023-12-31", "pub_date": "2024-04-30", "roe_avg": 0.05}]
        )
        trading = self._trading(["2024-05-06"], symbols=("600000", "000002"))

        daily = fundamentals_to_daily(long, trading).set_index("symbol")

        self.assertAlmostEqual(daily.loc["600000", "roe_avg"], 0.05)
        self.assertTrue(pd.isna(daily.loc["000002", "roe_avg"]))

    def test_bare_trading_dates_broadcast_across_the_long_frame_symbols(self):
        long = _long_frame(
            [{"symbol": "600000", "stat_date": "2023-12-31", "pub_date": "2024-04-30", "roe_avg": 0.05}]
        )

        daily = fundamentals_to_daily(long, pd.to_datetime(["2024-05-06"]))

        self.assertEqual(daily["symbol"].tolist(), ["600000"])
        self.assertAlmostEqual(daily["roe_avg"].iloc[0], 0.05)

    def test_empty_long_frame_returns_a_full_schema(self):
        daily = fundamentals_to_daily(pd.DataFrame(columns=LONG_COLUMNS), self._trading(["2024-05-06"]))

        self.assertEqual(list(daily.columns), ["symbol", "date", *DAILY_FUNDAMENTAL_COLUMNS, "fundamental_pub_date"])
        self.assertTrue(daily[list(DAILY_FUNDAMENTAL_COLUMNS)].isna().all().all())

    def test_alignment_module_never_imports_baostock(self):
        path = Path(__file__).parents[2] / "quant_core" / "fundamental_data.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in tree.body:
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            self.assertNotIn("baostock", names)


def _panel_frame():
    dates = pd.to_datetime(["2024-03-05", "2024-04-29", "2024-04-30", "2024-05-06", "2024-06-03", "2024-07-01"])
    rows = []
    for symbol, offset in (("600000", 0.0), ("000002", 10.0)):
        for index, date in enumerate(dates):
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": 10.0 + offset + index,
                    "high": 11.0 + offset + index,
                    "low": 9.0 + offset + index,
                    "close": 10.5 + offset + index,
                    "volume": 1000.0 + index,
                }
            )
    return pd.DataFrame(rows)


def _worker_root(path):
    """复刻真实 worker_data_root 的目录约定（promote_cached_artifact 依赖 cache/）。"""
    for name in ("cache", "checkpoints", "staging", "logs"):
        (path / name).mkdir(parents=True, exist_ok=True)
    return path


class FundamentalEnrichWorkerTests(unittest.TestCase):
    def _store(self, source_uri):
        job_id, source_id, enrich_id = uuid4(), uuid4(), uuid4()
        job = fake_job(
            id=job_id,
            payload={"enrich_version_id": str(enrich_id), "source_version_id": str(source_id)},
        )
        source = DataVersion(
            id=source_id, project_id=uuid4(), source_id=uuid4(), layer="standardized", status="ready",
            specification={}, artifact_uri=source_uri, content_sha256="a" * 64,
            lineage={"transform": "canonical_market_v2"},
        )
        enrich = DataVersion(
            id=enrich_id, project_id=source.project_id, source_id=source.source_id, parent_id=source_id,
            job_id=job_id, layer="standardized", status="queued", specification={},
            lineage={"parent_id": str(source_id)},
        )
        return job, source, enrich, {(Job, job_id): job, (DataVersion, source_id): source, (DataVersion, enrich_id): enrich}

    def _run(self, job, store, tmp_root, client, panel_path):
        uploaded = {}

        def _upload(name, path, content_type):
            uploaded["uri"], uploaded["path"] = name, Path(path)
            return f"s3://{name}"

        with mock.patch.object(data_catalog, "SyncSessionFactory", FakeSessionFactory(store)), \
                mock.patch.object(data_catalog, "cached_artifact", lambda *args: panel_path), \
                mock.patch.object(data_catalog, "upload_file", _upload), \
                mock.patch.object(data_catalog, "worker_data_root", lambda: _worker_root(tmp_root)), \
                mock.patch.object(local_artifacts, "worker_data_root", lambda: _worker_root(tmp_root)), \
                mock.patch.object(data_catalog, "_fundamental_client", lambda: client), \
                mock.patch.object(data_catalog, "_progress", lambda *args: None):
            summary = data_catalog.enrich_fundamentals(str(job.id))
        return summary, uploaded

    def test_enrich_publishes_a_new_version_bound_to_its_parent(self):
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            panel_path = root / "standard.parquet"
            panel = _panel_frame()
            panel.to_parquet(panel_path, index=False)
            job, source, enrich, store = self._store("s3://data/standardized/source.parquet")
            client = FakeQuarterlyClient(
                _four_tables("sh.600000", 2023, 4, stat_date="2023-12-31", pub_date="2024-04-30",
                             profit={"roeAvg": "0.05", "gpMargin": "0.25"})
            )

            summary, uploaded = self._run(job, store, root, client, panel_path)

            self.assertEqual(job.status, "succeeded")
            self.assertEqual(enrich.status, "ready")
            self.assertEqual(enrich.lineage["transform"], PIPELINE_VERSION)
            self.assertEqual(enrich.lineage["parent_id"], str(source.id))
            self.assertEqual(enrich.lineage["alignment"], "pub_date_asof_backward_v1")
            self.assertEqual(enrich.lineage["year_range"], [2023, 2024])
            self.assertEqual(enrich.lineage["fetched_symbols"], 1)
            self.assertEqual(enrich.lineage["pub_date_coverage"]["600000"]["min"], "2024-04-30")
            self.assertEqual(enrich.quality_report["symbols_without_fundamentals"], ["000002"])
            # 12 行行情里只有 600000 在 04-30 及之后的 4 行拿到了 ROE
            self.assertAlmostEqual(enrich.quality_report["coverage"]["roe_avg"], 4 / 12, places=5)
            self.assertEqual(enrich.row_count, len(panel))
            # 结果摘要用平台统一的 standard_version_id，任务中心才能定位到新版本
            self.assertEqual(summary["standard_version_id"], str(enrich.id))

            published = pd.read_parquet(uploaded["path"])
            self.assertEqual(list(published.columns), [*panel.columns, *DAILY_FUNDAMENTAL_COLUMNS, "fundamental_pub_date"])
            values = published.set_index(["symbol", "date"])["roe_avg"]
            self.assertTrue(pd.isna(values.loc[("600000", pd.Timestamp("2024-04-29"))]))
            self.assertAlmostEqual(values.loc[("600000", pd.Timestamp("2024-04-30"))], 0.05)
            self.assertTrue(pd.isna(values.loc[("000002", pd.Timestamp("2024-07-01"))]))

    def test_resume_reuses_per_symbol_checkpoints(self):
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            panel_path = root / "standard.parquet"
            _panel_frame().to_parquet(panel_path, index=False)
            job, source, enrich, store = self._store("s3://data/standardized/source.parquet")
            client = FakeQuarterlyClient(
                _four_tables("sh.600000", 2023, 4, stat_date="2023-12-31", pub_date="2024-04-30")
            )

            self._run(job, store, root, client, panel_path)
            first_queries = len(client.calls)
            enrich.status, job.status = "running", "running"
            summary, _ = self._run(job, store, root, client, panel_path)

            self.assertGreater(first_queries, 0)
            self.assertEqual(summary["resumed_symbols"], 1)
            self.assertEqual(summary["fetched_symbols"], 0)
            # 检查点命中的股票完全不重新查询；没有财报的股票会重查（不把抖动固化）
            self.assertTrue(all(call[1] != "sh.600000" for call in client.calls[first_queries:]))
            self.assertTrue(all(call[1] == "sz.000002" for call in client.calls[first_queries:]))

    def test_source_version_with_fundamental_columns_is_rejected(self):
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            panel_path = root / "standard.parquet"
            panel = _panel_frame().assign(roe_avg=np.nan)
            panel.to_parquet(panel_path, index=False)
            job, source, enrich, store = self._store("s3://data/standardized/source.parquet")

            with self.assertRaises(ValueError):
                self._run(job, store, root, FakeQuarterlyClient({}), panel_path)

            self.assertEqual(job.status, "failed")
            self.assertEqual(enrich.status, "failed")


class FundamentalFactorTests(unittest.TestCase):
    NEW_IMPLEMENTATIONS = ("roe_ttm", "gross_margin", "revenue_yoy", "profit_yoy", "cfo_quality", "accruals")

    def test_missing_columns_return_all_missing_instead_of_raising(self):
        frame = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3), "close": [10.0, 11.0, 12.0]})

        for implementation in self.NEW_IMPLEMENTATIONS:
            values = compute_factor(frame, implementation, {"window": 1})
            self.assertTrue(values.isna().all(), implementation)

    def test_fundamental_columns_are_read_through_and_accruals_is_inverted(self):
        frame = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=2),
                "close": [10.0, 11.0],
                "roe_avg": [0.05, 0.07],
                "gross_margin": [0.25, np.nan],
                "revenue_yoy": [0.10, 0.20],
                "profit_yoy": [0.30, -0.10],
                "cfo_to_np": [1.5, 0.4],
                "accruals": [0.02, -0.03],
            }
        )

        self.assertEqual(compute_factor(frame, "roe_ttm", {"window": 1}).tolist(), [0.05, 0.07])
        self.assertEqual(compute_factor(frame, "cfo_quality", {"window": 1}).tolist(), [1.5, 0.4])
        self.assertEqual(compute_factor(frame, "accruals", {"window": 1}).tolist(), [-0.02, 0.03])
        self.assertTrue(pd.isna(compute_factor(frame, "gross_margin", {"window": 1}).iloc[1]))

    def test_implementations_are_single_window_point_in_time_factors(self):
        library = {item["slug"]: item for item in FACTOR_LIBRARY}

        for implementation in self.NEW_IMPLEMENTATIONS:
            self.assertIn(implementation, ALLOWED_IMPLEMENTATIONS)
            self.assertIn(implementation, POINT_IN_TIME_IMPLEMENTATIONS)
            self.assertEqual(library[implementation]["default_window"], 1)
            self.assertNotIn(f"{implementation}_20d", library)
            # schema 白名单与实现注册表必须同步，否则前端注册会被 422 拦下
            FeatureCreate(
                name=implementation,
                slug=implementation,
                implementation=implementation,
                parameters={"window": 1},
            )
        self.assertEqual(library["roe_ttm"]["family"], "quality")
        self.assertIn(library["revenue_yoy"]["family"], {"growth", "quality"})

    def test_expression_language_accepts_fundamental_columns(self):
        validate_expression("roe_avg / turnover")
        validate_expression("log(cfo_to_np)")
        validate_expression("accruals")


if __name__ == "__main__":
    unittest.main()
