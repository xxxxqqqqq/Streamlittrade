"""数据集、实验、模型和策略API契约。"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DatasetCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    data_source: Literal["feature_snapshot", "demo", "baostock"] = "demo"
    feature_snapshot_id: UUID | None = None
    factor_research_id: UUID | None = None
    symbols: list[str] = Field(default=["DEMO"], min_length=1, max_length=100)
    start_date: date = date(2018, 1, 1)
    end_date: date = date(2024, 12, 31)
    horizon: int = Field(default=5, ge=1, le=60)
    training_fraction: float = Field(default=0.55, ge=0.3, le=0.8)
    tuning_fraction: float = Field(default=0.25, ge=0.1, le=0.4)
    tuning_folds: int = Field(default=3, ge=2, le=6)
    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date >= self.end_date: raise ValueError("开始日期必须早于结束日期")
        if self.training_fraction + self.tuning_fraction > 0.9:
            raise ValueError("at least 10% of dates must remain in the final sealed region")
        if self.data_source == "feature_snapshot":
            if self.feature_snapshot_id is None: raise ValueError("正式数据集必须选择特征快照")
            if self.factor_research_id is None: raise ValueError("正式数据集必须绑定已通过的因子研究门禁")
        elif self.data_source == "demo": self.symbols = [f"DEMO{i+1}" for i in range(max(3, len(self.symbols)))]
        elif any(len(s) != 6 or not s.isdigit() for s in self.symbols): raise ValueError("真实股票代码必须是六位数字")
        return self


class ExperimentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    dataset_id: UUID
    algorithm: Literal["hist_gradient_boosting", "random_forest", "logistic_regression"] = "hist_gradient_boosting"
    parameters: dict[str, int | float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_algorithm_parameters(self):
        defaults = {
            "hist_gradient_boosting": {"max_iter": 150, "max_depth": 5, "learning_rate": 0.05},
            "random_forest": {"n_estimators": 300, "max_depth": 8, "min_samples_leaf": 5},
            "logistic_regression": {"C": 1.0, "max_iter": 500},
        }
        allowed = set(defaults[self.algorithm])
        unknown = set(self.parameters).difference(allowed)
        if unknown: raise ValueError(f"当前算法不支持参数: {sorted(unknown)}")
        self.parameters = {**defaults[self.algorithm], **self.parameters}
        if int(self.parameters.get("max_iter", 1)) <= 0: raise ValueError("max_iter 必须大于0")
        if "n_estimators" in self.parameters and int(self.parameters["n_estimators"]) < 10:
            raise ValueError("n_estimators 不能小于10")
        if "C" in self.parameters and float(self.parameters["C"]) <= 0:
            raise ValueError("C 必须大于0")
        return self


class RecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; name: str; status: str; created_at: datetime


class DatasetRead(RecordRead):
    job_id: UUID | None; feature_snapshot_id: UUID | None; factor_research_id: UUID | None; specification: dict[str, Any]; row_count: int | None; feature_count: int | None; artifact_uri: str | None; metadata_snapshot: dict[str, Any] | None; error_message: str | None


class ExperimentRead(RecordRead):
    job_id: UUID | None; dataset_id: UUID; algorithm: str; parameters: dict[str, Any]; metrics: dict[str, Any] | None; reproducibility: dict[str, Any] | None; error_message: str | None


class ModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; experiment_id: UUID; name: str; version: int; algorithm: str; artifact_uri: str; prediction_artifact_uri: str | None; metrics: dict[str, Any]; reproducibility: dict[str, Any]; stage: str; created_at: datetime


class SealedEvaluationCreate(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


class SealedEvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    dataset_id: UUID
    model_id: UUID
    job_id: UUID
    status: str
    reason: str
    metrics: dict[str, Any] | None
    content_sha256: str | None
    error_message: str | None
    created_at: datetime


class StrategyCreate(BaseModel):
    name: str
    slug: str = Field(pattern=r"^[a-z0-9_-]+$")
    implementation: Literal["right_trend", "v_shape"] = "right_trend"
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_builtin_parameters(self):
        defaults = {
            "right_trend": {"ma_short": 5, "ma_mid": 20, "ma_long": 60, "vol_ratio": 1.5},
            "v_shape": {"lookback": 10, "drop_threshold": 0.08, "rebound_threshold": 0.03, "confirm_days": 2, "vol_ratio": 1.5},
        }
        allowed = {
            "right_trend": {"ma_short","ma_mid","ma_long","vol_ratio","rsi_period","rsi_upper","rsi_lower","kdj_n","kdj_m1","kdj_m2"},
            "v_shape": {"lookback","drop_threshold","rebound_threshold","vol_ratio","confirm_days"},
        }[self.implementation]
        unknown = set(self.parameters).difference(allowed)
        if unknown: raise ValueError(f"策略参数不受支持: {sorted(unknown)}")
        self.parameters = {**defaults[self.implementation], **self.parameters}
        if self.implementation == "right_trend":
            short,middle,long=(int(self.parameters[key]) for key in ("ma_short","ma_mid","ma_long"))
            if not 2 <= short < middle < long <= 500:
                raise ValueError("均线必须满足 2 <= short < middle < long <= 500")
        elif not 3 <= int(self.parameters["lookback"]) <= 250:
            raise ValueError("lookback 必须在3到250之间")
        return self


class StrategyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; name: str; slug: str; implementation: str; description: str; strategy_type: str; parameters: dict[str, Any]; version: int; created_at: datetime


class TaskSubmission(BaseModel):
    job_id: UUID
    resource_id: UUID
    status: Literal["queued"] = "queued"


class ModelStageUpdate(BaseModel):
    stage: Literal["validated", "production", "archived"]
    reason: str = Field(min_length=3, max_length=500)


class ModelRollbackRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class PredictionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    model_id: UUID
    feature_snapshot_id: UUID


class ProductionPredictionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    feature_snapshot_id: UUID


class PredictionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    job_id: UUID
    model_id: UUID
    feature_snapshot_id: UUID
    name: str
    status: str
    artifact_uri: str | None
    row_count: int | None
    summary: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
