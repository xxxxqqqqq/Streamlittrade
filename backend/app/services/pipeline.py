"""一键研究流水线的服务端编排。

流水线把"特征快照 → 因子研究 → 数据集 → 训练 → 调参区回测"五步链式执行。
每一步仍是通过 outbox 派发的标准 Job，取消、超时、Worker 恢复语义与手工
创建完全一致；本模块只在任务落终态后创建下一步资源，不绕过任何既有门禁
（数据集因子门禁、模型回测的完整不可变 OOS 区间等全部沿用）。

推进动作只发生在 API 进程的 outbox 循环里，Worker 不感知流水线存在。
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from backend.app.db.sync_session import SyncSessionFactory
from backend.app.infrastructure.outbox import add_outbox
from backend.app.models.backtest import BacktestRun
from backend.app.models.data_catalog import DataVersion, FactorResearchRun, FeatureSnapshot
from backend.app.models.job import Job
from backend.app.models.research import (
    Dataset,
    Experiment,
    ModelVersion,
    ResearchPipeline,
)
from backend.app.schemas.backtest import BacktestCreate
from backend.app.schemas.data_catalog import FactorResearchCreate
from backend.app.schemas.research import DatasetCreate, ExperimentCreate
from backend.app.services.model_backtest_gate import prediction_window
from backend.app.services.research_gates import validate_factor_dataset_gate

PIPELINE_STEPS = ("materialize", "factor_research", "dataset", "training", "backtest")
STEP_LABELS = {
    "materialize": "特征快照",
    "factor_research": "因子研究",
    "dataset": "研究数据集",
    "training": "模型训练",
    "backtest": "调参区回测",
}

_MATERIALIZE_FUNC = "backend.app.workers.data_catalog.materialize_features"
_FACTOR_RESEARCH_FUNC = "backend.app.workers.data_catalog.research_factors"
_DATASET_FUNC = "backend.app.workers.research.build_dataset"
_TRAINING_FUNC = "backend.app.workers.research.train_experiment"
_BACKTEST_FUNC = "backend.app.workers.backtest.execute_backtest"


def build_pipeline_spec(inputs: dict[str, Any], first_step: str) -> dict[str, Any]:
    """初始化流水线编排状态；被跳过的步骤显式标记为 skipped。"""
    steps = {
        name: {"status": "pending", "job_id": None, "resource_id": None}
        for name in PIPELINE_STEPS
    }
    for name in PIPELINE_STEPS:
        if name == first_step:
            break
        steps[name]["status"] = "skipped"
    return {"inputs": inputs, "steps": steps}


def _step_name(base: str, suffix: str) -> str:
    return f"{base[:100]}-{suffix}"


def _record_step(pipeline: ResearchPipeline, spec: dict, step: str, job_id: uuid.UUID, resource_id: uuid.UUID) -> None:
    spec["steps"][step] = {"status": "queued", "job_id": str(job_id), "resource_id": str(resource_id)}
    pipeline.spec = spec
    pipeline.current_step = step
    pipeline.current_job_id = job_id


def _create_factor_research(session, pipeline: ResearchPipeline, spec: dict, snapshot_id: uuid.UUID) -> None:
    inputs = spec["inputs"]
    body = FactorResearchCreate(
        name=_step_name(pipeline.name, "因子研究"),
        snapshot_id=snapshot_id,
        forward_period=int(inputs["horizon"]),
        training_fraction=float(inputs["training_fraction"]),
    )
    job_id, run_id = uuid.uuid4(), uuid.uuid4()
    job = Job(
        id=job_id, owner_id=pipeline.owner_id, project_id=pipeline.project_id,
        kind="factor_research", status="queued", progress=0,
        payload={"factor_research_id": str(run_id)},
    )
    run = FactorResearchRun(
        id=run_id, project_id=pipeline.project_id, snapshot_id=snapshot_id,
        job_id=job_id, name=body.name, status="queued",
        parameters=body.model_dump(exclude={"name", "snapshot_id"}),
        selected_feature_slugs=[],
    )
    session.add(job)
    session.add(run)
    add_outbox(session, job, _FACTOR_RESEARCH_FUNC)
    _record_step(pipeline, spec, "factor_research", job_id, run_id)


def _create_dataset(session, pipeline: ResearchPipeline, spec: dict, run_id: uuid.UUID) -> None:
    inputs = spec["inputs"]
    run = session.get(FactorResearchRun, run_id)
    if run is None:
        raise ValueError("因子研究记录丢失")
    snapshot = session.get(FeatureSnapshot, run.snapshot_id)
    if snapshot is None or snapshot.status != "ready":
        raise ValueError("特征快照尚未就绪")
    validate_factor_dataset_gate(
        snapshot_id=snapshot.id,
        horizon=int(inputs["horizon"]),
        training_fraction=float(inputs["training_fraction"]),
        run_snapshot_id=run.snapshot_id,
        run_status=run.status,
        run_parameters=run.parameters,
        run_metrics=run.metrics,
        selected_feature_slugs=run.selected_feature_slugs,
    )
    profile = snapshot.profile or {}
    body = DatasetCreate(
        name=_step_name(pipeline.name, "数据集"),
        data_source="feature_snapshot",
        feature_snapshot_id=snapshot.id,
        factor_research_id=run.id,
        start_date=datetime.strptime(profile["date_min"], "%Y-%m-%d").date() if profile.get("date_min") else DatasetCreate.model_fields["start_date"].default,
        end_date=datetime.strptime(profile["date_max"], "%Y-%m-%d").date() if profile.get("date_max") else DatasetCreate.model_fields["end_date"].default,
        horizon=int(inputs["horizon"]),
        training_fraction=float(inputs["training_fraction"]),
    )
    job_id, dataset_id = uuid.uuid4(), uuid.uuid4()
    job = Job(
        id=job_id, owner_id=pipeline.owner_id, project_id=pipeline.project_id,
        kind="dataset", status="queued", progress=0,
        payload={"dataset_id": str(dataset_id)},
    )
    dataset = Dataset(
        id=dataset_id, project_id=pipeline.project_id, job_id=job_id,
        feature_snapshot_id=snapshot.id, factor_research_id=run.id,
        name=body.name, status="queued", specification=body.model_dump(mode="json"),
    )
    session.add(job)
    session.add(dataset)
    add_outbox(session, job, _DATASET_FUNC)
    _record_step(pipeline, spec, "dataset", job_id, dataset_id)


def _create_training(session, pipeline: ResearchPipeline, spec: dict, dataset_id: uuid.UUID) -> None:
    inputs = spec["inputs"]
    dataset = session.get(Dataset, dataset_id)
    if dataset is None or dataset.status != "ready":
        raise ValueError("研究数据集尚未就绪")
    body = ExperimentCreate(
        name=_step_name(pipeline.name, "实验"),
        dataset_id=dataset.id,
        algorithm=inputs["algorithm"],
        parameters=inputs.get("algorithm_parameters") or {},
    )
    job_id, experiment_id = uuid.uuid4(), uuid.uuid4()
    job = Job(
        id=job_id, owner_id=pipeline.owner_id, project_id=pipeline.project_id,
        kind="training", status="queued", progress=0,
        payload={"experiment_id": str(experiment_id)},
    )
    experiment = Experiment(id=experiment_id, project_id=pipeline.project_id, job_id=job_id, **body.model_dump())
    session.add(job)
    session.add(experiment)
    add_outbox(session, job, _TRAINING_FUNC)
    _record_step(pipeline, spec, "training", job_id, experiment_id)


def _create_backtest(session, pipeline: ResearchPipeline, spec: dict, experiment_id: uuid.UUID) -> None:
    inputs = spec["inputs"]
    model = session.scalar(select(ModelVersion).where(ModelVersion.experiment_id == experiment_id))
    if model is None or not model.prediction_artifact_uri:
        raise ValueError("训练未登记带样本外预测的模型版本")
    experiment = session.get(Experiment, experiment_id)
    dataset = session.get(Dataset, experiment.dataset_id)
    snapshot = session.get(FeatureSnapshot, dataset.feature_snapshot_id) if dataset else None
    if snapshot is None or snapshot.status != "ready":
        raise ValueError("模型的特征快照不可用")
    request = BacktestCreate(
        signal_source="model_oos",
        prediction_scope="tuning_oos",
        run_type="portfolio",
        data_source="data_version",
        data_version_id=snapshot.data_version_id,
        model_id=model.id,
        symbol="MODEL_OOS",
        top_n=int(inputs["top_n"]),
        minimum_probability=float(inputs["minimum_probability"]),
        rebalance_frequency=int(inputs["rebalance_frequency"]),
        initial_cash=Decimal(str(inputs["initial_cash"])),
    )
    # 与手动创建一致：回测强制覆盖为完整不可变调参区 OOS 区间，禁止挑选日期。
    allowed_start, allowed_end = prediction_window(dict(model.metrics or {}), None, "tuning_oos")
    request.start_date = datetime.strptime(allowed_start, "%Y-%m-%d").date()
    request.end_date = datetime.strptime(allowed_end, "%Y-%m-%d").date()
    request.strategy_name = "model_probability"
    request.strategy_parameters = {
        "top_n": request.top_n,
        "minimum_probability": request.minimum_probability,
        "rebalance_frequency": request.rebalance_frequency,
    }
    request.portfolio_protocol_source = "tuning_user_configurable"
    version = session.get(DataVersion, snapshot.data_version_id)
    request.symbols = sorted(str(s) for s in (version.specification.get("symbols", []) if version else []))
    job_id, backtest_id = uuid.uuid4(), uuid.uuid4()
    job = Job(
        id=job_id, owner_id=pipeline.owner_id, project_id=pipeline.project_id,
        kind="backtest", status="queued", progress=0.0,
        payload=request.model_dump(mode="json"),
    )
    run = BacktestRun(
        id=backtest_id, project_id=pipeline.project_id, job_id=job_id,
        data_version_id=request.data_version_id, strategy_id=None, model_id=request.model_id,
        signal_source="model_oos",
        portfolio_construction={
            "method": "cross_sectional_top_n",
            "weighting": "equal_weight",
            "prediction_scope": "tuning_oos",
            "portfolio_protocol_source": "tuning_user_configurable",
            "date_policy": "complete_immutable_scope",
            "top_n": request.top_n,
            "minimum_probability": request.minimum_probability,
            "rebalance_frequency": request.rebalance_frequency,
        },
        run_type="portfolio", data_source="data_version", symbol="MODEL_OOS",
        strategy_name="model_probability", strategy_parameters=request.strategy_parameters,
        start_date=request.start_date, end_date=request.end_date, initial_cash=request.initial_cash,
    )
    session.add(job)
    session.add(run)
    add_outbox(session, job, _BACKTEST_FUNC)
    _record_step(pipeline, spec, "backtest", job_id, backtest_id)


def create_first_step(session, pipeline: ResearchPipeline) -> None:
    """创建流水线首步任务；供 API 在提交事务前调用（不做 flush/commit）。"""
    spec = copy.deepcopy(pipeline.spec or {})
    inputs = spec["inputs"]
    if pipeline.current_step == "materialize":
        job_id, snapshot_id = uuid.uuid4(), uuid.uuid4()
        job = Job(
            id=job_id, owner_id=pipeline.owner_id, project_id=pipeline.project_id,
            kind="feature_materialize", status="queued", progress=0,
            payload={"snapshot_id": str(snapshot_id)},
        )
        snapshot = FeatureSnapshot(
            id=snapshot_id, project_id=pipeline.project_id,
            data_version_id=uuid.UUID(inputs["data_version_id"]), job_id=job_id,
            name=_step_name(pipeline.name, "特征快照"), status="queued",
            feature_definition_ids=list(inputs["feature_definition_ids"]),
            lineage={"data_version_id": inputs["data_version_id"]},
        )
        session.add(job)
        session.add(snapshot)
        add_outbox(session, job, _MATERIALIZE_FUNC)
        _record_step(pipeline, spec, "materialize", job_id, snapshot_id)
    elif pipeline.current_step == "factor_research":
        _create_factor_research(session, pipeline, spec, uuid.UUID(inputs["feature_snapshot_id"]))
    else:
        raise ValueError(f"非法的流水线首步: {pipeline.current_step}")


def _fail_pipeline(pipeline: ResearchPipeline, spec: dict, message: str) -> None:
    pipeline.status = "failed"
    pipeline.error_message = message[:2000]
    pipeline.completed_at = datetime.now(UTC)
    pipeline.spec = spec


def advance_pipeline_record(session, pipeline: ResearchPipeline) -> bool:
    """任务落终态后推进一步；返回是否发生了状态变化。

    成功创建下一步、流水线完成或失败都返回 True；当前任务仍在排队/运行返回 False。
    """
    spec = copy.deepcopy(pipeline.spec or {})
    step = pipeline.current_step
    job = session.get(Job, pipeline.current_job_id)
    if job is None:
        spec["steps"][step]["status"] = "failed"
        _fail_pipeline(pipeline, spec, f"步骤「{STEP_LABELS.get(step, step)}」的任务记录丢失")
        return True
    if job.status in ("queued", "running"):
        return False
    spec["steps"][step]["status"] = job.status
    if job.status in ("failed", "canceled"):
        pipeline.status = job.status
        pipeline.error_message = (
            f"步骤「{STEP_LABELS.get(step, step)}」{job.status}: {job.error_message or ''}"
        )[:2000]
        pipeline.completed_at = datetime.now(UTC)
        pipeline.spec = spec
        return True
    try:
        resource_id = spec["steps"][step]["resource_id"]
        if step == "materialize":
            _create_factor_research(session, pipeline, spec, uuid.UUID(resource_id))
        elif step == "factor_research":
            _create_dataset(session, pipeline, spec, uuid.UUID(resource_id))
        elif step == "dataset":
            _create_training(session, pipeline, spec, uuid.UUID(resource_id))
        elif step == "training":
            _create_backtest(session, pipeline, spec, uuid.UUID(resource_id))
        elif step == "backtest":
            pipeline.status = "succeeded"
            pipeline.current_step = "done"
            pipeline.completed_at = datetime.now(UTC)
            pipeline.spec = spec
        else:
            raise ValueError(f"未知的流水线步骤: {step}")
    except ValueError as exc:
        spec["steps"][step]["status"] = "succeeded"
        _fail_pipeline(pipeline, spec, f"步骤「{STEP_LABELS.get(step, step)}」之后无法继续: {exc}")
    return True


def advance_pipelines(limit: int = 20) -> int:
    """扫描运行中的流水线并推进；与 outbox 派发一样按行锁抢占，多副本安全。"""
    advanced = 0
    with SyncSessionFactory() as session:
        pipelines = list(
            session.scalars(
                select(ResearchPipeline)
                .where(ResearchPipeline.status == "running")
                .order_by(ResearchPipeline.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
        )
        for pipeline in pipelines:
            try:
                if advance_pipeline_record(session, pipeline):
                    advanced += 1
            except Exception as exc:  # 单条流水线异常不能阻塞其他流水线与 outbox 循环
                pipeline.status = "failed"
                pipeline.error_message = f"流水线推进异常: {exc}"[:2000]
                pipeline.completed_at = datetime.now(UTC)
                advanced += 1
        session.commit()
    return advanced
