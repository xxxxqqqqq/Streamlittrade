"""Shared database lifecycle helpers for observable remote workers."""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime, timedelta

from backend.app.core.config import get_settings


class TaskCanceled(RuntimeError):
    """Raised when the authoritative PostgreSQL job requests cancellation."""


def worker_identity() -> str:
    settings = get_settings()
    return settings.worker_name.strip() or f"{socket.gethostname()}-{os.getpid()}"


def lease_deadline() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=get_settings().worker_lease_seconds)


def mark_running(job, progress: float | None = None) -> None:
    """Stamp a claimed job with its compute node and renewable lease."""

    now = datetime.now(UTC)
    job.status = "running"
    if progress is not None:
        job.progress = progress
    if job.started_at is None:
        job.started_at = now
    job.attempt += 1
    job.worker_name = worker_identity()
    job.worker_heartbeat_at = now
    job.lease_expires_at = lease_deadline()
    job.error_message = None


def heartbeat(job, progress: float | None = None) -> None:
    """Renew a job lease and fail cooperatively at a safe checkpoint."""

    if job.status == "cancel_requested":
        job.status = "canceled"
        job.completed_at = datetime.now(UTC)
        job.lease_expires_at = None
        raise TaskCanceled("Task canceled by user")
    if progress is not None:
        job.progress = progress
    job.worker_name = worker_identity()
    job.worker_heartbeat_at = datetime.now(UTC)
    job.lease_expires_at = lease_deadline()


def mark_finished(job) -> None:
    job.completed_at = datetime.now(UTC)
    job.lease_expires_at = None
    job.worker_heartbeat_at = datetime.now(UTC)
