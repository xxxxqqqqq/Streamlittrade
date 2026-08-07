"""Redis Queue连接与回测入队函数。"""

from uuid import UUID

from redis import Redis
from rq import Queue
from rq.job import Job as RQJob

from backend.app.core.config import get_settings


QUEUE_NAME = "quant-backtests"
redis_sync = Redis.from_url(get_settings().redis_url)
backtest_queue = Queue(QUEUE_NAME, connection=redis_sync, default_timeout=900)


def enqueue_backtest(job_id: UUID) -> None:
    """只向Redis发送数据库任务ID，完整参数由Worker从PostgreSQL读取。

    这种设计避免Redis消息和数据库参数出现两个互相冲突的版本。
    """
    backtest_queue.enqueue(
        "backend.app.workers.backtest.execute_backtest",
        str(job_id),
        job_id=str(job_id),
        result_ttl=3600,
        failure_ttl=86400,
    )


def enqueue_task(job_id: UUID, function_path: str) -> None:
    """将数据集或训练任务放入同一研究队列。"""
    backtest_queue.enqueue(function_path, str(job_id), job_id=str(job_id), result_ttl=3600, failure_ttl=86400)


def cancel_queued_task(job_id: UUID) -> None:
    """尽力从 Redis 队列取消任务；已运行任务由 Worker 协作停止。"""
    try:
        RQJob.fetch(str(job_id), connection=redis_sync).cancel()
    except Exception:
        # PostgreSQL 的 cancel_requested 状态仍是权威指令，RQ记录可能已过期。
        return


def enqueue_by_kind(job_id: UUID, kind: str) -> None:
    paths = {
        "backtest": "backend.app.workers.backtest.execute_backtest",
        "dataset": "backend.app.workers.research.build_dataset",
        "training": "backend.app.workers.research.train_experiment",
        "sealed_evaluation": "backend.app.workers.research.evaluate_sealed_model",
        "data_sync": "backend.app.workers.data_catalog.sync_data",
        "feature_materialize": "backend.app.workers.data_catalog.materialize_features",
    }
    if kind not in paths:
        raise ValueError(f"不支持重试的任务类型: {kind}")
    enqueue_task(job_id, paths[kind])
