"""
模块：数据获取层 (data_loader.py)
功能：基于 Baostock 获取 A 股历史日线数据（前复权），带 Streamlit 内存缓存
依赖：streamlit (cache_data, warning, error), pandas, numpy, baostock, time, datetime
"""
import streamlit as st
import pandas as pd
import time
import baostock as bs


# ============================================================
# A 股历史日线数据获取（带缓存与重试）
# ============================================================

@st.cache_data(ttl=3600)  # 缓存有效期 1 小时，避免重复请求
def fetch_stock_data(symbol, start_date, end_date, max_retries=2):
    """
    从 Baostock 获取 A 股历史日线数据（前复权）

    Args:
        symbol:      股票代码，如 "600160"（沪市）或 "000001"（深市）
        start_date:  起始日期，格式 "YYYYMMDD"
        end_date:    结束日期，格式 "YYYYMMDD"
        max_retries: 最大重试次数，默认 2 次

    Returns:
        pd.DataFrame: 包含 date(索引), open, high, low, close, volume 的数据表
                     失败时返回 None
    """
    # ---- 日期格式转换：YYYYMMDD → YYYY-MM-DD ----
    start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    # ---- 股票代码格式转换：6 开头 → sh，0/3 开头 → sz ----
    if symbol.startswith('6'):
        bs_code = f"sh.{symbol}"
    elif symbol.startswith('0') or symbol.startswith('3'):
        bs_code = f"sz.{symbol}"
    else:
        bs_code = f"sz.{symbol}"  # 默认深市

    # ---- 带重试的数据获取循环 ----
    for attempt in range(max_retries):
        try:
            # 登录 Baostock
            lg = bs.login()
            if lg.error_code != '0':
                raise Exception(f"Baostock 登录失败: {lg.error_msg}")

            # 查询历史 K 线数据（日线，前复权）
            rs = bs.query_history_k_data_plus(
                code=bs_code,
                fields="date,open,high,low,close,volume",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="2"  # 2=前复权
            )
            if rs.error_code != '0':
                raise Exception(f"数据查询失败: {rs.error_msg}")

            # 逐行读取查询结果
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())

            if not data_list:
                raise ValueError("查询返回数据为空，请检查股票代码和日期范围")

            # 构建 DataFrame
            df = pd.DataFrame(data_list, columns=rs.fields)

            # 数据处理：日期 → 索引，OHLCV → 浮点数
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)

            # 登出并返回
            bs.logout()

            # 去重排序
            df = df[~df.index.duplicated(keep='first')]
            df = df.sort_index()
            return df

        except Exception as e:
            # 确保登出
            try:
                bs.logout()
            except Exception:
                pass

            # 指数退避重试
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # 1s, 2s, 4s...
                st.warning(f"数据获取失败，{wait_time}秒后重试... ({attempt + 1}/{max_retries})")
                time.sleep(wait_time)
            else:
                st.error(f"获取 {symbol} 数据失败，已重试 {max_retries} 次: {e}")
                return None

    return None
