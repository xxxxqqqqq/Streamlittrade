import unittest
from unittest.mock import patch

from quant_core.data import fetch_stock_data


class _Response:
    error_code = "0"
    error_msg = "success"

    def __init__(self, fields, rows):
        self.fields = fields.split(",")
        self._rows = iter(rows)
        self._current = None

    def next(self):
        try:
            self._current = next(self._rows)
            return True
        except StopIteration:
            return False

    def get_row_data(self):
        return self._current


class _BaoStockClient:
    def __init__(self):
        self.requested_fields = None
        self.logged_out = False

    def login(self):
        return _Response("", [])

    def query_history_k_data_plus(self, *, fields, **kwargs):
        self.requested_fields = fields
        return _Response(
            fields,
            [["2024-01-02", "10", "11", "9", "10.5", "100000", "1050000"]],
        )

    def logout(self):
        self.logged_out = True


class BaoStockAdapterTests(unittest.TestCase):
    def test_daily_query_preserves_real_turnover_amount(self):
        client = _BaoStockClient()
        with patch("quant_core.data.bs", client):
            result = fetch_stock_data("600000", "20240101", "20240131")

        self.assertEqual(
            client.requested_fields,
            "date,open,high,low,close,volume,amount",
        )
        self.assertEqual(
            list(result.columns),
            ["open", "high", "low", "close", "volume", "amount"],
        )
        self.assertEqual(result.iloc[0]["amount"], 1_050_000)
        self.assertTrue(client.logged_out)


if __name__ == "__main__":
    unittest.main()
