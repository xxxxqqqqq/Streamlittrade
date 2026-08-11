"""Safe, versionable factor calculations used by the feature platform.

The expression implementation intentionally evaluates a small AST instead of
calling ``eval``.  Researchers can combine market columns and approved rolling
operators, while imports, attributes, indexing and arbitrary Python remain
impossible.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

np = None
pd = None


MARKET_FIELDS = frozenset({"open", "high", "low", "close", "volume"})
EXPRESSION_FUNCTIONS = frozenset(
    {
        "abs",
        "clip",
        "delta",
        "ema",
        "lag",
        "log",
        "max",
        "mean",
        "min",
        "pct_change",
        "sqrt",
        "std",
        "sum",
    }
)


@dataclass(frozen=True)
class FactorTemplate:
    implementation: str
    name: str
    family: str
    description: str
    default_window: int


FACTOR_LIBRARY = (
    FactorTemplate("return", "区间收益率", "momentum", "收盘价过去N日收益率", 20),
    FactorTemplate("log_return", "对数收益率", "momentum", "收盘价过去N日对数收益率", 20),
    FactorTemplate("moving_average_bias", "均线偏离", "trend", "收盘价相对N日均线的偏离", 20),
    FactorTemplate("volatility", "收益波动率", "risk", "日收益率的N日标准差", 20),
    FactorTemplate("downside_volatility", "下行波动率", "risk", "负收益的N日标准差", 20),
    FactorTemplate("volume_ratio", "成交量比率", "liquidity", "成交量相对N日均量的比值", 20),
    FactorTemplate("rsi", "相对强弱指标", "technical", "N日RSI技术指标", 14),
    FactorTemplate("price_position", "价格区间位置", "technical", "收盘价在N日高低区间的位置", 20),
    FactorTemplate("atr", "真实波幅", "risk", "N日平均真实波幅相对价格的比例", 14),
    FactorTemplate("amplitude", "日内振幅", "risk", "日内高低价差相对开盘价的比例", 1),
    FactorTemplate("overnight_gap", "隔夜跳空", "technical", "开盘价相对前收盘价的变化", 1),
    FactorTemplate("illiquidity", "非流动性", "liquidity", "绝对收益相对成交额代理的N日均值", 20),
    FactorTemplate("skewness", "收益偏度", "risk", "日收益率的N日滚动偏度", 20),
    FactorTemplate("momentum_acceleration", "动量加速度", "momentum", "短周期与长周期动量之差", 20),
    FactorTemplate("short_term_reversal", "短期反转", "behavioral", "近期过度涨跌后的价格回归代理", 5),
    FactorTemplate("relative_strength_12_1", "12-1动量", "momentum", "跳过最近一月的中长期相对强度", 252),
    FactorTemplate("trend_quality", "趋势质量", "quality", "单位波动率所承载的区间收益", 60),
    FactorTemplate("drawdown", "回撤压力", "risk", "当前价格相对近期高点的回撤", 60),
    FactorTemplate("liquidity_trend", "流动性趋势", "liquidity", "近期成交额相对前期的改善程度", 20),
    FactorTemplate("turnover_stability", "成交稳定性", "liquidity", "成交额变异系数的相反数", 20),
    FactorTemplate("volume_price_confirmation", "量价确认", "behavioral", "收益方向与异常成交量的共振", 20),
)

BUILTIN_IMPLEMENTATIONS = frozenset(item.implementation for item in FACTOR_LIBRARY)
ALLOWED_IMPLEMENTATIONS = BUILTIN_IMPLEMENTATIONS | {"expression"}


def _ensure_numeric_libraries() -> None:
    """Load worker-only numeric dependencies without bloating API startup."""

    global np, pd
    if np is None or pd is None:
        import numpy as numpy_module
        import pandas as pandas_module

        np, pd = numpy_module, pandas_module


def factor_library_payload() -> list[dict[str, Any]]:
    """Return serializable metadata for the frontend factor library."""

    return [
        {
            "implementation": item.implementation,
            "name": item.name,
            "family": item.family,
            "description": item.description,
            "default_window": item.default_window,
        }
        for item in FACTOR_LIBRARY
    ]


def _positive_integer(value: Any, name: str, *, maximum: int = 500) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    number = int(value)
    if number < 1 or number > maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")
    return number


def validate_factor_parameters(implementation: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Normalize parameters and validate expressions before persistence."""

    if implementation not in ALLOWED_IMPLEMENTATIONS:
        raise ValueError(f"Unsupported factor implementation: {implementation}")
    normalized = dict(parameters)
    if implementation == "expression":
        expression = str(normalized.get("expression", "")).strip()
        validate_expression(expression)
        normalized["expression"] = expression
    elif implementation == "momentum_acceleration":
        short_window = _positive_integer(normalized.get("short_window", 5), "short_window")
        long_window = _positive_integer(normalized.get("long_window", 20), "long_window")
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        normalized.update(short_window=short_window, long_window=long_window)
    else:
        normalized["window"] = _positive_integer(normalized.get("window", 20), "window")
    return normalized


def validate_expression(expression: str) -> None:
    """Reject any syntax outside the bounded factor expression language."""

    if not expression or len(expression) > 500:
        raise ValueError("expression must contain between 1 and 500 characters")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression: {exc.msg}") from exc
    nodes = list(ast.walk(tree))
    if len(nodes) > 100:
        raise ValueError("expression is too complex")
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Call,
        ast.Name,
        ast.Load,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.USub,
        ast.UAdd,
    )
    for node in nodes:
        if not isinstance(node, allowed_nodes):
            raise ValueError(f"expression syntax is not allowed: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in MARKET_FIELDS | EXPRESSION_FUNCTIONS:
            raise ValueError(f"unknown field or function: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in EXPRESSION_FUNCTIONS:
                raise ValueError("only approved factor functions may be called")
            if node.keywords:
                raise ValueError("keyword arguments are not supported")
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                raise ValueError("only numeric constants are supported")
            if abs(float(node.value)) > 1_000_000:
                raise ValueError("numeric constant is too large")
        if isinstance(node, ast.Pow) and isinstance(node.right, ast.Constant):
            if abs(float(node.right.value)) > 8:
                raise ValueError("power exponent is too large")


def _window_argument(node: ast.AST, evaluator: "_ExpressionEvaluator") -> int:
    value = evaluator.evaluate(node)
    if isinstance(value, pd.Series):
        raise ValueError("rolling window must be a constant")
    return _positive_integer(value, "window")


class _ExpressionEvaluator:
    """Recursive evaluator for the approved expression AST."""

    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def evaluate(self, node: ast.AST) -> pd.Series | float:
        if isinstance(node, ast.Expression):
            return self.evaluate(node.body)
        if isinstance(node, ast.Name):
            return self.frame[node.id].astype(float)
        if isinstance(node, ast.Constant):
            return float(node.value)
        if isinstance(node, ast.UnaryOp):
            value = self.evaluate(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            left, right = self.evaluate(node.left), self.evaluate(node.right)
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                if isinstance(node.op, ast.Div):
                    return left / right
                if isinstance(node.op, ast.Mod):
                    return left % right
                if isinstance(node.op, ast.Pow):
                    return left**right
        if isinstance(node, ast.Call):
            return self._call(node)
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")

    def _call(self, node: ast.Call) -> pd.Series:
        name = node.func.id
        if not node.args:
            raise ValueError(f"{name} requires arguments")
        value = self.evaluate(node.args[0])
        if not isinstance(value, pd.Series):
            value = pd.Series(float(value), index=self.frame.index)
        if name in {"abs", "log", "sqrt"}:
            if len(node.args) != 1:
                raise ValueError(f"{name} accepts one argument")
            if name == "abs":
                return value.abs()
            if name == "log":
                return np.log(value.where(value > 0))
            return np.sqrt(value.where(value >= 0))
        if name == "clip":
            if len(node.args) != 3:
                raise ValueError("clip(value, lower, upper) requires three arguments")
            lower, upper = self.evaluate(node.args[1]), self.evaluate(node.args[2])
            if isinstance(lower, pd.Series) or isinstance(upper, pd.Series):
                raise ValueError("clip bounds must be constants")
            return value.clip(float(lower), float(upper))
        if len(node.args) != 2:
            raise ValueError(f"{name} requires a value and window")
        window = _window_argument(node.args[1], self)
        if name == "lag":
            return value.shift(window)
        if name == "delta":
            return value.diff(window)
        if name == "pct_change":
            return value.pct_change(window)
        if name == "mean":
            return value.rolling(window).mean()
        if name == "std":
            return value.rolling(window).std()
        if name == "min":
            return value.rolling(window).min()
        if name == "max":
            return value.rolling(window).max()
        if name == "sum":
            return value.rolling(window).sum()
        if name == "ema":
            return value.ewm(span=window, adjust=False, min_periods=window).mean()
        raise ValueError(f"Unsupported expression function: {name}")


def evaluate_expression(frame: pd.DataFrame, expression: str) -> pd.Series:
    _ensure_numeric_libraries()
    validate_expression(expression)
    result = _ExpressionEvaluator(frame).evaluate(ast.parse(expression, mode="eval"))
    if not isinstance(result, pd.Series):
        result = pd.Series(float(result), index=frame.index)
    return result.replace([np.inf, -np.inf], np.nan)


def compute_factor(group: pd.DataFrame, implementation: str, parameters: dict[str, Any]) -> pd.Series:
    """Compute one factor for one symbol, preserving the group's index."""

    _ensure_numeric_libraries()
    parameters = validate_factor_parameters(implementation, parameters)
    close = group["close"].astype(float)
    window = int(parameters.get("window", 20))
    returns = close.pct_change()
    if implementation == "expression":
        return evaluate_expression(group, str(parameters["expression"]))
    if implementation == "return":
        return close.pct_change(window)
    if implementation == "log_return":
        return np.log(close / close.shift(window))
    if implementation == "moving_average_bias":
        return close / close.rolling(window).mean() - 1
    if implementation == "volatility":
        return returns.rolling(window).std()
    if implementation == "downside_volatility":
        return returns.where(returns < 0, 0).rolling(window).std()
    if implementation == "volume_ratio":
        return group["volume"].astype(float) / group["volume"].astype(float).rolling(window).mean()
    if implementation == "rsi":
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window).mean()
        loss = (-delta.clip(upper=0)).rolling(window).mean()
        return 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    if implementation == "price_position":
        low = group["low"].astype(float).rolling(window).min()
        high = group["high"].astype(float).rolling(window).max()
        return (close - low) / (high - low).replace(0, np.nan)
    if implementation == "atr":
        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                group["high"].astype(float) - group["low"].astype(float),
                (group["high"].astype(float) - previous_close).abs(),
                (group["low"].astype(float) - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        return true_range.rolling(window).mean() / close
    if implementation == "amplitude":
        return (group["high"].astype(float) - group["low"].astype(float)) / group["open"].astype(float).replace(0, np.nan)
    if implementation == "overnight_gap":
        return group["open"].astype(float) / close.shift(1) - 1
    if implementation == "illiquidity":
        amount_proxy = close * group["volume"].astype(float)
        return (returns.abs() / amount_proxy.replace(0, np.nan)).rolling(window).mean()
    if implementation == "skewness":
        return returns.rolling(window).skew()
    if implementation == "momentum_acceleration":
        short_window = int(parameters["short_window"])
        long_window = int(parameters["long_window"])
        return close.pct_change(short_window) - close.pct_change(long_window)
    if implementation == "short_term_reversal":
        return -close.pct_change(window)
    if implementation == "relative_strength_12_1":
        skip = max(1, window // 12)
        return close.shift(skip) / close.shift(window) - 1
    if implementation == "trend_quality":
        realized = returns.rolling(window).std() * np.sqrt(window)
        return close.pct_change(window) / realized.replace(0, np.nan)
    if implementation == "drawdown":
        return close / close.rolling(window).max() - 1
    if implementation == "liquidity_trend":
        turnover = close * group["volume"].astype(float)
        recent = turnover.rolling(window).mean()
        return recent / recent.shift(window) - 1
    if implementation == "turnover_stability":
        turnover = close * group["volume"].astype(float)
        mean = turnover.rolling(window).mean()
        return -(turnover.rolling(window).std() / mean.replace(0, np.nan))
    if implementation == "volume_price_confirmation":
        volume = group["volume"].astype(float)
        # A suspended stock legitimately has zero volume.  Its logarithmic
        # volume surprise is undefined, not positive/negative infinity.
        volume_ratio = volume / volume.rolling(window).mean().replace(0, np.nan)
        abnormal_volume = np.log(volume_ratio.where(volume_ratio > 0))
        return close.pct_change(window) * abnormal_volume
    raise ValueError(f"Unsupported factor implementation: {implementation}")
