import unittest
import pandas as pd
from quant_core.akshare_data import fetch_akshare_stock_data


class FakeAKShare:
    def stock_zh_a_hist(self, **kwargs):
        self.kwargs = kwargs
        return pd.DataFrame({
            "日期": ["2024-01-02", "2024-01-03"], "股票代码": ["000001", "000001"],
            "开盘": [10.0, 10.2], "收盘": [10.1, 10.3], "最高": [10.2, 10.4],
            "最低": [9.9, 10.1], "成交量": [100000, 120000], "成交额": [1000000, 1200000],
        })


class AKShareAdapterTests(unittest.TestCase):
    def test_official_daily_shape_is_normalized(self):
        client = FakeAKShare()
        result = fetch_akshare_stock_data("000001", "20240101", "20240131", client=client)
        self.assertEqual(list(result.columns), ["open", "high", "low", "close", "volume", "amount"])
        self.assertIsInstance(result.index, pd.DatetimeIndex)
        self.assertEqual(client.kwargs["adjust"], "qfq")

    def test_invalid_symbol_is_rejected_before_network(self):
        with self.assertRaises(ValueError):
            fetch_akshare_stock_data("bad", "20240101", "20240131", client=FakeAKShare())
