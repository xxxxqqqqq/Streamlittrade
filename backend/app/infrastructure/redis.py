"""全进程复用的异步 Redis 连接池。"""

from redis.asyncio import Redis

from backend.app.core.config import get_settings


redis_client = Redis.from_url(
    get_settings().redis_url,
    encoding="utf-8",
    decode_responses=True,
)
