"""Contracts for production prediction schedules, drift runs, and alerts."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    algorithm: Literal["hist_gradient_boosting", "random_forest", "extra_trees", "logistic_regression"]
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


class PaperAutomationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    account_id: UUID
    algorithm: Literal["hist_gradient_boosting", "random_forest", "extra_trees", "logistic_regression"]
    interval_minutes: int = Field(default=1440, ge=30, le=10080)
    top_n: int = Field(default=5, ge=1, le=50)
    probability_threshold: float = Field(default=0.55, ge=0.5, le=0.99)
    gross_exposure: float = Field(default=0.95, gt=0, le=1)
    enabled: bool = False


class PaperAutomationUpdate(BaseModel):
    interval_minutes: int | None = Field(default=None, ge=30, le=10080)
    top_n: int | None = Field(default=None, ge=1, le=50)
    probability_threshold: float | None = Field(default=None, ge=0.5, le=0.99)
    gross_exposure: float | None = Field(default=None, gt=0, le=1)
    enabled: bool | None = None


class PaperAutomationScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    name: str
    algorithm: str
    interval_minutes: int
    top_n: int
    probability_threshold: float
    gross_exposure: float
    enabled: bool
    next_run_at: datetime
    last_run_at: datetime | None
    last_job_id: UUID | None
    created_at: datetime


class PaperAutomationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    schedule_id: UUID
    job_id: UUID
    account_id: UUID
    model_id: UUID
    feature_snapshot_id: UUID
    status: str
    signal_date: date | None
    intended_trade_date: date | None
    signals: list[dict[str, Any]] | None
    targets: list[dict[str, Any]] | None
    order_ids: list[str]
    lineage: dict[str, Any]
    error_message: str | None
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
