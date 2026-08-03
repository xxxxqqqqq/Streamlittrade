"""健康检查响应模型。"""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class LivenessResponse(BaseModel):
    """进程存活检查不访问任何外部服务。"""

    status: Literal["ok"] = "ok"
    service: str
    version: str
    # 使用带 UTC 时区的时间，避免无时区时间在多服务器部署时产生歧义。
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReadinessResponse(BaseModel):
    """就绪检查分别报告数据库和队列是否可用。"""

    status: Literal["ready", "degraded"]
    checks: dict[str, Literal["ok", "unavailable"]]
