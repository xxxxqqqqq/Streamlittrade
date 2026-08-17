"""与界面无关的 A 股行情获取服务。

这里不调用 ``st.error``、``st.warning`` 或任何 Web 框架接口。失败时通过明确的
异常向上传递，由 Streamlit、FastAPI 或后台 Worker 自行决定如何展示和记录。
"""

from __future__ import annotations

import time
from typing import Callable

import baostock as bs
import pandas as pd


class MarketDataError(RuntimeError):
    """行情源登录、查询或数据校验失败。"""


def _to_baostock_code(symbol: str) -> str:
    """把六位证券代码转换为 Baostock 使用的交易所代码。"""
    symbol = str(symbol).strip()
    if len(symbol) != 6 or not symbol.isdigit():
        raise ValueError("股票代码必须是六位数字，例如 600160")
    if symbol.startswith("6"):
        return f"sh.{symbol}"
    if symbol.startswith(("0", "3")):
        return f"sz.{symbol}"
    raise ValueError(f"当前行情源暂不支持该证券代码: {symbol}")


def _to_iso_date(value: str) -> str:
    """校验 YYYYMMDD 日期并转换为 YYYY-MM-DD。"""
    value = str(value).strip()
    if len(value) != 8 or not value.isdigit():
        raise ValueError("日期必须使用 YYYYMMDD 格式")
    parsed = pd.to_datetime(value, format="%Y%m%d", errors="raise")
    return parsed.strftime("%Y-%m-%d")


def fetch_stock_data(
    symbol: str,
    start_date: str,
    end_date: str,
    max_retries: int = 2,
    sleeper: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """从 Baostock 获取前复权日线数据。

    参数和返回结构与旧版 ``data_loader.fetch_stock_data`` 保持一致；不同之处是
    本函数失败时抛出 ``MarketDataError``，而不是直接操作某个界面的状态。
    ``sleeper`` 可注入，便于自动化测试跳过真实等待。
    """
    if max_retries < 1:
        raise ValueError("max_retries 必须大于等于 1")

    bs_code = _to_baostock_code(symbol)
    start = _to_iso_date(start_date)
    end = _to_iso_date(end_date)
    if start > end:
        raise ValueError("开始日期不能晚于结束日期")

    last_error: Exception | None = None
    for attempt in range(max_retries):
        logged_in = False
        try:
            login_result = bs.login()
            if login_result.error_code != "0":
                raise MarketDataError(f"Baostock 登录失败: {login_result.error_msg}")
            logged_in = True

            result = bs.query_history_k_data_plus(
                code=bs_code,
                fields="date,open,high,low,close,volume,amount",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="2",
            )
            if result.error_code != "0":
                raise MarketDataError(f"行情查询失败: {result.error_msg}")

            rows: list[list[str]] = []
            while result.error_code == "0" and result.next():
                rows.append(result.get_row_data())
            if not rows:
                raise MarketDataError("行情查询结果为空，请检查代码和日期范围")

            data = pd.DataFrame(rows, columns=result.fields)
            data["date"] = pd.to_datetime(data["date"], errors="raise")
            for column in ("open", "high", "low", "close", "volume", "amount"):
                data[column] = pd.to_numeric(data[column], errors="raise")

            data = data.set_index("date")
            return data[~data.index.duplicated(keep="first")].sort_index()
        except Exception as exc:  # 保存最后一次错误，重试耗尽后统一包装。
            last_error = exc
            if attempt < max_retries - 1:
                sleeper(2**attempt)
        finally:
            # Baostock 使用进程级会话；无论查询成功与否都必须主动登出。
            if logged_in:
                try:
                    bs.logout()
                except Exception:
                    pass

    raise MarketDataError(
        f"获取 {symbol} 行情失败，已尝试 {max_retries} 次: {last_error}"
    ) from last_error
