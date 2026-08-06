"""Contracts for the model-to-trade workbench."""

from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field, model_validator


class WorkbenchContextRead(BaseModel):
    model: dict[str, Any]
    research: dict[str, Any]
    prediction_target: dict[str, Any]
    evaluation: dict[str, Any]
    universe: list[str]
    features: list[str]
    backtests: list[dict[str, Any]]
    active_backtest: dict[str, Any] | None = None


class SignalSeriesRead(BaseModel):
    model_id: str
    symbol: str
    evaluation_scope: str = "cv_oos"
    rows: list[dict[str, Any]]


class SymbolTimelineRead(BaseModel):
    model_id: str
    backtest_id: str
    symbol: str
    artifact_schema_version: int
    context: dict[str, Any]
    bars: list[dict[str, Any]]
    signals: list[dict[str, Any]]
    factors: list[dict[str, Any]]
    events: list[dict[str, Any]]


class SnapshotBacktestCreate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    initial_cash: Decimal = Field(default=Decimal("1000000"), gt=0, le=Decimal("1000000000"))
    top_n: int = Field(default=5, ge=1, le=100)
    minimum_probability: float = Field(default=0.55, ge=0, le=1)
    rebalance_frequency: int = Field(default=5, ge=1, le=60)
    max_volume_participation: float = Field(default=0.05, gt=0, le=1)
    lot_size: int = Field(default=100, ge=100, le=10000)
    commission: float = Field(default=0.0003, ge=0, le=0.05)
    minimum_commission: float = Field(default=5.0, ge=0, le=1000)
    stamp_duty: float = Field(default=0.0005, ge=0, le=0.05)
    slippage: float = Field(default=0.001, ge=0, le=0.1)

    @model_validator(mode="after")
    def validate_window(self):
        if self.start_date and self.end_date and self.start_date >= self.end_date:
            raise ValueError("start_date must be earlier than end_date")
        if self.lot_size % 100:
            raise ValueError("lot_size must be a multiple of 100")
        return self
