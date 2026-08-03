"""完全隔离的模拟账户、风控、撮合和结算接口。"""

from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.projects import ProjectContext, get_project_context
from backend.app.core.security import get_current_user
from backend.app.db.session import get_db_session
from backend.app.models.identity import AuditLog, User
from backend.app.models.paper import PaperAccount, PaperFill, PaperOrder, PaperPosition
from backend.app.schemas.paper import PaperAccountCreate, PaperAccountRead, PaperOrderCreate, PaperOrderRead, PaperSnapshot, SettlementRequest


router=APIRouter(prefix="/paper",tags=["paper-trading"],dependencies=[Depends(get_current_user)])
CENT=Decimal("0.01")


def money(value:Decimal)->Decimal:return value.quantize(CENT,rounding=ROUND_HALF_UP)


async def project_account(session:AsyncSession,account_id:UUID,context:ProjectContext)->PaperAccount:
    """按项目查找账户，避免通过已知 UUID 跨项目读取或交易。"""
    account=await session.scalar(
        select(PaperAccount).where(
            PaperAccount.id==account_id,
            PaperAccount.project_id==context.project.id,
        )
    )
    if account is None:raise HTTPException(404,"模拟账户不存在")
    return account


async def snapshot(session:AsyncSession,account:PaperAccount)->PaperSnapshot:
    positions=list((await session.scalars(select(PaperPosition).where(PaperPosition.account_id==account.id).order_by(PaperPosition.symbol))).all())
    orders=list((await session.scalars(select(PaperOrder).where(PaperOrder.account_id==account.id).order_by(PaperOrder.submitted_at.desc()).limit(100))).all())
    order_ids=[item.id for item in orders]
    fills=list((await session.scalars(select(PaperFill).where(PaperFill.order_id.in_(order_ids)).order_by(PaperFill.created_at.desc()))).all()) if order_ids else []
    market_value=money(sum((Decimal(item.last_price)*item.quantity for item in positions),Decimal("0")))
    equity=money(Decimal(account.cash)+market_value)
    return PaperSnapshot(account=account,equity=equity,market_value=market_value,total_profit=money(equity-Decimal(account.initial_cash)),positions=positions,orders=orders,fills=fills)


@router.post("/accounts",response_model=PaperAccountRead,status_code=201)
async def create_account(body:PaperAccountCreate,session:AsyncSession=Depends(get_db_session),user:User=Depends(get_current_user),context:ProjectContext=Depends(get_project_context)):
    limits={"max_order_value":str(body.max_order_value),"max_position_ratio":str(body.max_position_ratio),"commission_rate":"0.0003","minimum_commission":"5","sell_stamp_tax_rate":"0.0005","transfer_fee_rate":"0.00001"}
    account=PaperAccount(project_id=context.project.id,user_id=user.id,name=body.name,initial_cash=body.initial_cash,cash=body.initial_cash,status="active",risk_limits=limits)
    session.add(account);await session.flush();session.add(AuditLog(actor_id=user.id,action="paper.account_created",resource_type="paper_account",resource_id=str(account.id),details={"project_id":str(context.project.id),"initial_cash":str(body.initial_cash)}));await session.commit();await session.refresh(account);return account


@router.get("/accounts",response_model=list[PaperAccountRead])
async def list_accounts(session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    return list((await session.scalars(select(PaperAccount).where(PaperAccount.project_id==context.project.id).order_by(PaperAccount.created_at.desc()))).all())


@router.get("/accounts/{account_id}",response_model=PaperSnapshot)
async def read_account(account_id:UUID,session:AsyncSession=Depends(get_db_session),context:ProjectContext=Depends(get_project_context)):
    return await snapshot(session,await project_account(session,account_id,context))


@router.post("/accounts/{account_id}/orders",response_model=PaperOrderRead,status_code=201)
async def submit_order(account_id:UUID,body:PaperOrderCreate,session:AsyncSession=Depends(get_db_session),user:User=Depends(get_current_user),context:ProjectContext=Depends(get_project_context)):
    """使用明确的回放价格即时模拟成交；绝不调用任何券商接口。"""
    account=await project_account(session,account_id,context)
    if account.status!="active":raise HTTPException(409,"账户已冻结，不能提交订单")
    if account.last_settlement_date and body.trade_date<account.last_settlement_date:raise HTTPException(409,"交易日期不能早于账户最近结算日")
    position=await session.scalar(select(PaperPosition).where(PaperPosition.account_id==account.id,PaperPosition.symbol==body.symbol).with_for_update())
    gross=money(body.snapshot_price*body.quantity);limits=account.risk_limits
    commission=money(max(Decimal(limits["minimum_commission"]),gross*Decimal(limits["commission_rate"])))
    stamp=money(gross*Decimal(limits["sell_stamp_tax_rate"])) if body.side=="sell" else Decimal("0")
    transfer=money(gross*Decimal(limits["transfer_fee_rate"]));fees=commission+stamp+transfer
    rejection=None
    if gross>Decimal(limits["max_order_value"]):rejection="订单金额超过单笔风控上限"
    elif body.side=="buy" and Decimal(account.cash)<gross+fees:rejection="可用资金不足"
    elif body.side=="sell" and (position is None or position.sellable_quantity<body.quantity):rejection="T+1可卖持仓不足"
    if body.side=="buy" and not rejection:
        positions=list((await session.scalars(select(PaperPosition).where(PaperPosition.account_id==account.id))).all());equity=Decimal(account.cash)+sum((Decimal(x.last_price)*x.quantity for x in positions),Decimal("0"));old_value=Decimal(position.last_price)*position.quantity if position else Decimal("0")
        if equity>0 and (old_value+gross)/equity>Decimal(limits["max_position_ratio"]):rejection="单标的仓位超过风控比例"
    order=PaperOrder(account_id=account.id,symbol=body.symbol,side=body.side,quantity=body.quantity,snapshot_price=body.snapshot_price,status="rejected" if rejection else "filled",trade_date=body.trade_date,source=body.source,message=rejection)
    session.add(order);await session.flush()
    if not rejection:
        if body.side=="buy":
            account.cash=money(Decimal(account.cash)-gross-fees)
            if position is None:position=PaperPosition(account_id=account.id,symbol=body.symbol,quantity=0,sellable_quantity=0,average_cost=0,last_price=body.snapshot_price);session.add(position)
            total_cost=Decimal(position.average_cost)*position.quantity+gross+fees;position.quantity+=body.quantity;position.average_cost=(total_cost/position.quantity).quantize(Decimal("0.0001"));position.last_price=body.snapshot_price;position.last_buy_date=body.trade_date
        else:
            account.cash=money(Decimal(account.cash)+gross-fees);position.quantity-=body.quantity;position.sellable_quantity-=body.quantity;position.last_price=body.snapshot_price
        session.add(PaperFill(order_id=order.id,quantity=body.quantity,price=body.snapshot_price,gross_amount=gross,commission=commission,stamp_tax=stamp,transfer_fee=transfer))
    session.add(AuditLog(actor_id=user.id,action="paper.order_rejected" if rejection else "paper.order_filled",resource_type="paper_order",resource_id=str(order.id),details={"side":body.side,"symbol":body.symbol,"quantity":body.quantity,"price":str(body.snapshot_price),"reason":rejection or ""}));await session.commit();await session.refresh(order);return order


@router.post("/accounts/{account_id}/settle",response_model=PaperSnapshot)
async def settle(account_id:UUID,body:SettlementRequest,session:AsyncSession=Depends(get_db_session),user:User=Depends(get_current_user),context:ProjectContext=Depends(get_project_context)):
    account=await project_account(session,account_id,context)
    if account.last_settlement_date and body.trade_date<=account.last_settlement_date:raise HTTPException(409,"结算日期必须向后推进")
    positions=(await session.scalars(select(PaperPosition).where(PaperPosition.account_id==account.id))).all()
    for position in positions:
        if position.last_buy_date and position.last_buy_date<body.trade_date:position.sellable_quantity=position.quantity
    account.last_settlement_date=body.trade_date;session.add(AuditLog(actor_id=user.id,action="paper.account_settled",resource_type="paper_account",resource_id=str(account.id),details={"trade_date":body.trade_date.isoformat()}));await session.commit();await session.refresh(account);return await snapshot(session,account)


@router.post("/accounts/{account_id}/freeze",response_model=PaperAccountRead)
async def freeze(account_id:UUID,session:AsyncSession=Depends(get_db_session),user:User=Depends(get_current_user),context:ProjectContext=Depends(get_project_context)):
    account=await project_account(session,account_id,context);account.status="frozen";session.add(AuditLog(actor_id=user.id,action="paper.account_frozen",resource_type="paper_account",resource_id=str(account.id)));await session.commit();await session.refresh(account);return account
