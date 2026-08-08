"""Paper-stability gate and non-transmitting broker preview API."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.projects import ProjectContext, get_project_context
from backend.app.core.security import get_current_user, require_admin
from backend.app.db.session import get_db_session
from backend.app.models.broker import BrokerConnection, LiveReadinessEvaluation
from backend.app.models.identity import AuditLog, User
from backend.app.models.operations import AlertEvent, PaperAutomationRun
from backend.app.models.paper import PaperAccount, PaperOrder
from backend.app.models.research import ModelVersion
from backend.app.schemas.broker import BrokerConnectionCreate, BrokerConnectionRead, DryRunApproval, LiveReadinessRead
from backend.app.services.broker_safety import broker_adapter, evaluate_paper_stability
from backend.app.services.research_gates import calibration_evidence_complete


router = APIRouter(prefix="/broker-safety", tags=["broker-safety"], dependencies=[Depends(get_current_user)])


async def _connection(session: AsyncSession, connection_id: UUID, project_id: UUID) -> BrokerConnection:
    item = await session.scalar(select(BrokerConnection).where(BrokerConnection.id == connection_id, BrokerConnection.project_id == project_id))
    if item is None:
        raise HTTPException(404, "券商安全配置不存在")
    return item


@router.post("/connections", response_model=BrokerConnectionRead, status_code=201)
async def create_connection(body: BrokerConnectionCreate, session: AsyncSession = Depends(get_db_session), context: ProjectContext = Depends(get_project_context)):
    account = await session.scalar(select(PaperAccount).where(PaperAccount.id == body.paper_account_id, PaperAccount.project_id == context.project.id))
    if account is None:
        raise HTTPException(404, "模拟账户不存在")
    item = BrokerConnection(project_id=context.project.id, owner_id=context.user.id, status="disabled", dry_run=True, **body.model_dump())
    session.add(item)
    await session.flush()
    session.add(AuditLog(actor_id=context.user.id, action="broker.connection_registered_disabled", resource_type="broker_connection", resource_id=str(item.id), details={"provider": item.provider, "environment": item.environment, "credential_reference_only": True}))
    await session.commit(); await session.refresh(item)
    return item


@router.get("/connections", response_model=list[BrokerConnectionRead])
async def list_connections(session: AsyncSession = Depends(get_db_session), context: ProjectContext = Depends(get_project_context)):
    return list((await session.scalars(select(BrokerConnection).where(BrokerConnection.project_id == context.project.id).order_by(BrokerConnection.created_at.desc()))).all())


@router.post("/connections/{connection_id}/evaluate", response_model=LiveReadinessRead, status_code=201)
async def evaluate_connection(connection_id: UUID, session: AsyncSession = Depends(get_db_session), context: ProjectContext = Depends(get_project_context)):
    connection = await _connection(session, connection_id, context.project.id)
    run_stats = (await session.execute(select(
        func.count(PaperAutomationRun.id),
        func.count(PaperAutomationRun.id).filter(PaperAutomationRun.status == "succeeded"),
        func.min(PaperAutomationRun.signal_date), func.max(PaperAutomationRun.signal_date),
    ).where(PaperAutomationRun.account_id == connection.paper_account_id))).one()
    total_runs, successful_runs, first_date, last_date = int(run_stats[0]), int(run_stats[1]), run_stats[2], run_stats[3]
    observation_days = (last_date - first_date).days + 1 if first_date and last_date else 0
    unreviewed = int(await session.scalar(select(func.count(PaperOrder.id)).where(PaperOrder.account_id == connection.paper_account_id, PaperOrder.source == "model_automation", PaperOrder.status == "proposed")) or 0)
    critical = int(await session.scalar(select(func.count(AlertEvent.id)).where(AlertEvent.project_id == context.project.id, AlertEvent.severity == "critical", AlertEvent.status != "resolved")) or 0)
    latest_run = await session.scalar(select(PaperAutomationRun).where(PaperAutomationRun.account_id == connection.paper_account_id, PaperAutomationRun.status == "succeeded").order_by(PaperAutomationRun.created_at.desc()))
    model = await session.get(ModelVersion, latest_run.model_id) if latest_run else None
    stats = {
        "successful_runs": successful_runs, "observation_days": observation_days,
        "success_rate": successful_runs / total_runs if total_runs else 0,
        "unreviewed_proposals": unreviewed, "open_critical_alerts": critical,
        "production_model_reliable": bool(model and model.stage == "production" and calibration_evidence_complete(model.metrics or {})),
        "credential_reference_valid": bool(connection.credential_secret_ref and connection.credential_secret_ref.startswith("env:QUANT_BROKER_")),
        "dry_run_only": connection.dry_run is True,
    }
    result = evaluate_paper_stability(stats)
    evaluation = LiveReadinessEvaluation(project_id=context.project.id, connection_id=connection.id, eligible=result["eligible"], checks=result["checks"], policy_version=result["policy_version"])
    session.add(evaluation); await session.commit(); await session.refresh(evaluation)
    return evaluation


@router.get("/evaluations", response_model=list[LiveReadinessRead])
async def list_evaluations(session: AsyncSession = Depends(get_db_session), context: ProjectContext = Depends(get_project_context)):
    return list((await session.scalars(select(LiveReadinessEvaluation).where(LiveReadinessEvaluation.project_id == context.project.id).order_by(LiveReadinessEvaluation.created_at.desc()).limit(100))).all())


@router.post("/connections/{connection_id}/approve-dry-run", response_model=BrokerConnectionRead)
async def approve_dry_run(connection_id: UUID, body: DryRunApproval, session: AsyncSession = Depends(get_db_session), admin: User = Depends(require_admin), context: ProjectContext = Depends(get_project_context)):
    connection = await _connection(session, connection_id, context.project.id)
    evaluation = await session.scalar(select(LiveReadinessEvaluation).where(LiveReadinessEvaluation.connection_id == connection.id).order_by(LiveReadinessEvaluation.created_at.desc()))
    stale = bool(evaluation and datetime.now(UTC) - evaluation.created_at > timedelta(hours=24))
    if evaluation is None or not evaluation.eligible or stale:
        raise HTTPException(409, "最新稳定性评估未通过，不能批准 dry-run")
    connection.status, connection.dry_run = "dry_run_approved", True
    connection.approved_by, connection.approved_at = admin.id, datetime.now(UTC)
    session.add(AuditLog(actor_id=admin.id, action="broker.dry_run_approved", resource_type="broker_connection", resource_id=str(connection.id), details={"evaluation_id": str(evaluation.id), "live_submission_enabled": False, "acknowledgement": body.acknowledgement}))
    await session.commit(); await session.refresh(connection)
    return connection


@router.get("/connections/{connection_id}/preview", response_model=list[dict])
async def preview_orders(connection_id: UUID, session: AsyncSession = Depends(get_db_session), context: ProjectContext = Depends(get_project_context)):
    connection = await _connection(session, connection_id, context.project.id)
    orders = list((await session.scalars(select(PaperOrder).where(PaperOrder.account_id == connection.paper_account_id, PaperOrder.source == "model_automation", PaperOrder.status == "proposed").order_by(PaperOrder.submitted_at).limit(100))).all())
    payload = [{"paper_order_id": str(item.id), "symbol": item.symbol, "side": item.side, "quantity": item.quantity, "reference_price": float(item.snapshot_price), "intended_trade_date": item.trade_date.isoformat()} for item in orders]
    return broker_adapter(connection.provider).preview(payload)
