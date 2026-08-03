"""RQ Worker使用的同步SQLAlchemy会话。

API使用AsyncSession；RQ任务本身是同步进程，因此使用独立同步会话更直接，也
避免在多个任务之间反复创建和销毁事件循环。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings


sync_engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SyncSessionFactory = sessionmaker(sync_engine, class_=Session, expire_on_commit=False)
