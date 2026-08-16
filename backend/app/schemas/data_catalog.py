"""Validated API contracts for the data catalog and feature platform."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from backend.app.schemas.names import reject_corrupted_display_name


class SourceCreate(BaseModel):
    name: str = Field(min_length=2,max_length=120); slug: str = Field(pattern=r"^[a-z0-9_-]+$")
    provider: Literal["demo","akshare","baostock"]; asset_type: Literal["equity_daily"]="equity_daily"
    configuration: dict[str,Any]=Field(default_factory=dict)
    _formal_name=field_validator("name")(reject_corrupted_display_name)
class SourceRead(SourceCreate):
    model_config=ConfigDict(from_attributes=True); id:UUID;status:str;created_at:datetime
class DynamicUniversePolicy(BaseModel):
    enabled:bool=True
    min_history_days:int=Field(default=120,ge=20,le=1000)
    min_price:float=Field(default=3.0,ge=0,le=100000)
    liquidity_lookback:int=Field(default=20,ge=5,le=252)
    min_avg_turnover:float=Field(default=1_000_000.0,ge=0)
    max_members:int=Field(default=100,ge=3,le=1000)
class SyncCreate(BaseModel):
    name:str=Field(default="A股日线研究数据",min_length=2,max_length=80)
    source_id:UUID;symbols:list[str]=Field(min_length=1,max_length=500);start_date:date;end_date:date
    universe_policy:DynamicUniversePolicy=Field(default_factory=DynamicUniversePolicy)
    _formal_name=field_validator("name")(reject_corrupted_display_name)
    @model_validator(mode="after")
    def check(self):
        if self.start_date>=self.end_date:raise ValueError("start_date must be earlier than end_date")
        return self
class VersionRead(BaseModel):
    model_config=ConfigDict(from_attributes=True);id:UUID;source_id:UUID;parent_id:UUID|None;job_id:UUID|None;layer:str;status:str;specification:dict[str,Any];artifact_uri:str|None;content_sha256:str|None;row_count:int|None;quality_report:dict[str,Any]|None;lineage:dict[str,Any];error_message:str|None;created_at:datetime
class FeatureCreate(BaseModel):
    name:str=Field(min_length=2,max_length=120);slug:str=Field(pattern=r"^[a-z0-9_-]+$");family:str="technical"
    implementation:Literal[
        "return","log_return","moving_average_bias","volatility","downside_volatility",
        "volume_ratio","rsi","price_position","atr","amplitude","overnight_gap",
        "illiquidity","skewness","momentum_acceleration","expression",
        "short_term_reversal","relative_strength_12_1","trend_quality","drawdown",
        "liquidity_trend","turnover_stability","volume_price_confirmation",
        "intraday_return","close_location","upper_shadow","lower_shadow","price_efficiency",
        "return_kurtosis","up_day_ratio","max_daily_return","min_daily_return",
        "volume_volatility","volume_momentum"
    ]
    parameters:dict[str,Any]=Field(default_factory=dict);description:str=""
    _formal_name=field_validator("name")(reject_corrupted_display_name)
    @model_validator(mode="after")
    def validate_parameters(self):
        from backend.app.services.factors import validate_factor_parameters
        try:self.parameters=validate_factor_parameters(self.implementation,self.parameters)
        except ValueError as exc:raise ValueError(str(exc)) from exc
        return self
class FeatureRead(FeatureCreate):
    model_config=ConfigDict(from_attributes=True);id:UUID;version:int;status:str;created_at:datetime
class FactorLibraryItem(BaseModel):
    slug:str;implementation:str;name:str;family:str;description:str;default_window:int
    parameters:dict[str,Any];source:str;reference_url:str
class MaterializeCreate(BaseModel):
    name:str=Field(min_length=2,max_length=120);data_version_id:UUID;feature_definition_ids:list[UUID]=Field(min_length=1,max_length=250)
    _formal_name=field_validator("name")(reject_corrupted_display_name)
class SnapshotRead(BaseModel):
    model_config=ConfigDict(from_attributes=True);id:UUID;data_version_id:UUID;job_id:UUID|None;name:str;status:str;feature_definition_ids:list[str];artifact_uri:str|None;content_sha256:str|None;row_count:int|None;profile:dict[str,Any]|None;lineage:dict[str,Any];error_message:str|None;created_at:datetime
class CatalogSubmission(BaseModel):
    job_id:UUID;resource_id:UUID;status:Literal["queued"]="queued"
class FactorResearchCreate(BaseModel):
    name:str=Field(min_length=2,max_length=120);snapshot_id:UUID
    forward_period:int=Field(default=5,ge=1,le=60)
    training_fraction:float=Field(default=.55,ge=.3,le=.8)
    quantiles:int=Field(default=5,ge=2,le=10)
    min_coverage:float=Field(default=.7,ge=0,le=1)
    min_abs_rank_ic:float=Field(default=.02,ge=0,le=1)
    min_ic_ir:float=Field(default=.2,ge=0,le=10)
    false_discovery_rate:float=Field(default=.05,gt=0,le=.25)
    min_ic_observations:int=Field(default=30,ge=10,le=1000)
    _formal_name=field_validator("name")(reject_corrupted_display_name)
class FactorResearchRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID;project_id:UUID|None;snapshot_id:UUID;job_id:UUID|None;name:str;status:str
    parameters:dict[str,Any];metrics:dict[str,Any]|None;selected_feature_slugs:list[str]
    error_message:str|None;created_at:datetime
