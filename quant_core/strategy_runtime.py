"""策略选择与本地自定义策略加载。

本模块不读取 ``st.session_state``。调用方需要显式传入策略名称、参数和代码。
注意：Python ``exec`` 无法安全执行互联网用户提交的代码；``trusted_code`` 默认
关闭。当前 Streamlit 是个人本地工具，因此兼容层会显式开启它。未来公开网站
必须把自定义代码交给受限的一次性容器，而不能在 FastAPI 进程中开启此选项。
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from strategies import generate_right_signal, generate_v_shape_signal


def resolve_strategy(
    name: str,
    parameters: Mapping[str, Any] | None = None,
    custom_code: str = "",
    *,
    trusted_code: bool = False,
) -> tuple[Callable, dict[str, Any], str]:
    """把策略配置解析为 ``(信号函数, 参数, 展示名称)``。"""
    params = dict(parameters or {})

    if "右侧趋势" in name:
        defaults = {"ma_short": 5, "ma_mid": 20, "ma_long": 60, "vol_ratio": 1.5}
        defaults.update(params)
        return generate_right_signal, defaults, name

    if "V型反转" in name or "v_shape" in name.lower():
        defaults = {"lookback": 10, "drop_threshold": 0.15, "rebound_threshold": 0.01, "vol_ratio": 1.3}
        defaults.update(params)
        return generate_v_shape_signal, defaults, name

    if custom_code:
        if not trusted_code:
            raise PermissionError("自定义 Python 策略只能在受信任环境或隔离容器中执行")
        # globals 与 locals 使用同一命名空间，否则策略顶层 import 的模块不会
        # 出现在 generate_signal 的全局变量中，函数实际调用时会报 NameError。
        namespace: dict[str, Any] = {"__builtins__": __builtins__}
        exec(compile(custom_code, "<custom_strategy>", "exec"), namespace)
        strategy = namespace.get("generate_signal")
        if not callable(strategy):
            raise ValueError("自定义策略必须定义 generate_signal 函数")

        signature = inspect.signature(strategy)
        accepts_kwargs = any(
            item.kind == inspect.Parameter.VAR_KEYWORD
            for item in signature.parameters.values()
        )
        if not accepts_kwargs and len(signature.parameters) <= 1:
            def wrapped(data, **_kwargs):
                return strategy(data)

            return wrapped, {}, name
        return strategy, params, name

    # 未知或未完整配置的策略回退到稳定的内置默认值。
    return generate_right_signal, {
        "ma_short": 5,
        "ma_mid": 20,
        "ma_long": 60,
        "vol_ratio": 1.5,
    }, name
