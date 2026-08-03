"""Contracts for production prediction schedules, drift runs, and alerts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    algorithm: Literal["hist_gradient_boosting", "random_forest", "logistic_regression"]
    feature_snapshot_id: UUID
    interval_minutes: int = Field(default=1440, ge=5, le=10080)
    enabled: bool = True


class ScheduleUpdate(BaseModel):
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    enabled: bool | None = None


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    algorithm: str
    feature_snapshot_id: UUID
    interval_minutes: int
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None
    last_job_id: UUID | None
    created_at: datetime


class DriftCreate(BaseModel):
    model_id: UUID
    current_snapshot_id: UUID


class DriftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    job_id: UUID
    model_id: UUID
    baseline_snapshot_id: UUID
    current_snapshot_id: UUID
    status: str
    alert_level: str
    metrics: dict[str, Any] | None
    error_message: str | None
    created_at: datetime


class AlertUpdate(BaseModel):
    status: Literal["acknowledged", "resolved"]


class AlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    drift_run_id: UUID | None
    code: str
    severity: str
    title: str
    message: str
    status: str
    details: dict[str, Any]
    acknowledged_by: UUID | None
    acknowledged_at: datetime | None
    created_at: datetime

