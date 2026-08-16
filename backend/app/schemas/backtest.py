"""HTTP contracts for single-symbol and portfolio backtest jobs."""

from datetime import date, datetime
from decimal import Decimal
import math
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BacktestCreate(BaseModel):
    signal_source: Literal["strategy", "model_oos"] = "strategy"
    run_type: Literal["single", "portfolio"] = "single"
    data_source: Literal["data_version", "demo", "baostock"] = "demo"
    data_version_id: UUID | None = None
    strategy_id: UUID | None = None
    model_id: UUID | None = None
    symbol: str = Field(default="DEMO", min_length=1, max_length=20)
    symbols: list[str] = Field(default_factory=list, max_length=500)
    strategy_name: Literal["right_trend", "v_shape", "model_probability"] = "right_trend"
    strategy_parameters: dict[str, int | float] = Field(default_factory=dict)
    top_n: int = Field(default=10, ge=1, le=100)
    minimum_probability: float = Field(default=0.5, ge=0, le=1)
    rebalance_frequency: int = Field(default=5, ge=1, le=60)
    start_date: date = date(2020, 1, 1)
    end_date: date = date(2024, 12, 31)
    initial_cash: Decimal = Field(default=Decimal("100000"), gt=0, le=Decimal("1000000000"))
    max_positions: int = Field(default=10, ge=1, le=100)
    max_volume_participation: float = Field(default=0.05, gt=0, le=1)
    lot_size: int = Field(default=100, ge=100, le=10000)
    commission: float = Field(default=0.0003, ge=0, le=0.05)
    minimum_commission: float = Field(default=5.0, ge=0, le=1000)
    stamp_duty: float = Field(default=0.0005, ge=0, le=0.05)
    slippage: float = Field(default=0.001, ge=0, le=0.1)

    @model_validator(mode="after")
    def validate_business_rules(self):
        if self.start_date >= self.end_date: raise ValueError("start_date must be earlier than end_date")
        if self.lot_size % 100:
            raise ValueError("lot_size must be a multiple of 100")
        if (self.end_date - self.start_date).days > 365 * 20: raise ValueError("backtest range cannot exceed 20 years")
        if self.signal_source == "model_oos":
            if self.model_id is None:
                raise ValueError("model_oos backtest requires model_id")
            self.run_type = "portfolio"
            self.data_source = "data_version"
            self.strategy_id = None
            self.strategy_name = "model_probability"
            self.strategy_parameters = {
                "top_n": self.top_n,
                "minimum_probability": self.minimum_probability,
                "rebalance_frequency": self.rebalance_frequency,
            }
            self.symbol = "MODEL_OOS"
            return self
        if self.run_type == "portfolio":
            if self.data_source == "demo":
                requested = max(3, min(len(self.symbols) or 5, 20))
                self.symbols = [f"DEMO{i + 1}" for i in range(requested)]
            elif self.data_source == "baostock" and (not self.symbols or any(len(s) != 6 or not s.isdigit() for s in self.symbols)):
                raise ValueError("portfolio Baostock symbols must be six-digit codes")
            elif self.data_source == "data_version" and self.data_version_id is None:
                raise ValueError("versioned backtest requires data_version_id")
            self.symbol = ",".join(self.symbols) if self.symbols else "DATA_VERSION"
        elif self.data_source == "baostock":
            if len(self.symbol) != 6 or not self.symbol.isdigit(): raise ValueError("Baostock symbol must be a six-digit code")
        elif self.data_source == "data_version":
            if self.data_version_id is None: raise ValueError("versioned backtest requires data_version_id")
        else:
            self.symbol = "DEMO"
        allowed = {
            "right_trend": {"ma_short","ma_mid","ma_long","vol_ratio","rsi_period","rsi_upper","rsi_lower","kdj_n","kdj_m1","kdj_m2"},
            "v_shape": {"lookback","drop_threshold","rebound_threshold","vol_ratio","confirm_days"},
        }[self.strategy_name]
        unknown = set(self.strategy_parameters).difference(allowed)
        if unknown: raise ValueError(f"unknown strategy parameters: {sorted(unknown)}")
        if any(not math.isfinite(float(value)) for value in self.strategy_parameters.values()): raise ValueError("strategy parameters must be finite")
        if self.strategy_name == "right_trend":
            short, middle, long = (int(self.strategy_parameters.get(k, v)) for k,v in (("ma_short",5),("ma_mid",20),("ma_long",60)))
            if not 2 <= short < middle < long <= 500: raise ValueError("moving averages must satisfy 2 <= short < middle < long <= 500")
        elif not 3 <= int(self.strategy_parameters.get("lookback", 10)) <= 250: raise ValueError("lookback must be between 3 and 250")
        if not 0.1 <= float(self.strategy_parameters.get("vol_ratio", 1.5)) <= 20: raise ValueError("vol_ratio must be between 0.1 and 20")
        return self


class BacktestSubmission(BaseModel):
    job_id: UUID; backtest_id: UUID; status: Literal["queued"] = "queued"


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; kind: str; status: str; progress: float; result_summary: dict[str, Any] | None
    error_message: str | None; created_at: datetime; started_at: datetime | None; completed_at: datetime | None


class BacktestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; job_id: UUID; data_version_id: UUID | None; strategy_id: UUID | None; model_id: UUID | None
    signal_source: str; portfolio_construction: dict[str, Any]; run_type: str; data_source: str; symbol: str; strategy_name: str
    strategy_parameters: dict[str, Any]; start_date: date; end_date: date; initial_cash: Decimal
    metrics: dict[str, Any] | None; data_quality: dict[str, Any] | None; artifact_uri: str | None; created_at: datetime
