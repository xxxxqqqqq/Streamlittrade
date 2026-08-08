"""Disabled-by-default broker connection and readiness contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BrokerConnectionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    paper_account_id: UUID
    provider: str = Field(min_length=2, max_length=60, pattern=r"^[a-z][a-z0-9_]*$")
    environment: Literal["sandbox", "live"] = "sandbox"
    credential_secret_ref: str | None = Field(default=None, max_length=160, pattern=r"^env:QUANT_BROKER_[A-Z0-9_]+$")


class BrokerConnectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    paper_account_id: UUID
    name: str
    provider: str
    environment: str
    credential_secret_ref: str | None
    status: str
    dry_run: bool
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime


class LiveReadinessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    connection_id: UUID
    eligible: bool
    checks: dict[str, Any]
    policy_version: str
    created_at: datetime


class DryRunApproval(BaseModel):
    acknowledgement: Literal["I_UNDERSTAND_NO_LIVE_ORDERS"]
