"""API容器入口：先执行数据库迁移，再启动Uvicorn。"""

import os
import sys

from alembic import command
from alembic.config import Config


def main() -> None:
    """迁移失败时立即退出，避免API在错误表结构上继续接收请求。"""
    command.upgrade(Config("backend/alembic.ini"), "head")
    os.execv(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host=0.0.0.0",
            "--port=8000",
        ],
    )


if __name__ == "__main__":
    main()
