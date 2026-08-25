"""Redis Queue connections and reversible light/heavy task routing."""

from uuid import UUID

from redis import Redis
from rq import Queue
from rq.job import Job as RQJob

from backend.app.core.config import get_settings


settings = get_settings()
QUEUE_NAME = settings.legacy_queue_name
LIGHT_QUEUE_NAME = settings.light_queue_name
HEAVY_QUEUE_NAME = settings.heavy_queue_name
redis_sync = Redis.from_url(settings.redis_url)

# Keep this public alias for old callers and rollback deployments.  Split mode
# selects another queue per task without making existing Redis jobs unreadable.
backtest_queue = Queue(
    QUEUE_NAME,
    connection=redis_sync,
    default_timeout=settings.light_job_timeout_seconds,
)

HEAVY_FUNCTIONS = frozenset(
    {
        "backend.app.workers.data_catalog.materialize_features",
        "backend.app.workers.data_catalog.research_factors",
        "backend.app.workers.research.build_dataset",
        "backend.app.workers.research.train_experiment",
        "backend.app.workers.research.evaluate_sealed_model",
        "backend.app.workers.research.run_batch_prediction",
        "backend.app.workers.backtest.execute_backtest",
        "backend.app.workers.monitoring.run_drift_monitor",
    }
)


def queue_name_for_task(function_path: str) -> str:
    """Return a stable queue name while preserving the legacy rollback mode."""

    if settings.queue_mode != "split":
        return settings.legacy_queue_name
    return settings.heavy_queue_name if function_path in HEAVY_FUNCTIONS else settings.light_queue_name


def timeout_for_task(function_path: str) -> int:
    return (
        settings.heavy_job_timeout_seconds
        if function_path in HEAVY_FUNCTIONS
        else settings.light_job_timeout_seconds
    )


def enqueue_backtest(job_id: UUID) -> None:
    """只向Redis发送数据库任务ID，完整参数由Worker从PostgreSQL读取。

    这种设计避免Redis消息和数据库参数出现两个互相冲突的版本。
    """
    enqueue_task(job_id, "backend.app.workers.backtest.execute_backtest")


def enqueue_task(job_id: UUID, function_path: str, queue_name: str | None = None) -> None:
    """Enqueue a committed database job on its explicit execution class."""

    resolved_name = queue_name or queue_name_for_task(function_path)
    queue = Queue(
        resolved_name,
        connection=redis_sync,
        default_timeout=timeout_for_task(function_path),
    )
    queue.enqueue(
        function_path,
        str(job_id),
        job_id=str(job_id),
        job_timeout=timeout_for_task(function_path),
        result_ttl=3600,
        failure_ttl=86400,
    )


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
        "factor_research": "backend.app.workers.data_catalog.research_factors",
        "paper_automation": "backend.app.workers.automation.run_paper_automation",
        "drift_monitor": "backend.app.workers.monitoring.run_drift_monitor",
    }
    if kind not in paths:
        raise ValueError(f"不支持重试的任务类型: {kind}")
    enqueue_task(job_id, paths[kind])
