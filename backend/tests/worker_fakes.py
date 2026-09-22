"""Worker 集成测试用的最小替身：不依赖外部数据库与对象存储。

替身只实现 worker 真正调用的接口（get/add/commit），让任务函数可以在内存里
跑完整流程，从而验证落库的 metrics / reproducibility 契约，而不是只验证孤立
的辅助函数。
"""

from types import SimpleNamespace
from uuid import uuid4


class FakeSyncSession:
    def __init__(self, store):
        self.store, self.added = store, []

    def get(self, model, key):
        return self.store.get((model, key))

    def add(self, item):
        self.added.append(item)

    def commit(self):
        pass


class FakeSessionFactory:
    """既可调用又可作上下文管理器的同步会话工厂替身。"""

    def __init__(self, store):
        self.store, self.added = store, []

    def __call__(self):
        return self

    def __enter__(self):
        return FakeSyncSession(self.store)

    def __exit__(self, *exc_info):
        return False


def fake_job(**overrides):
    """带完整 worker 生命周期字段的任务替身（mark_running/heartbeat 会写这些字段）。"""

    values = {
        "id": uuid4(), "project_id": uuid4(), "status": "queued", "progress": 0, "payload": {},
        "started_at": None, "attempt": 0, "worker_name": None, "worker_heartbeat_at": None,
        "lease_expires_at": None, "error_message": None, "result_summary": None, "completed_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)
