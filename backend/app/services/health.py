"""基础设施就绪状态检查。"""

from sqlalchemy import text

from backend.app.db.session import engine
from backend.app.infrastructure.redis import redis_client


async def check_dependencies() -> tuple[bool, dict[str, str]]:
    """探测 PostgreSQL 与 Redis；一个失败即表示当前实例不应接收业务流量。"""
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        checks["postgresql"] = "ok"
    except Exception:
        # 健康接口不向外泄露连接串、主机名或数据库错误细节。
        checks["postgresql"] = "unavailable"

    try:
        checks["redis"] = "ok" if await redis_client.ping() else "unavailable"
    except Exception:
        checks["redis"] = "unavailable"

    return all(value == "ok" for value in checks.values()), checks
