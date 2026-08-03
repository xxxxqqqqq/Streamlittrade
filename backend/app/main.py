"""FastAPI 应用工厂和进程生命周期入口。"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.health import router as health_router
from backend.app.api.router import api_router
from backend.app.core.config import get_settings
from backend.app.db.session import engine
from backend.app.infrastructure.redis import redis_client
from backend.app.core.security import hash_password
from backend.app.db.session import AsyncSessionFactory
from backend.app.models.identity import Project, ProjectMember, User
from backend.app.models.data_catalog import DataSource
from sqlalchemy import select
from backend.app.infrastructure.outbox import outbox_loop
from backend.app.infrastructure.scheduler import scheduler_loop


async def ensure_bootstrap_admin() -> None:
    """开发环境幂等创建首个管理员，生产环境要求显式安全配置。"""
    settings = get_settings()
    if settings.app_env == "production":
        if settings.jwt_secret.get_secret_value().startswith("local-only"):
            raise RuntimeError("生产环境必须配置 QUANT_JWT_SECRET")
        if settings.bootstrap_admin_password.get_secret_value() == "quant-dev-admin":
            raise RuntimeError("生产环境必须配置 QUANT_BOOTSTRAP_ADMIN_PASSWORD")
    async with AsyncSessionFactory() as session:
        existing = await session.scalar(select(User).limit(1))
        if existing is None:
            session.add(
                User(
                    email=settings.bootstrap_admin_email.lower(),
                    display_name="平台管理员",
                    password_hash=hash_password(settings.bootstrap_admin_password.get_secret_value()),
                    role="admin",
                    is_active=True,
                )
            )
            await session.commit()


async def ensure_default_data_sources() -> None:
    """Register stable provider identities without storing credentials.

    Data sources are explicit execution targets.  Keeping both built-in
    providers available avoids the misleading situation where changing the
    provider in the registration form appears to change an existing source,
    while synchronization still references the previously selected source ID.
    """
    async with AsyncSessionFactory() as session:
        defaults = (
            {
                "name": "AKShare A股日线",
                "slug": "akshare-a-daily",
                "provider": "akshare",
                "configuration": {"adjust": "qfq", "interface": "stock_zh_a_hist"},
            },
            {
                "name": "Baostock A股日线",
                "slug": "baostock-a-daily",
                "provider": "baostock",
                "configuration": {"adjust": "qfq", "interface": "query_history_k_data_plus"},
            },
        )
        for definition in defaults:
            existing = await session.scalar(
                select(DataSource).where(DataSource.slug == definition["slug"])
            )
            if existing is None:
                session.add(
                    DataSource(
                        **definition,
                        asset_type="equity_daily",
                        status="active",
                    )
                )
        if session.new:
            await session.commit()


async def ensure_default_project() -> None:
    """Give the bootstrap user a project even on a freshly created database."""
    async with AsyncSessionFactory() as session:
        user = await session.scalar(select(User).order_by(User.created_at))
        if user is None:
            return
        membership = await session.scalar(select(ProjectMember).where(ProjectMember.user_id == user.id))
        if membership is None:
            project = Project(owner_id=user.id, name="默认研究项目", slug=f"default-{str(user.id)[:8]}")
            session.add(project); await session.flush()
            session.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))
            await session.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时保持客户端惰性连接，关闭时释放数据库和Redis连接池。"""
    await ensure_bootstrap_admin()
    await ensure_default_project()
    await ensure_default_data_sources()
    stop = asyncio.Event()
    dispatcher = asyncio.create_task(outbox_loop(stop))
    scheduler = asyncio.create_task(scheduler_loop(stop))
    yield
    stop.set()
    await asyncio.gather(dispatcher, scheduler)
    await redis_client.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    """创建可供生产服务器和测试分别实例化的 FastAPI 应用。"""
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router)
    application.include_router(api_router, prefix=settings.api_v1_prefix)
    return application


app = create_app()
