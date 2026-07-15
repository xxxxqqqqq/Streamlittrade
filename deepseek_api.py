"""
模块：DeepSeek API 客户端 (deepseek_api.py)
功能：封装 DeepSeek API 的调用、响应解析、代码提取与验证逻辑
依赖：streamlit (session_state), requests, re, config.SYSTEM_PROMPT
"""
import streamlit as st
import requests
import re


# ============================================================
# 核心 API 调用函数
# ============================================================

def call_deepseek(messages, model="deepseek-v4-pro", temperature=0.1, max_tokens=8000):
    """
    调用 DeepSeek Chat API 生成策略代码
    使用 requests 库直接发送 HTTP 请求，避免 openai 库的编码兼容问题

    Args:
        messages:    对话消息列表，格式为 [{"role": "...", "content": "..."}, ...]
        model:       模型名称，默认 deepseek-v4-pro（最强推理模型）
        temperature: 生成温度 (0~2)，越低输出越确定/代码越严谨，默认 0.1（代码生成推荐）
        max_tokens:  最大输出 token 数，默认 8000（确保复杂策略代码不被截断）

    Returns:
        str: 生成的文本内容，或以 "[ERROR] ..." 开头的错误信息
    """
    # 从 session_state 获取用户输入的 API Key
    api_key = st.session_state.get("deepseek_api_key", "")
    if not api_key:
        return "[ERROR] 请先在侧边栏设置 DeepSeek API Key"

    # 构建 API 请求
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    # ---- 带重试的 API 调用 ----
    import time as _time
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=120)
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                _time.sleep(2)
                continue
            return f"[ERROR] API 请求超时（已重试{max_retries}次），v4-pro 模型推理较慢，请稍后再试"
        except requests.exceptions.HTTPError as e:
            return f"[ERROR] API 返回错误: {e.response.status_code}"
        except Exception as e:
            if attempt < max_retries:
                _time.sleep(2)
                continue
            return f"[ERROR] API 调用失败: {e}"


# ============================================================
# 代码提取与验证工具
# ============================================================

def extract_code(text):
    """
    从 DeepSeek 返回的文本中提取纯 Python 策略代码
    自动去除 Markdown 代码块标记（```python ... ```），
    并定位 generate_signal 函数定义

    Args:
        text: DeepSeek 返回的原始文本

    Returns:
        str: 提取后的纯 Python 代码
    """
    # 策略1: 匹配 Markdown 代码块 ```python ... ``` 或 ``` ... ```
    pattern = r"```(?:python)?\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)

    if matches:
        code = matches[0].strip()
        # 如果提取的代码中包含目标函数，直接返回
        if "def generate_signal" in code:
            return code
        # 否则从原文中按 def 关键字截取
        if "def generate_signal" in text:
            start = text.find("def generate_signal")
            code = text[start:].strip()
            if code.endswith("```"):
                code = code[:-3].strip()
            return code

    # 策略2: 无代码块标记，直接按 def generate_signal 定位
    if "def generate_signal" in text:
        start = text.find("def generate_signal")
        code = text[start:].strip()
        if code.endswith("```"):
            code = code[:-3].strip()
        return code

    # 兜底：返回原始文本
    return text.strip()


def validate_strategy_code(code):
    """
    验证策略代码是否符合基本规范：
    1. Python 语法正确（可编译）
    2. 包含 generate_signal 函数定义
    3. 函数体内有 return 语句

    Args:
        code: 待验证的策略代码字符串

    Returns:
        tuple: (is_valid: bool, message: str)
    """
    try:
        # 第一步：编译检查语法
        compile(code, "<string>", "exec")
    except SyntaxError as e:
        return False, f"语法错误: {e}"

    # 第二步：检查必要元素
    if "def generate_signal" not in code:
        return False, "未找到 generate_signal 函数定义"
    if "return" not in code:
        return False, "generate_signal 函数缺少 return 语句"

    return True, "代码验证通过"


# ============================================================
# 依赖自动安装工具
# ============================================================

# 常用 import 名 → pip 包名的映射（处理命名不一致的情况）
_PIP_NAME_MAP = {
    'sklearn': 'scikit-learn',
    'PIL': 'pillow',
    'bs4': 'beautifulsoup4',
    'cv2': 'opencv-python',
    'statsmodels': 'statsmodels',
    'scipy': 'scipy',
}


def ensure_dependencies(code):
    """
    扫描策略代码中的所有 import 语句，自动安装缺失的第三方库

    仅对非标准库进行检测和安装。对于映射表中已知的包名不一致问题
    （如 import sklearn → pip install scikit-learn），自动修正。

    Args:
        code: 策略代码字符串

    Returns:
        list: 已安装（或尝试安装）的包名列表，用于 UI 提示
    """
    import sys as _sys
    import subprocess as _sp
    import re as _re

    # 提取所有 import xxx 和 from xxx import 语句中的顶级包名
    imports = _re.findall(r'^\s*(?:import|from)\s+(\w+)', code, _re.MULTILINE)

    # 标准库白名单（不需要安装）
    stdlib = {
        'pandas', 'numpy', 're', 'os', 'sys', 'math', 'time', 'json',
        'datetime', 'collections', 'itertools', 'functools', 'random',
        'warnings', 'typing', 'abc', 'copy', 'hashlib', 'io', 'logging',
        'pathlib', 'pickle', 'pprint', 'queue', 'statistics', 'string',
        'subprocess', 'threading', 'traceback', 'unittest', 'urllib',
        'xml', 'csv', 'enum', 'gc', 'inspect', 'operator', 'textwrap',
        '__future__', 'ast', 'base64', 'bisect', 'calendar', 'cmath',
        'concurrent', 'contextlib', 'dataclasses', 'decimal', 'fractions',
        'glob', 'gzip', 'html', 'http', 'importlib', 'ipaddress',
        'multiprocessing', 'numbers', 'platform', 'secrets', 'shutil',
        'socket', 'sqlite3', 'struct', 'tempfile', 'uuid', 'zipfile',
    }

    installed_list = []

    for lib_name in imports:
        # 跳过标准库
        if lib_name in stdlib:
            continue

        # 尝试导入，已安装则跳过
        try:
            __import__(lib_name)
            continue
        except ImportError:
            pass

        # 查找正确的 pip 包名
        pip_name = _PIP_NAME_MAP.get(lib_name, lib_name)

        # 调用 pip install
        try:
            _sp.check_call(
                [_sys.executable, "-m", "pip", "install", pip_name, "-q"],
                timeout=60
            )
            installed_list.append(pip_name)
        except Exception:
            pass  # 安装失败静默处理，exec 时会报具体 ImportError

    return installed_list
