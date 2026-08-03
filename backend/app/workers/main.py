"""RQ Worker进程入口。"""

from redis import Redis
from rq import Queue, Worker

from backend.app.core.config import get_settings
from backend.app.infrastructure.queue import QUEUE_NAME


def main() -> None:
    """持续消费回测队列；每个任务状态另外持久化到PostgreSQL。"""
    connection = Redis.from_url(get_settings().redis_url)
    queue = Queue(QUEUE_NAME, connection=connection)
    Worker([queue], connection=connection).work(with_scheduler=False)


if __name__ == "__main__":
    main()
