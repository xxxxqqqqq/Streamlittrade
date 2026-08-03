"""API v1 总路由。

后续用户、策略、数据集、实验和模型路由都在此聚合，避免全部堆进 main.py。
"""

from fastapi import APIRouter

from backend.app.api.backtests import router as backtests_router
from backend.app.api.research import router as research_router
from backend.app.api.auth import router as auth_router
from backend.app.api.realtime import router as realtime_router
from backend.app.api.paper import router as paper_router
from backend.app.api.monitoring import router as monitoring_router
from backend.app.api.data_catalog import router as data_catalog_router
from backend.app.api.projects import router as projects_router
from backend.app.api.operations import router as operations_router
from backend.app.api.product import router as product_router


api_router = APIRouter()
api_router.include_router(backtests_router)
api_router.include_router(research_router)
api_router.include_router(auth_router)
api_router.include_router(realtime_router)
api_router.include_router(paper_router)
api_router.include_router(monitoring_router)
api_router.include_router(data_catalog_router)
api_router.include_router(projects_router)
api_router.include_router(operations_router)
api_router.include_router(product_router)


@api_router.get("/system/info", tags=["system"])
async def system_info() -> dict[str, str]:
    """供Vue确认后端API版本和服务身份。"""
    return {"service": "quant-platform-api", "api_version": "v1"}
