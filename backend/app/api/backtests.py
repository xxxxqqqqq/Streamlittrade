"""回测提交、任务状态与结果查询接口。"""

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from backend.app.models.job import Job, OutboxEvent
from backend.app.models.backtest import BacktestRun
from backend.app.models.data_catalog import DataVersion, FeatureSnapshot
from backend.app.models.research import Dataset, Experiment, ModelVersion, SealedEvaluation, Strategy

from backend.app.db.session import get_db_session
from backend.app.schemas.backtest import (
    BacktestCreate,
    BacktestRead,
    BacktestSubmission,
    JobRead,
)
from backend.app.services.backtests import (
    create_backtest,
    get_backtest_or_404,
    get_job_or_404,
)
from backend.app.core.security import get_current_user
from backend.app.models.identity import AuditLog, User
from backend.app.infrastructure.queue import cancel_queued_task
from datetime import UTC, datetime
from backend.app.core.projects import ProjectContext, get_project_context
from backend.app.services.model_backtest_gate import prediction_window, sealed_portfolio_protocol


router = APIRouter(tags=["backtests"], dependencies=[Depends(get_current_user)])


@router.get("/jobs", response_model=list[JobRead])
async def list_jobs(session: AsyncSession = Depends(get_db_session),context:ProjectContext=Depends(get_project_context)) -> list[JobRead]:
    items = (await session.scalars(select(Job).where(Job.project_id==context.project.id).order_by(Job.created_at.desc()).limit(100))).all()
    return [JobRead.model_validate(item) for item in items]


@router.get("/backtests", response_model=list[BacktestRead])
async def list_backtests(session: AsyncSession = Depends(get_db_session),context:ProjectContext=Depends(get_project_context)) -> list[BacktestRead]:
    items = (await session.scalars(select(BacktestRun).where(BacktestRun.project_id==context.project.id).order_by(BacktestRun.created_at.desc()).limit(100))).all()
    return [BacktestRead.model_validate(item) for item in items]


@router.post("/backtests", response_model=BacktestSubmission, status_code=status.HTTP_202_ACCEPTED)
async def submit_backtest(
    request: BacktestCreate,
    session: AsyncSession = Depends(get_db_session),
    context:ProjectContext=Depends(get_project_context),
) -> BacktestSubmission:
    """创建异步回测；接口立即返回ID，不等待计算完成。"""
    if request.signal_source=="model_oos":
        row=(await session.execute(
            select(ModelVersion,Experiment)
            .join(Experiment,Experiment.id==ModelVersion.experiment_id)
            .where(
                ModelVersion.id==request.model_id,
                Experiment.project_id==context.project.id,
            )
        )).first()
        if row is None:
            raise HTTPException(404,"模型不存在或不属于当前项目")
        model,experiment=row
        if request.prediction_scope == "tuning_oos" and not model.prediction_artifact_uri:
            raise HTTPException(409,"该模型没有调参区样本外预测产物，不能进行可信模型回测")
        dataset=await session.get(Dataset,experiment.dataset_id)
        snapshot=(
            await session.get(FeatureSnapshot,dataset.feature_snapshot_id)
            if dataset and dataset.feature_snapshot_id else None
        )
        if (
            dataset is None
            or snapshot is None
            or snapshot.project_id!=context.project.id
            or snapshot.status!="ready"
        ):
            raise HTTPException(409,"模型必须来自当前项目的正式特征快照")
        request.data_version_id=snapshot.data_version_id
        sealed_evaluation = None
        sealed_metrics = None
        if request.prediction_scope == "sealed_oos":
            sealed_evaluation = await session.scalar(
                select(SealedEvaluation).where(
                    SealedEvaluation.model_id == model.id,
                    SealedEvaluation.dataset_id == dataset.id,
                    SealedEvaluation.status == "succeeded",
                )
            )
            if sealed_evaluation is None or not sealed_evaluation.artifact_uri:
                raise HTTPException(409,"该模型尚未完成最终封存区评估")
            sealed_metrics = dict(sealed_evaluation.metrics or {})
        try:
            allowed_start, allowed_end = prediction_window(
                dict(model.metrics or {}), sealed_metrics, request.prediction_scope
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        # 模型回测必须覆盖完整的不可变 OOS 区间，禁止手工截取表现较好的日期。
        request.start_date = datetime.strptime(allowed_start, "%Y-%m-%d").date()
        request.end_date = datetime.strptime(allowed_end, "%Y-%m-%d").date()
        if request.prediction_scope == "sealed_oos":
            protocol, protocol_source = sealed_portfolio_protocol(sealed_metrics)
            for field, value in protocol.items():
                setattr(request, field, value)
            request.portfolio_protocol_source = protocol_source
        else:
            request.portfolio_protocol_source = "tuning_user_configurable"
        request.strategy_name="model_probability"
        request.strategy_parameters={
            "top_n":request.top_n,
            "minimum_probability":request.minimum_probability,
            "rebalance_frequency":request.rebalance_frequency,
        }
    elif request.strategy_id:
        strategy=await session.scalar(
            select(Strategy).where(
                Strategy.id==request.strategy_id,
                Strategy.project_id==context.project.id,
            )
        )
        if strategy is None:
            raise HTTPException(404,"策略版本不存在")
        request.strategy_name=strategy.implementation
        request.strategy_parameters=dict(strategy.parameters)
    if request.data_source=="data_version":
        version=await session.scalar(
            select(DataVersion).where(
                DataVersion.id==request.data_version_id,
                DataVersion.project_id==context.project.id,
            )
        )
        if version is None or version.layer!="standardized" or version.status!="ready":
            raise HTTPException(409,"必须选择当前项目内已就绪的标准化数据版本")
        available={str(symbol) for symbol in version.specification.get("symbols",[])}
        if request.run_type=="portfolio":
            selected=set(request.symbols) if request.symbols else available
            if not selected or not selected.issubset(available):
                raise HTTPException(409,"回测股票池必须属于所选数据版本")
            request.symbols=sorted(selected)
            request.symbol=(
                "MODEL_OOS" if request.signal_source=="model_oos"
                else ",".join(request.symbols)
            )
        elif not request.symbol or request.symbol=="DATA_VERSION" or request.symbol not in available:
            raise HTTPException(409,"单标的回测代码必须属于所选数据版本")
    job, run = await create_backtest(session, request, owner_id=context.user.id, project_id=context.project.id)
    return BacktestSubmission(job_id=job.id, backtest_id=run.id)


@router.get("/jobs/{job_id}", response_model=JobRead)
async def read_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    context:ProjectContext=Depends(get_project_context),
) -> JobRead:
    """查询queued/running/succeeded/failed及0到100的进度。"""
    return JobRead.model_validate(await get_job_or_404(session, job_id, context.project.id))


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
async def cancel_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
    context:ProjectContext=Depends(get_project_context),
) -> JobRead:
    """取消排队任务；运行中任务在下一个安全阶段边界停止。"""
    job = await get_job_or_404(session, job_id, context.project.id)
    if job.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="只有排队或运行中的任务可以取消")
    job.status = "canceled" if job.status == "queued" else "cancel_requested"
    job.error_message = "用户请求取消任务"
    session.add(AuditLog(actor_id=user.id, action="job.cancel", resource_type="job", resource_id=str(job.id), details={"kind": job.kind}))
    await session.commit()
    if job.status == "canceled":
        await run_in_threadpool(cancel_queued_task, job.id)
    await session.refresh(job)
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/retry", response_model=JobRead)
async def retry_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
    context:ProjectContext=Depends(get_project_context),
) -> JobRead:
    """使用数据库中保存的原始参数重新执行失败或取消任务。"""
    job = await get_job_or_404(session, job_id, context.project.id)
    if job.status not in {"failed", "canceled"}:
        raise HTTPException(status_code=409, detail="只有失败或已取消任务可以重试")
    job.status = "queued"
    job.progress = 0
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    outbox=await session.scalar(select(OutboxEvent).where(OutboxEvent.job_id==job.id))
    if outbox:
        outbox.status="pending";outbox.available_at=datetime.now(UTC);outbox.dispatched_at=None;outbox.last_error=None
    session.add(AuditLog(actor_id=user.id, action="job.retry", resource_type="job", resource_id=str(job.id), details={"kind": job.kind}))
    await session.commit()
    await session.refresh(job)
    return JobRead.model_validate(job)


@router.get("/backtests/{backtest_id}", response_model=BacktestRead)
async def read_backtest(
    backtest_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    context:ProjectContext=Depends(get_project_context),
) -> BacktestRead:
    """查询回测指标和MinIO/OSS产物地址。"""
    return BacktestRead.model_validate(await get_backtest_or_404(session, backtest_id, context.project.id))


@router.get("/backtests/{backtest_id}/artifact", response_model=dict[str, Any])
async def read_backtest_artifact(
    backtest_id: UUID,
    session: AsyncSession = Depends(get_db_session),
    context:ProjectContext=Depends(get_project_context),
) -> dict[str, Any]:
    """通过API读取回测明细，避免浏览器直接接触对象存储凭据。"""
    run = await get_backtest_or_404(session, backtest_id, context.project.id)
    if not run.artifact_uri:
        raise HTTPException(status_code=409, detail="回测结果尚未生成")
    prefix = "s3://quant-artifacts/"
    if not run.artifact_uri.startswith(prefix):
        raise HTTPException(status_code=500, detail="回测产物地址格式无效")
    # 延迟加载基础设施适配器，使 OpenAPI 契约测试不要求连接或安装 MinIO。
    from backend.app.infrastructure.object_storage import download_bytes

    payload = await run_in_threadpool(download_bytes, run.artifact_uri)
    return json.loads(payload.decode("utf-8"))
