"""容器与负载均衡器使用的健康检查接口。"""

from fastapi import APIRouter, Response, status

from backend.app.core.config import get_settings
from backend.app.schemas.health import LivenessResponse, ReadinessResponse
from backend.app.services.health import check_dependencies


router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """只证明API进程能够响应，不受数据库短暂故障影响。"""
    settings = get_settings()
    return LivenessResponse(service=settings.app_name, version=settings.app_version)


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(response: Response) -> ReadinessResponse:
    """数据库或Redis不可用时返回503，阻止负载均衡继续导入业务流量。"""
    ready, checks = await check_dependencies()
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if ready else "degraded", checks=checks)
