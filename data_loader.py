"""Streamlit 行情适配层。

纯行情逻辑位于 :mod:`quant_core.data`。本文件只负责缓存和用户提示，避免核心
代码依赖 Streamlit，也保留旧页面所使用的 ``None`` 失败返回约定。
"""

import streamlit as st

from quant_core.data import MarketDataError, fetch_stock_data as _fetch_stock_data


@st.cache_data(ttl=3600)
def fetch_stock_data(symbol: str, start_date: str, end_date: str, max_retries: int = 2):
    """获取行情并将核心异常翻译成 Streamlit 提示。"""
    try:
        return _fetch_stock_data(symbol, start_date, end_date, max_retries=max_retries)
    except (MarketDataError, ValueError) as exc:
        st.error(str(exc))
        return None
