"""所有 SQLAlchemy ORM 模型共享的声明式基类。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Alembic 后续会从该 metadata 自动发现数据表。"""
