"""后端集中配置。

所有环境差异都通过 ``QUANT_`` 前缀的环境变量注入。业务代码不得直接散落地
读取 ``os.getenv``，这样本地、测试和阿里云部署使用同一套配置入口。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置及其安全默认值。"""

    model_config = SettingsConfigDict(
        env_prefix="QUANT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Quant Platform API"
    app_version: str = "0.1.0"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    docs_enabled: bool = True

    # 默认值只能用于本机开发；生产环境必须由部署系统注入强密码。
    database_url: str = "postgresql+psycopg://quant:quant_dev_password@localhost:5432/quant"
    redis_url: str = "redis://localhost:6379/0"

    # Queue routing keeps the current single-queue deployment available as a
    # rollback path while allowing CPU/memory-heavy jobs to run on a remote
    # compute worker.  Production switches to ``split`` only after the remote
    # worker is healthy.
    queue_mode: str = "legacy"
    legacy_queue_name: str = "quant-backtests"
    light_queue_name: str = "quant-light"
    heavy_queue_name: str = "quant-heavy"
    worker_queues: str = ""
    worker_name: str = ""
    light_job_timeout_seconds: int = 3600
    heavy_job_timeout_seconds: int = 28800
    worker_lease_seconds: int = 1800

    # Remote workers keep immutable inputs and resumable factor partitions on
    # local SSD.  Nothing in this directory is authoritative until its hash is
    # verified and the final artifact is committed in PostgreSQL/MinIO.
    worker_data_dir: Path = Path(".worker-data")
    object_storage_retry_attempts: int = 5

    object_storage_endpoint: str = "http://localhost:9000"
    object_storage_access_key: str = "quant_local"
    object_storage_secret_key: SecretStr = SecretStr("change_this_local_secret")
    object_storage_bucket: str = "quant-artifacts"

    cors_origins: list[str] = ["http://localhost:5173"]

    # 本地默认值只用于开发引导；生产部署必须通过环境变量覆盖。
    jwt_secret: SecretStr = SecretStr("local-only-change-this-jwt-secret")
    access_token_minutes: int = 60
    refresh_token_days: int = 30
    bootstrap_admin_email: str = "admin@quant.local"
    bootstrap_admin_password: SecretStr = SecretStr("quant-dev-admin")

    @property
    def worker_queue_names(self) -> list[str]:
        """Resolve the queues consumed by this process without hidden magic."""

        configured = [item.strip() for item in self.worker_queues.split(",") if item.strip()]
        if configured:
            return configured
        if self.queue_mode == "split":
            return [self.heavy_queue_name]
        return [self.legacy_queue_name]


@lru_cache
def get_settings() -> Settings:
    """每个进程只解析一次环境变量，测试可通过 ``cache_clear`` 重载。"""
    return Settings()
