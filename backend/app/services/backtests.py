"""Project-scoped backtest creation and lookup services."""

import uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.infrastructure.outbox import add_outbox
from backend.app.models.backtest import BacktestRun
from backend.app.models.job import Job
from backend.app.schemas.backtest import BacktestCreate


async def create_backtest(session:AsyncSession,request:BacktestCreate,*,owner_id,project_id)->tuple[Job,BacktestRun]:
    job_id,backtest_id=uuid.uuid4(),uuid.uuid4();payload=request.model_dump(mode="json")
    job=Job(id=job_id,owner_id=owner_id,project_id=project_id,kind="backtest",status="queued",progress=0.0,payload=payload)
    run=BacktestRun(
        id=backtest_id,project_id=project_id,job_id=job_id,
        data_version_id=request.data_version_id,strategy_id=request.strategy_id,model_id=request.model_id,
        signal_source=request.signal_source,
        portfolio_construction={
            "method":"cross_sectional_top_n",
            "weighting":"equal_weight",
            "prediction_scope":request.prediction_scope,
            "portfolio_protocol_source":request.portfolio_protocol_source,
            "date_policy":"complete_immutable_scope",
            "top_n":request.top_n,
            "minimum_probability":request.minimum_probability,
            "rebalance_frequency":request.rebalance_frequency,
        } if request.signal_source=="model_oos" else {},
        run_type=request.run_type,data_source=request.data_source,symbol=request.symbol,
        strategy_name=request.strategy_name,strategy_parameters=request.strategy_parameters,
        start_date=request.start_date,end_date=request.end_date,initial_cash=request.initial_cash,
    )
    session.add(job);await session.flush();session.add(run);add_outbox(session,job,"backend.app.workers.backtest.execute_backtest");await session.commit();await session.refresh(job);await session.refresh(run);return job,run


async def get_job_or_404(session:AsyncSession,job_id:uuid.UUID,project_id=None)->Job:
    query=select(Job).where(Job.id==job_id)
    if project_id is not None:query=query.where(Job.project_id==project_id)
    job=await session.scalar(query)
    if job is None:raise HTTPException(status_code=404,detail="Task not found")
    return job


async def get_backtest_or_404(session:AsyncSession,backtest_id:uuid.UUID,project_id=None)->BacktestRun:
    query=select(BacktestRun).where(BacktestRun.id==backtest_id)
    if project_id is not None:query=query.where(BacktestRun.project_id==project_id)
    run=await session.scalar(query)
    if run is None:raise HTTPException(status_code=404,detail="Backtest not found")
    return run
