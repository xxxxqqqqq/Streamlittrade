"""不依赖外部数据库的API契约测试。"""

import unittest

from httpx import ASGITransport, AsyncClient

from backend.app.main import app


class ApplicationContractTests(unittest.IsolatedAsyncioTestCase):
    """直接通过 ASGI 调用应用，无需启动端口或依赖外部服务。"""

    async def asyncSetUp(self):
        self.client = AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_liveness_contract(self):
        response = await self.client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertIn("service", payload)
        self.assertIn("version", payload)

    async def test_versioned_system_route(self):
        response = await self.client.get("/api/v1/system/info")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["api_version"], "v1")

    async def test_openapi_contains_foundation_routes(self):
        document = (await self.client.get("/openapi.json")).json()

        self.assertIn("/health/live", document["paths"])
        self.assertIn("/health/ready", document["paths"])
        self.assertIn("/api/v1/system/info", document["paths"])
        self.assertIn("/api/v1/backtests", document["paths"])
        self.assertIn("/api/v1/jobs/{job_id}", document["paths"])
        self.assertIn("/api/v1/backtests/{backtest_id}", document["paths"])
        self.assertIn("/api/v1/backtests/{backtest_id}/artifact", document["paths"])
        self.assertIn("/api/v1/strategies", document["paths"])
        self.assertIn("/api/v1/datasets", document["paths"])
        self.assertIn("/api/v1/experiments", document["paths"])
        self.assertIn("/api/v1/models", document["paths"])
        self.assertIn("/api/v1/jobs", document["paths"])
        self.assertIn("/api/v1/auth/login", document["paths"])
        self.assertIn("/api/v1/auth/me", document["paths"])
        self.assertIn("/api/v1/audit-logs", document["paths"])
        self.assertIn("/api/v1/jobs/{job_id}/cancel", document["paths"])
        self.assertIn("/api/v1/jobs/{job_id}/retry", document["paths"])
        self.assertIn("/api/v1/models/{model_id}/stage", document["paths"])
        self.assertIn("/api/v1/models/{model_id}/rollback", document["paths"])
        self.assertIn("/api/v1/models/{model_id}/sealed-evaluation", document["paths"])
        self.assertIn("/api/v1/models/production", document["paths"])
        self.assertIn(
            "/api/v1/models/production/{algorithm}/predictions",
            document["paths"],
        )
        self.assertIn("/api/v1/predictions", document["paths"])
        self.assertIn(
            "/api/v1/predictions/{prediction_id}/artifact",
            document["paths"],
        )
        self.assertIn("/api/v1/paper/accounts", document["paths"])
        self.assertIn("/api/v1/paper/accounts/{account_id}/orders", document["paths"])
        self.assertIn("/api/v1/paper/accounts/{account_id}/settle", document["paths"])
        self.assertIn("/api/v1/monitoring/overview", document["paths"])
        self.assertIn("/api/v1/prediction-schedules", document["paths"])
        self.assertIn("/api/v1/paper-automation-schedules", document["paths"])
        self.assertIn("/api/v1/paper-automation-runs", document["paths"])
        self.assertIn("/api/v1/broker-safety/connections", document["paths"])
        self.assertIn("/api/v1/broker-safety/connections/{connection_id}/evaluate", document["paths"])
        self.assertIn("/api/v1/broker-safety/connections/{connection_id}/preview", document["paths"])
        self.assertIn(
            "/api/v1/prediction-schedules/{schedule_id}/run",
            document["paths"],
        )
        self.assertIn("/api/v1/monitoring/drift-runs", document["paths"])
        self.assertIn("/api/v1/monitoring/alerts", document["paths"])
        self.assertIn(
            "/api/v1/monitoring/alerts/{alert_id}",
            document["paths"],
        )
        self.assertIn("/api/v1/users/{user_id}", document["paths"])
        self.assertIn(
            "/api/v1/projects/{project_id}/members",
            document["paths"],
        )
        self.assertIn(
            "/api/v1/projects/{project_id}/members/{member_id}",
            document["paths"],
        )
        self.assertIn(
            "/api/v1/data-center/versions/{version_id}",
            document["paths"],
        )
        self.assertIn(
            "/api/v1/data-center/materializations/{snapshot_id}",
            document["paths"],
        )
        self.assertIn("/api/v1/data-center/factor-library", document["paths"])
        self.assertIn("/api/v1/data-center/factor-research", document["paths"])
        self.assertIn(
            "/api/v1/data-center/factor-research/{research_id}",
            document["paths"],
        )
        self.assertIn("/api/v1/search", document["paths"])
        self.assertIn("/api/v1/notifications", document["paths"])


if __name__ == "__main__":
    unittest.main()
