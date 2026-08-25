"""RQ Worker entrypoint for a named, explicitly scoped compute node."""

import os
import socket

from redis import Redis
from rq import Queue, Worker

from backend.app.core.config import get_settings


def main() -> None:
    """持续消费回测队列；每个任务状态另外持久化到PostgreSQL。"""
    settings = get_settings()
    connection = Redis.from_url(settings.redis_url)
    queues = [Queue(name, connection=connection) for name in settings.worker_queue_names]
    identity = settings.worker_name.strip() or f"{socket.gethostname()}-{os.getpid()}"
    Worker(queues, connection=connection, name=identity).work(with_scheduler=False)


if __name__ == "__main__":
    main()
