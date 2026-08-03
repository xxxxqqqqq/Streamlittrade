"""模拟交易请求的安全边界测试。"""

import unittest
from datetime import date
from decimal import Decimal

from pydantic import ValidationError

from backend.app.schemas.paper import PaperAccountCreate, PaperOrderCreate


class PaperTradingContractTests(unittest.TestCase):
    def test_order_requires_board_lot(self):
        with self.assertRaises(ValidationError):
            PaperOrderCreate(symbol="600000",side="buy",quantity=150,snapshot_price=Decimal("10"),trade_date=date.today())

    def test_order_rejects_non_stock_symbol(self):
        with self.assertRaises(ValidationError):
            PaperOrderCreate(symbol="DEMO",side="buy",quantity=100,snapshot_price=Decimal("10"),trade_date=date.today())

    def test_account_has_conservative_risk_defaults(self):
        account=PaperAccountCreate(name="测试账户")
        self.assertEqual(account.max_position_ratio,Decimal("0.30"))
        self.assertEqual(account.max_order_value,Decimal("100000"))


if __name__=="__main__":unittest.main()
