"""模拟交易 API 数据契约。"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PaperAccountCreate(BaseModel):
    name: str = Field(min_length=2,max_length=100)
    initial_cash: Decimal = Field(default=Decimal("1000000"),ge=Decimal("10000"),le=Decimal("1000000000"))
    max_order_value: Decimal = Field(default=Decimal("100000"),gt=0)
    max_position_ratio: Decimal = Field(default=Decimal("0.30"),gt=0,le=1)


class PaperOrderCreate(BaseModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    side: Literal["buy","sell"]
    quantity: int = Field(ge=100,le=10000000)
    snapshot_price: Decimal = Field(gt=0,le=Decimal("100000"),decimal_places=4)
    trade_date: date
    source: Literal["manual_replay"] = "manual_replay"

    @model_validator(mode="after")
    def validate_board_lot(self):
        if self.quantity%100: raise ValueError("A股模拟订单数量必须是100股的整数倍")
        return self


class SettlementRequest(BaseModel):
    trade_date: date


class PaperAccountRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID;project_id:UUID;user_id:UUID;name:str;initial_cash:Decimal;cash:Decimal;status:str;risk_limits:dict[str,Any];last_settlement_date:date|None;created_at:datetime


class PaperPositionRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID;symbol:str;quantity:int;sellable_quantity:int;average_cost:Decimal;last_price:Decimal;last_buy_date:date|None


class PaperOrderRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID;symbol:str;side:str;quantity:int;snapshot_price:Decimal;status:str;trade_date:date;source:str;message:str|None;submitted_at:datetime


class PaperFillRead(BaseModel):
    model_config=ConfigDict(from_attributes=True)
    id:UUID;order_id:UUID;quantity:int;price:Decimal;gross_amount:Decimal;commission:Decimal;stamp_tax:Decimal;transfer_fee:Decimal;created_at:datetime


class PaperSnapshot(BaseModel):
    account:PaperAccountRead
    equity:Decimal
    market_value:Decimal
    total_profit:Decimal
    positions:list[PaperPositionRead]
    orders:list[PaperOrderRead]
    fills:list[PaperFillRead]
