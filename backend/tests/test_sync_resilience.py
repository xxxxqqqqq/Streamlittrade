"""数据同步容错契约：单只股票无数据时跳过并记录，不再让整个任务失败。"""

import unittest
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

import pandas as pd

from backend.app.models.data_catalog import DataSource, DataVersion
from backend.app.models.job import Job
from backend.app.workers import data_catalog
from backend.tests.worker_fakes import FakeSessionFactory, fake_job
from quant_core.demo_data import generate_demo_stock_data
from quant_core.data import MarketDataError
from datetime import date


def _payload_store():
    job_id = uuid4()
    raw_id, standard_id, source_id = uuid4(), uuid4(), uuid4()
    job = fake_job(id=job_id, payload={
        "raw_version_id": str(raw_id), "standard_version_id": str(standard_id),
        "symbols": ["600519", "001280", "600036"],
        "start_date": "2020-01-01", "end_date": "2020-06-30",
    })
    source = SimpleNamespace(id=source_id, provider="baostock", slug="baostock-a-daily", configuration={})
    raw = SimpleNamespace(id=raw_id, source_id=source_id, status="queued",
                          artifact_uri=None, content_sha256=None, row_count=None, quality_report=None, lineage=None)
    standard = SimpleNamespace(id=standard_id, status="queued",
                               artifact_uri=None, content_sha256=None, row_count=None, quality_report=None, lineage=None)
    store = {
        (Job, job_id): job,
        (DataVersion, raw_id): raw,
        (DataVersion, standard_id): standard,
        (DataSource, source_id): source,
    }
    return job, raw, standard, store


def _fake_fetch(symbol, start, end):
    if symbol == "001280":
        raise MarketDataError("行情查询结果为空")
    return generate_demo_stock_data(date(2020, 1, 1), date(2020, 6, 30), seed=7)


class SyncSkipTests(unittest.TestCase):
    def test_symbols_without_data_are_skipped_and_recorded(self):
        job, raw, standard, store = _payload_store()
        with mock.patch.object(data_catalog, "SyncSessionFactory", FakeSessionFactory(store)), \
                mock.patch.object(data_catalog, "fetch_stock_data", _fake_fetch), \
                mock.patch.object(data_catalog, "upload_bytes", lambda name, content, content_type: f"s3://{name}"), \
                mock.patch.object(data_catalog, "_progress", lambda *a: None):
            data_catalog.sync_data(str(job.id))

        self.assertEqual(job.status, "succeeded")
        self.assertEqual(standard.status, "ready")
        skipped = standard.lineage["skipped_symbols"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["symbol"], "001280")
        self.assertIn("无数据已跳过", " ".join(standard.quality_report["warnings"]))
        self.assertEqual(standard.row_count, len(raw.artifact_uri) > 0 and standard.row_count or 0)

    def test_all_symbols_empty_fails_loudly(self):
        job, raw, standard, store = _payload_store()
        always_empty = mock.Mock(side_effect=MarketDataError("行情查询结果为空"))
        with mock.patch.object(data_catalog, "SyncSessionFactory", FakeSessionFactory(store)), \
                mock.patch.object(data_catalog, "fetch_stock_data", always_empty), \
                mock.patch.object(data_catalog, "upload_bytes", lambda name, content, content_type: f"s3://{name}"), \
                mock.patch.object(data_catalog, "_progress", lambda *a: None):
            with self.assertRaises(ValueError):
                data_catalog.sync_data(str(job.id))


if __name__ == "__main__":
    unittest.main()
