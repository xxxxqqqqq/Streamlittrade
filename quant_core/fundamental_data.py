"""Baostock 季度财务数据的时点（PIT）取数与日频对齐。

模块边界：

- ``fundamentals_to_daily`` 是纯 pandas 对齐逻辑，不导入 baostock，可在离线环境
  构造数据回放测试；
- 只有默认客户端 ``baostock_quarterly_client`` 才延迟导入 baostock，因此 API 进程
  引用本模块不会带上数据源依赖；
- 所有指标一律按 ``pubDate``（公告日）对齐，禁止用 ``statDate``（报告期）对齐，
  否则就是拿未来信息做研究。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Iterable, Protocol

import pandas as pd


logger = logging.getLogger(__name__)

PIPELINE_VERSION = "fundamental_pit_v1"

QUARTERLY_TABLES = ("profit", "growth", "balance", "cash_flow")

# baostock 季度接口字段到长表列名的映射。字段名以服务端实际返回为准
# （query_profit_data / query_growth_data / query_balance_data /
# query_cash_flow_data，参数 (code, year, quarter)，每张表都带 pubDate）。
FIELD_MAPPING: dict[str, dict[str, str]] = {
    "profit": {
        "roeAvg": "roe_avg",  # 净资产收益率(平均)，服务端已是小数，"0.051598" 即 5.16%
        "npMargin": "np_margin",  # 销售净利率
        "gpMargin": "gross_margin",  # 销售毛利率
        "netProfit": "net_profit",  # 净利润(元)，绝对额，仅用于派生比率
        "MBRevenue": "revenue",  # 主营营业收入(元)，绝对额，同比的当期值与基期
    },
    "growth": {
        # 取 YOYNI（净利润同比增长率）；YOYPNI 是归母口径，两者混用会让同一因子
        # 的口径随股票漂移，因此只登记一个字段。
        "YOYNI": "profit_yoy",
    },
    "balance": {
        "liabilityToAsset": "liability_to_asset",  # 资产负债率
        "assetToEquity": "asset_to_equity",  # 权益乘数，用于按恒等式复原总资产规模
    },
    "cash_flow": {
        "CFOToNP": "cfo_to_np",  # 经营现金净流量/净利润
    },
}

# 直接来自数据源的列（派生列见 DAILY_FUNDAMENTAL_COLUMNS 里的 revenue_yoy / accruals）
FUNDAMENTAL_COLUMNS = (
    "roe_avg",
    "gross_margin",
    "np_margin",
    "net_profit",
    "revenue",
    "profit_yoy",
    "cfo_to_np",
    "liability_to_asset",
    "asset_to_equity",
)

LONG_COLUMNS = ("symbol", "stat_date", "pub_date", *FUNDAMENTAL_COLUMNS)

DERIVED_COLUMNS = ("revenue_yoy", "accruals")

# 对齐到交易日之后交给因子层的列
DAILY_FUNDAMENTAL_COLUMNS = (
    "roe_avg",
    "gross_margin",
    "revenue_yoy",
    "profit_yoy",
    "cfo_to_np",
    "liability_to_asset",
    "accruals",
)

# 每个交易日实际生效的公告日，用于审计“因子只用了当时已知的信息”
PUB_DATE_COLUMN = "fundamental_pub_date"

# baostock 网络请求的抖动重试次数（单季度单表）
DEFAULT_MAX_RETRIES = 2


class QuarterlyClient(Protocol):
    """季度财务数据源协议：测试注入假 client，生产注入 baostock。"""

    def fetch(self, table: str, code: str, year: int, quarter: int) -> pd.DataFrame:
        ...


def to_baostock_code(symbol: str) -> str:
    """把六位证券代码转换为 baostock 使用的交易所代码。"""

    text = str(symbol).strip().lower()
    if len(text) == 9 and text[2] == "." and text[:2] in {"sh", "sz"} and text[3:].isdigit():
        return text
    if len(text) != 6 or not text.isdigit():
        raise ValueError(f"股票代码必须是六位数字或 sh./sz. 前缀代码: {symbol}")
    return f"sh.{text}" if text.startswith("6") else f"sz.{text}"


def _result_frame(result: Any) -> pd.DataFrame:
    """把 baostock 的 ResultData 翻页读成 DataFrame（列名即服务端字段）。"""

    rows: list[list[str]] = []
    while result.error_code == "0" and result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=result.fields)


class BaostockQuarterlyClient:
    """默认季度数据客户端：延迟导入 baostock，逐 (表, 年, 季) 查询。"""

    def __init__(self) -> None:
        self._module: Any = None
        self._logged_in = False

    def _data_source(self) -> Any:
        if self._module is None:
            import baostock  # 延迟导入：纯对齐逻辑与 API 进程都不需要该依赖

            self._module = baostock
        return self._module

    def login(self) -> None:
        if self._logged_in:
            return
        module = self._data_source()
        result = module.login()
        if result.error_code != "0":
            raise RuntimeError(f"Baostock 登录失败: {result.error_msg}")
        self._logged_in = True

    def logout(self) -> None:
        if not self._logged_in:
            return
        try:
            self._data_source().logout()
        finally:
            self._logged_in = False

    def fetch(self, table: str, code: str, year: int, quarter: int) -> pd.DataFrame:
        if table not in QUARTERLY_TABLES:
            raise ValueError(f"不支持的季度财务表: {table}")
        if not self._logged_in:
            self.login()
        query = getattr(self._data_source(), f"query_{table}_data")
        result = query(code=code, year=int(year), quarter=int(quarter))
        if result.error_code != "0":
            raise RuntimeError(f"baostock {table} 查询失败: {result.error_msg}")
        return _result_frame(result)


def baostock_quarterly_client() -> BaostockQuarterlyClient:
    """构造默认的 baostock 季度客户端（可被测试替换）。"""

    return BaostockQuarterlyClient()


def _retry_call(
    action: Callable[[], Any],
    sleeper: Callable[[float], None],
    max_retries: int,
    *,
    label: str,
) -> Any:
    """按退避策略重试一次外部调用，耗尽后抛出带上下文的异常。"""

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            return action()
        except Exception as exc:  # 网络抖动、登录过期等统一退避重试
            last_error = exc
            if attempt < max_retries - 1:
                sleeper(2**attempt)
    raise RuntimeError(f"{label} 失败，已尝试 {max_retries} 次: {last_error}") from last_error


def _normalize_table_rows(
    raw: pd.DataFrame,
    table: str,
    symbol: str,
    counters: dict[str, Any],
) -> pd.DataFrame:
    """把一张表的原始返回规范成 (symbol, stat_date, pub_date, 指标…) 的行。"""

    frame = pd.DataFrame(raw).copy()
    if "pubDate" not in frame.columns or "statDate" not in frame.columns:
        raise ValueError(f"baostock {table} 返回缺少 pubDate/statDate 字段")
    stat_date = pd.to_datetime(frame["statDate"], errors="coerce")
    pub_date = pd.to_datetime(frame["pubDate"], errors="coerce")
    usable = stat_date.notna() & pub_date.notna()
    # 缺公告日的行无法做时点对齐；丢弃并计数，绝不退化成用报告期对齐
    counters["missing_pub_date"] += int((~usable).sum())
    frame = frame[usable]
    output = pd.DataFrame(
        {
            "symbol": symbol,
            "stat_date": stat_date[usable].to_numpy(),
            "pub_date": pub_date[usable].to_numpy(),
        }
    )
    for field, column in FIELD_MAPPING[table].items():
        values = frame[field] if field in frame.columns else pd.Series(index=frame.index)
        output[column] = pd.to_numeric(values, errors="coerce").to_numpy()
    return output.reset_index(drop=True)


def _numeric_column(frame: pd.DataFrame, name: str) -> pd.Series:
    """读取数值列；列不存在时返回整列空值，让派生指标自然为空。"""

    if name not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[name], errors="coerce").astype("float64")


def _derive_revenue_yoy(frame: pd.DataFrame) -> pd.Series:
    """主营营业收入同比：同季度对比上一年，且只能用当时已经公告的上一期。

    MBRevenue 是年初至今的累计口径，所以只能同季度相比。基期取“公告日严格早于
    本期公告日”的最近一期，避免用修订后重述的旧数据回填新公告。
    """

    if frame.empty or "revenue" not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    rows = frame[["symbol", "stat_date", "pub_date", "revenue"]].copy()
    rows["year"] = rows["stat_date"].dt.year
    rows["quarter"] = rows["stat_date"].dt.quarter
    rows["_row"] = range(len(rows))
    base = rows[["symbol", "year", "quarter", "pub_date", "revenue"]].rename(
        columns={"pub_date": "_base_pub_date", "revenue": "_base_revenue"}
    )
    base["year"] = base["year"] + 1
    aligned = pd.merge_asof(
        rows.sort_values("pub_date", kind="stable"),
        base.sort_values("_base_pub_date", kind="stable"),
        left_on="pub_date",
        right_on="_base_pub_date",
        by=["symbol", "year", "quarter"],
        direction="backward",
        allow_exact_matches=False,
    ).sort_values("_row", kind="stable")
    denominator = _numeric_column(aligned, "_base_revenue").replace(0, float("nan"))
    values = _numeric_column(aligned, "revenue") / denominator - 1
    return pd.Series(values.to_numpy(), index=frame.index, dtype="float64")


def _derive_accruals(frame: pd.DataFrame) -> pd.Series:
    """Sloan 应计利润 (净利润 - 经营现金流) / 总资产，质量反向指标。

    baostock 季度接口只返回比率、没有绝对金额，因此先按恒等式复原规模再约分：
    平均净资产 = 净利润 / roeAvg（roeAvg 本身就是净利润/平均净资产），
    总资产 = 平均净资产 * assetToEquity，经营现金流 = 净利润 * CFOToNP；
    约掉净利润后 accruals = (1 - CFOToNP) * roeAvg / assetToEquity，
    即 “1 - 现金流含量” 乘以 ROA。任一分量缺失即返回空值。
    """

    cfo_quality = _numeric_column(frame, "cfo_to_np")
    roe = _numeric_column(frame, "roe_avg")
    multiplier = _numeric_column(frame, "asset_to_equity").replace(0, float("nan"))
    values = (1.0 - cfo_quality) * roe / multiplier
    return values.replace([float("inf"), float("-inf")], float("nan"))


def _combine_sources(symbol: str, sources: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """把四张表压成“一行一个公告事件”的长表。

    事件集合是四张表 (stat_date, pub_date) 的并集；每个事件取各表在该公告日或
    之前最近一次已公告的值。这样同一 stat_date 的修订会作为新事件出现，而不会
    因为某张表没跟着修订就丢掉整行，也不会把两张表的公告日做笛卡尔积。
    """

    events = pd.concat(
        [frame[["stat_date", "pub_date"]] for frame in sources.values()],
        ignore_index=True,
    )
    events = events.drop_duplicates().sort_values("pub_date", kind="stable").reset_index(drop=True)
    events["symbol"] = symbol
    merged = events
    for frame in sources.values():
        merged = pd.merge_asof(
            merged,
            frame.sort_values("pub_date", kind="stable"),
            on="pub_date",
            by=["symbol", "stat_date"],
            direction="backward",
        )
    merged["revenue_yoy"] = _derive_revenue_yoy(merged)
    merged["accruals"] = _derive_accruals(merged)
    columns = [name for name in LONG_COLUMNS + DERIVED_COLUMNS if name in merged.columns]
    return (
        merged[columns]
        .sort_values(["stat_date", "pub_date"], kind="stable")
        .reset_index(drop=True)
    )


def _fetch_symbol(
    client: Any,
    symbol: str,
    first_year: int,
    last_year: int,
    sleeper: Callable[[float], None],
    max_retries: int,
    counters: dict[str, Any],
) -> pd.DataFrame | None:
    """拉取一只股票全部年份的季度财务数据并压成公告事件长表。"""

    code = to_baostock_code(symbol)
    sources: dict[str, pd.DataFrame] = {}
    for table in QUARTERLY_TABLES:
        pieces: list[pd.DataFrame] = []
        for year in range(first_year, last_year + 1):
            for quarter in (1, 2, 3, 4):
                label = f"{symbol} {table} {year}Q{quarter}"
                try:
                    raw = _retry_call(
                        lambda: client.fetch(table, code, year, quarter),
                        sleeper,
                        max_retries,
                        label=label,
                    )
                except Exception as exc:
                    counters["failed"] += 1
                    if len(counters["failure_details"]) < 20:
                        counters["failure_details"].append({"target": label, "reason": str(exc)[:200]})
                    continue
                if raw is None or len(raw) == 0:
                    counters["empty"] += 1
                    continue
                pieces.append(_normalize_table_rows(raw, table, symbol, counters))
        if pieces:
            combined = pd.concat(pieces, ignore_index=True)
            sources[table] = combined.drop_duplicates(subset=["stat_date", "pub_date"], keep="last")
    if not sources:
        return None
    return _combine_sources(symbol, sources)


def _empty_long_frame() -> pd.DataFrame:
    columns = list(LONG_COLUMNS) + list(DERIVED_COLUMNS)
    return pd.DataFrame({name: pd.Series(dtype="float64") for name in columns})


def fetch_quarterly_fundamentals(
    symbols: Iterable[str],
    start_year: int,
    end_year: int,
    *,
    client: Any = None,
    sleeper: Callable[[float], None] | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> pd.DataFrame:
    """逐股逐季拉取 baostock 四张季频表，产出公告日长表。

    返回每行一个“公告事件”的长表，列为 ``LONG_COLUMNS + DERIVED_COLUMNS``：
    ``symbol, stat_date, pub_date, roe_avg, gross_margin, np_margin, net_profit,
    revenue, profit_yoy, cfo_to_np, liability_to_asset, asset_to_equity,
    revenue_yoy, accruals``。``client`` 可注入（默认 baostock），``sleeper`` 可注入
    以便测试跳过真实等待；函数自己创建的客户端会在结束时登出，外部注入的客户端由
    调用方负责关闭（批量逐股取数时可以只登录一次）。取数计数（空结果、缺公告日、
    失败明细）写在 ``result.attrs["warnings"]`` 里，供调用方落进数据版本的质量报告。
    """

    symbol_list = [str(item) for item in symbols]
    if not symbol_list:
        raise ValueError("必须至少提供一只股票代码")
    first_year, last_year = int(start_year), int(end_year)
    if first_year > last_year:
        raise ValueError("start_year 不能晚于 end_year")
    pause = sleeper or time.sleep
    owns_client = client is None
    data_client = client if client is not None else baostock_quarterly_client()

    counters: dict[str, Any] = {
        "empty": 0,
        "missing_pub_date": 0,
        "failed": 0,
        "failure_details": [],
        "symbols": [],
    }
    try:
        frames: list[pd.DataFrame] = []
        for symbol in symbol_list:
            frame = _fetch_symbol(
                data_client, symbol, first_year, last_year, pause, max_retries, counters
            )
            if frame is not None and not frame.empty:
                frames.append(frame)
                counters["symbols"].append(symbol)
    finally:
        if owns_client:
            logout = getattr(data_client, "logout", None)
            if callable(logout):
                try:
                    logout()
                except Exception:  # 登出失败不应掩盖取数结果
                    logger.warning("baostock 登出失败", exc_info=True)

    if frames:
        result = pd.concat(frames, ignore_index=True)
        result = result.reindex(columns=list(LONG_COLUMNS) + list(DERIVED_COLUMNS))
        result = result.sort_values(["symbol", "stat_date", "pub_date"], kind="stable").reset_index(
            drop=True
        )
    else:
        result = _empty_long_frame()

    warnings = {
        "pipeline": PIPELINE_VERSION,
        "year_range": [first_year, last_year],
        "symbols": [str(item) for item in symbol_list],
        "symbols_with_fundamentals": list(counters["symbols"]),
        "empty_queries": int(counters["empty"]),
        "missing_pub_date_rows": int(counters["missing_pub_date"]),
        "failed_queries": int(counters["failed"]),
        "failure_details": counters["failure_details"],
    }
    if warnings["missing_pub_date_rows"]:
        logger.warning(
            "丢弃 %s 行缺少 pubDate 的季度财务数据：无法做时点对齐",
            warnings["missing_pub_date_rows"],
        )
    if warnings["failed_queries"]:
        logger.warning("季度财务查询失败 %s 次，明细见 warnings", warnings["failed_queries"])
    result.attrs["warnings"] = warnings
    return result


def _normalize_trade_dates(fundamentals_df: pd.DataFrame, trade_dates: Any) -> pd.DataFrame:
    """把交易日入参规范成 (symbol, date) 两列。"""

    if isinstance(trade_dates, pd.DataFrame):
        if "date" not in trade_dates.columns:
            raise ValueError("trade_dates 必须包含 date 列")
        if "symbol" in trade_dates.columns:
            return pd.DataFrame(
                {
                    "date": trade_dates["date"].to_numpy(),
                    "symbol": trade_dates["symbol"].astype(str).to_numpy(),
                }
            )
        frame = pd.DataFrame({"date": trade_dates["date"].to_numpy()})
    else:
        frame = pd.DataFrame({"date": pd.to_datetime(list(trade_dates))})
    if "symbol" not in getattr(fundamentals_df, "columns", ()):
        raise ValueError("trade_dates 缺少 symbol 列时，长表必须提供股票代码")
    symbols = sorted(pd.Series(fundamentals_df["symbol"]).astype(str).unique())
    if not symbols:
        raise ValueError("长表没有任何股票代码，无法广播交易日")
    return frame.merge(pd.DataFrame({"symbol": symbols}), how="cross")


def fundamentals_to_daily(fundamentals_df: pd.DataFrame, trade_dates: Any) -> pd.DataFrame:
    """把公告日长表 as-of 对齐到交易日面板。

    每个交易日只能看到 ``pub_date <= 交易日`` 的最近一次公告（
    ``merge_asof(direction="backward")``）；绝不允许用 ``stat_date`` 对齐，那等于
    把还要过一个多月才公告的财报提前塞进当期截面。返回
    ``(symbol, date) + DAILY_FUNDAMENTAL_COLUMNS + fundamental_pub_date``。
    """

    trading = _normalize_trade_dates(fundamentals_df, trade_dates)
    trading["date"] = pd.to_datetime(trading["date"], errors="coerce")
    if trading["date"].isna().any():
        raise ValueError("trade_dates 中存在无法解析的日期")
    trading["symbol"] = trading["symbol"].astype(str)

    available = [name for name in DAILY_FUNDAMENTAL_COLUMNS if name in fundamentals_df.columns]
    right = pd.DataFrame(columns=["symbol", "pub_date", *available])
    if not fundamentals_df.empty:
        source = fundamentals_df.copy()
        source["symbol"] = source["symbol"].astype(str)
        source["pub_date"] = pd.to_datetime(source["pub_date"], errors="coerce")
        right = source.dropna(subset=["pub_date"])[["symbol", "pub_date", *available]]

    if right.empty:
        merged = trading.assign(**{name: float("nan") for name in DAILY_FUNDAMENTAL_COLUMNS})
        merged[PUB_DATE_COLUMN] = pd.NaT
    else:
        ordered = trading.assign(_order=range(len(trading))).sort_values("date", kind="stable")
        merged = pd.merge_asof(
            ordered,
            right.sort_values("pub_date", kind="stable"),
            left_on="date",
            right_on="pub_date",
            by="symbol",
            direction="backward",
        )
        merged = merged.sort_values("_order", kind="stable").drop(columns=["_order"])
        merged = merged.rename(columns={"pub_date": PUB_DATE_COLUMN})
    for name in DAILY_FUNDAMENTAL_COLUMNS:
        if name not in merged.columns:
            merged[name] = float("nan")
    return merged[["symbol", "date", *DAILY_FUNDAMENTAL_COLUMNS, PUB_DATE_COLUMN]].reset_index(
        drop=True
    )
