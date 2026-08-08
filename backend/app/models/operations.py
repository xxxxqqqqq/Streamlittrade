"""Production model scheduling, drift monitoring, and alert persistence."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class PredictionSchedule(Base):
    """Periodically score a fixed feature snapshot with the current production model."""

    __tablename__ = "prediction_schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    feature_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feature_snapshots.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PaperAutomationSchedule(Base):
    """Turn the newest compatible snapshot into reviewable paper-order proposals."""

    __tablename__ = "paper_automation_schedules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1440)
    top_n: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    probability_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.55)
    gross_exposure: Mapped[float] = mapped_column(Float, nullable=False, default=0.95)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class PaperAutomationRun(Base):
    """Immutable lineage for one signal date and its proposed paper orders."""

    __tablename__ = "paper_automation_runs"
    __table_args__ = (UniqueConstraint("schedule_id", "feature_snapshot_id", name="uq_paper_automation_schedule_snapshot"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper_automation_schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("paper_accounts.id", ondelete="RESTRICT"), nullable=False)
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False)
    feature_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("feature_snapshots.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    signal_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    intended_trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    signals: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    targets: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    order_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    lineage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DriftRun(Base):
    """Asynchronous comparison between a model's baseline and current feature snapshot."""

    __tablename__ = "drift_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    baseline_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feature_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    current_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("feature_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued", index=True)
    alert_level: Mapped[str] = mapped_column(String(20), nullable=False, default="none", index=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AlertEvent(Base):
    """Persistent, auditable operational alert with acknowledgement lifecycle."""

    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    drift_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("drift_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
