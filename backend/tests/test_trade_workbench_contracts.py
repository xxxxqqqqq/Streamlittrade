import unittest
from datetime import date

from pydantic import ValidationError

from backend.app.schemas.trade_workbench import SnapshotBacktestCreate


class TradeWorkbenchContractTests(unittest.TestCase):
    def test_snapshot_backtest_has_explicit_execution_defaults(self):
        request = SnapshotBacktestCreate()
        self.assertEqual(request.top_n, 5)
        self.assertEqual(request.lot_size, 100)
        self.assertEqual(request.commission, 0.0003)

    def test_snapshot_backtest_rejects_invalid_window_and_board_lot(self):
        with self.assertRaises(ValidationError):
            SnapshotBacktestCreate(
                start_date=date(2024, 2, 1), end_date=date(2024, 1, 1)
            )
        with self.assertRaises(ValidationError):
            SnapshotBacktestCreate(lot_size=250)


if __name__ == "__main__":
    unittest.main()
