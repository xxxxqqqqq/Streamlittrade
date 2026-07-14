import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import time
import warnings
import baostock as bs
import re
import os
import requests
import json
from dotenv import load_dotenv
from openai import OpenAI


try:
    from streamlit_ace import st_ace
    ACE_AVAILABLE = True
except ImportError:
    ACE_AVAILABLE = False

# ============================================================
# 0. 引入deepseek用于生成自定义策略
# ============================================================
# 加载 .env 文件（如果存在）
load_dotenv()

# 获取 API Key（优化为动态获取）
DEEPSEEK_API_KEY = ""

warnings.filterwarnings('ignore')

def get_deepseek_client():
    """初始化 DeepSeek 客户端"""
    return OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com"
    )

def call_deepseek(messages, model="deepseek-chat", temperature=0.3, max_tokens=2000):
    """
    使用 requests 直接调用 DeepSeek API，避免编码问题
    """
    print(messages)  # 调试时查看
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    try:
        # 确保 JSON 序列化时保留中文字符
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except requests.exceptions.RequestException as e:
        return f"[ERROR] API 调用失败: {e}"
    except KeyError:
        return f"[ERROR] API 返回格式异常: {response.text}"


def extract_code(text):
    """
    从 DeepSeek 返回的文本中提取 Python 代码
    支持多种格式：
    - ```python ... ```
    - ``` ... ```
    - 直接包含 def generate_signal 的代码块
    """
    # 尝试匹配 Markdown 代码块
    pattern = r"```(?:python)?\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        code = matches[0].strip()
        # 如果提取出的代码仍包含多余字符，尝试只保留 def 之后的内容
        if "def generate_signal" in code:
            return code
        else:
            # 可能匹配到了非 Python 代码块，继续尝试其他方法
            pass

    # 如果没有代码块标记，尝试查找 "def generate_signal" 并截取到文件末尾
    if "def generate_signal" in text:
        # 从 def 开始截取，直到结束
        start = text.find("def generate_signal")
        code = text[start:].strip()
        # 去除可能的后缀 Markdown 标记
        if code.endswith("```"):
            code = code[:-3].strip()
        return code

    # 否则直接返回原文本（去除首尾空白）
    return text.strip()


def validate_strategy_code(code):
    """验证生成的代码是否包含必要的函数和语法正确"""
    # 调试：打印前200字符
    print("=== 提取的代码预览 ===")
    print(code[:200])
    print("=== 代码结束 ===")

    try:
        compile(code, "<string>", "exec")
        # 检查是否包含 generate_signal 函数
        if "def generate_signal" not in code:
            return False, "未找到 generate_signal 函数"
        if "return" not in code:
            return False, "函数缺少 return 语句"
        return True, "代码验证通过"
    except SyntaxError as e:
        return False, f"语法错误: {e}"

# ============================================================
# 1. 数据获取（基于 Baostock，带缓存）
# ============================================================

@st.cache_data(ttl=3600)
def fetch_stock_data(symbol, start_date, end_date, max_retries=2):
    """
    使用 Baostock 获取 A 股历史日线数据（前复权）
    仅使用内存缓存，不保存到本地硬盘
    """
    # 日期格式转换
    start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
    end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"

    # 转换代码格式
    if symbol.startswith('6'):
        bs_code = f"sh.{symbol}"
    elif symbol.startswith('0') or symbol.startswith('3'):
        bs_code = f"sz.{symbol}"
    else:
        bs_code = f"sz.{symbol}"

    # 网络请求（带重试）
    for attempt in range(max_retries):
        try:
            lg = bs.login()
            if lg.error_code != '0':
                raise Exception(f"Baostock 登录失败: {lg.error_msg}")

            rs = bs.query_history_k_data_plus(
                code=bs_code,
                fields="date,open,high,low,close,volume",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="2"  # 前复权
            )
            if rs.error_code != '0':
                raise Exception(f"查询失败: {rs.error_msg}")

            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())
            if not data_list:
                raise ValueError("返回数据为空")

            df = pd.DataFrame(data_list, columns=rs.fields)
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            bs.logout()

            # 去重、排序
            df = df[~df.index.duplicated(keep='first')]
            df = df.sort_index()

            return df

        except Exception as e:
            bs.logout()
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                st.warning(f"数据获取失败，{wait_time}秒后重试... ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
            else:
                st.error(f"获取 {symbol} 数据失败，已重试 {max_retries} 次: {e}")
                return None
    return None

# ============================================================
# 2. 策略信号生成
# ============================================================
def generate_right_signal(df,
                          ma_short=5,
                          ma_mid=20,
                          ma_long=60,
                          vol_ratio=1.5,
                          rsi_period=14,
                          rsi_upper=70,
                          rsi_lower=50,
                          kdj_n=9,
                          kdj_m1=3,
                          kdj_m2=3):
    """
    增强版右侧信号：增加RSI过滤，MACD红柱持续放大，利用score分层
    """
    data = df.copy()
    data = data[~data.index.duplicated(keep='first')]
    data = data.sort_index()

    # 均线
    data['MA5'] = data['close'].rolling(ma_short).mean()
    data['MA20'] = data['close'].rolling(ma_mid).mean()
    data['MA60'] = data['close'].rolling(ma_long).mean()

    # MACD
    exp1 = data['close'].ewm(span=12, adjust=False).mean()
    exp2 = data['close'].ewm(span=26, adjust=False).mean()
    data['DIF'] = exp1 - exp2
    data['DEA'] = data['DIF'].ewm(span=9, adjust=False).mean()
    data['MACD_bar'] = (data['DIF'] - data['DEA']) * 2
    data['MACD_bar_shift'] = data['MACD_bar'].shift(1)   # 新增：前一日红绿柱

    # 成交量
    data['VOL_MA20'] = data['volume'].rolling(20).mean()

    # RSI
    delta = data['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
    rs = gain / loss
    data['RSI'] = 100 - (100 / (1 + rs))

    # KDJ
    low_min = data['low'].rolling(kdj_n).min()
    high_max = data['high'].rolling(kdj_n).max()
    data['RSV'] = (data['close'] - low_min) / (high_max - low_min) * 100
    data['K'] = data['RSV'].ewm(span=kdj_m1, adjust=False).mean()
    data['D'] = data['K'].ewm(span=kdj_m2, adjust=False).mean()
    data['J'] = 3 * data['K'] - 2 * data['D']

    # 条件构建
    cond1 = (data['MA5'] > data['MA20']) & (data['MA20'] > data['MA60'])   # 均线多头
    cond2 = (data['DIF'] > data['DEA']) & (data['DIF'] > 0)               # MACD零上金叉
    cond3 = data['volume'] > data['VOL_MA20'] * vol_ratio                 # 放量突破
    cond4 = data['close'] > data['MA60']                                  # 站上生命线
    cond5 = (data['K'] > data['D']) & (data['J'] > 20)                    # KDJ金叉
    cond6 = (data['RSI'] > rsi_lower) & (data['RSI'] < rsi_upper)         # RSI强势
    cond7 = data['MACD_bar'] > data['MACD_bar_shift']                     # MACD红柱放大

    # 核心条件：前4项必须满足
    core_signal = cond1 & cond2 & cond3 & cond4

    # 总得分
    data['score'] = (cond1.astype(int) + cond2.astype(int) + cond3.astype(int) +
                     cond4.astype(int) + cond5.astype(int) + cond6.astype(int) + cond7.astype(int))

    # 信号：核心 + (RSI或MACD放大)
    data['signal'] = core_signal & (cond6 | cond7)
    data['signal_type'] = 'right'

    return data

def generate_v_shape_signal(df, lookback=10, drop_threshold=0.15,
                            rebound_threshold=0.01, vol_ratio=1.3, confirm_days=2):
    data = df.copy()
    data = data[~data.index.duplicated(keep='first')]
    data = data.sort_index()

    data['signal'] = False
    data['signal_type'] = 'v_shape'
    data['VOL_MA20'] = data['volume'].rolling(20).mean()

    # 新增列用于存储触发时的参数
    data['drop_used'] = np.nan
    data['rebound_used'] = np.nan
    data['vol_ratio_used'] = np.nan

    for i in range(lookback + confirm_days + 5, len(data)):
        window = data.iloc[i - lookback: i + 1]
        if len(window) < lookback + 1:
            continue

        recent_high = window['high'].max()
        recent_low = window['low'].min()
        max_drawdown = (recent_high - recent_low) / recent_high
        if max_drawdown < drop_threshold:
            continue

        low_idx = window['low'].idxmin()
        low_price = window.loc[low_idx, 'low']
        low_pos = window.index.get_loc(low_idx)

        after_low = window.iloc[low_pos + 1:]
        if len(after_low) < confirm_days:
            continue
        if after_low['low'].iloc[:confirm_days].min() <= low_price:
            continue

        current_close = data.iloc[i]['close']
        rebound = (current_close - low_price) / low_price
        if rebound < rebound_threshold:
            continue

        vol_ratio_curr = data.iloc[i]['volume'] / data.iloc[i]['VOL_MA20']
        if vol_ratio_curr < vol_ratio:
            continue

        # 使用 .iloc 赋值，避免索引长度问题
        data.iloc[i, data.columns.get_loc('signal')] = True
        data.iloc[i, data.columns.get_loc('drop_used')] = max_drawdown
        data.iloc[i, data.columns.get_loc('rebound_used')] = rebound
        data.iloc[i, data.columns.get_loc('vol_ratio_used')] = vol_ratio_curr

    return data

# ============================================================
# DeepSeek 策略代码生成器
# ============================================================

SYSTEM_PROMPT = """你是一个量化交易策略代码生成助手。你的任务是根据用户的自然语言描述，生成符合以下规范的 Python 策略代码。

【代码规范】
1. 必须定义一个名为 `generate_signal` 的函数
2. 函数接收一个参数 `df`（Pandas DataFrame，包含 open, high, low, close, volume 列）
3. 函数必须返回一个 DataFrame，包含以下列：
   - 'signal': 布尔类型，True 表示买入信号
   - 'signal_type': 字符串，固定为 'custom'
4. 可以在函数内部计算任何技术指标（MA, MACD, RSI, KDJ 等）
5. 代码需要包含必要的 import 语句（如 import pandas as pd, import numpy as np）

【输出要求 - 极其重要】
- 只输出 Python 纯代码，不要使用任何 Markdown 代码块标记（如 ```python 或 ```）
- 不要添加任何解释文字、注释（除代码内必要的注释外）
- 输出内容必须从 `import` 或 `def` 直接开始，以 `return data` 结束
- 代码必须可以直接复制并运行，无语法错误

【示例】
用户说："当5日均线上穿20日均线时买入"
你应输出：
import pandas as pd
import numpy as np

def generate_signal(df):
    data = df.copy()
    data['MA5'] = data['close'].rolling(5).mean()
    data['MA20'] = data['close'].rolling(20).mean()
    data['signal'] = (data['MA5'] > data['MA20']) & (data['MA5'].shift(1) <= data['MA20'].shift(1))
    data['signal_type'] = 'custom'
    return data

现在，请根据用户的策略描述生成代码，严格遵守纯代码输出要求。"""


def call_deepseek(messages, model="deepseek-chat", temperature=0.3, max_tokens=2000):
    """调用 DeepSeek API，从 session_state 获取 API Key"""
    api_key = st.session_state.get("deepseek_api_key", "")
    if not api_key:
        return "[ERROR] 请先在侧边栏设置 DeepSeek API Key"

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
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"[ERROR] API 调用失败: {e}"

def extract_code(text):
    """
    从 DeepSeek 返回的文本中提取 Python 代码（去除 markdown 代码块标记）
    """
    pattern = r"```(?:python)?\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return matches[0].strip() if matches else text.strip()

def validate_strategy_code(code):
    """
    验证生成的代码是否包含必要的函数和语法正确
    """
    try:
        compile(code, "<string>", "exec")
        if "def generate_signal" not in code:
            return False, "未找到 generate_signal 函数"
        if "return" not in code:
            return False, "函数缺少 return 语句"
        return True, "代码验证通过"
    except SyntaxError as e:
        return False, f"语法错误: {e}"

# ============================================================
# 3. 回测引擎（修复了每日权益记录）
# ============================================================

def run_backtest(df, initial_cash=100000, commission=0.0003, slippage=0.001,
                 stop_loss=0.08, take_profit=0.20, trailing_stop=0.05,
                 max_hold_days=20, position_pct=0.30):
    data = df.copy()
    data = data[data['signal'].notna()]
    if data.empty:
        return None, None, {'error': '无有效数据'}

    # 确保 MA20 存在（用于右侧趋势止损）
    if 'MA20' not in data.columns:
        data['MA20'] = data['close'].rolling(20).mean()

    cash = initial_cash
    position = 0
    entry_price = 0
    highest_price = 0
    hold_days = 0
    in_position = False
    trades = []
    daily_equity = []

    for i in range(len(data)):
        current_date = data.index[i]
        current_price = data.iloc[i]['close']
        current_high = data.iloc[i]['high']
        current_signal = data.iloc[i]['signal']
        signal_type = data.iloc[i].get('signal_type', 'unknown')

        sold_this_step = False  # 标记本次迭代是否刚卖出

        # ---------- 持仓处理 ----------
        if in_position:
            hold_days += 1
            highest_price = max(highest_price, current_high)

            should_sell = False
            sell_reason = ""

            if hold_days >= 2:  # T+1
                if current_price <= entry_price * (1 - stop_loss):
                    should_sell = True
                    sell_reason = f"硬止损 (-{stop_loss*100:.0f}%)"
                elif current_price <= highest_price * (1 - trailing_stop):
                    should_sell = True
                    sell_reason = f"移动止损 (回撤{trailing_stop*100:.0f}%)"
                elif current_price >= entry_price * (1 + take_profit):
                    should_sell = True
                    sell_reason = f"目标止盈 (+{take_profit*100:.0f}%)"
                elif signal_type == 'right' and current_price < data.iloc[i]['MA20']:
                    should_sell = True
                    sell_reason = "趋势止损 (跌破MA20)"
                elif signal_type == 'v_shape' and hold_days >= max_hold_days:
                    should_sell = True
                    sell_reason = f"时间止损 (持有{hold_days}天)"

            if should_sell:
                sell_price = current_price * (1 - slippage)
                fee = sell_price * position * commission
                cash += sell_price * position - fee
                profit = (sell_price - entry_price) / entry_price
                trades.append({
                    'date': current_date,
                    'action': 'SELL',
                    'price': round(sell_price, 3),
                    'profit_pct': round(profit * 100, 2),
                    'hold_days': hold_days,
                    'reason': sell_reason
                })
                position = 0
                in_position = False
                entry_price = 0
                sold_this_step = True
                # 不 continue，继续执行后续记录权益

        # ---------- 买入（仅当未持仓且本步未卖出） ----------
        # 在买入代码块中（约在 run_backtest 的中间部分）
        if not in_position and not sold_this_step and current_signal:
            buy_price = current_price * (1 + slippage)
            portfolio_value = cash + position * buy_price
            target_value = portfolio_value * position_pct
            size = int(target_value / buy_price)
            if size > 0 and cash > buy_price * size:
                fee = buy_price * size * commission
                if cash >= buy_price * size + fee:
                    cash -= buy_price * size + fee
                    position = size
                    entry_price = buy_price
                    highest_price = buy_price
                    hold_days = 0
                    in_position = True
                    # 生成买入原因
                    entry_reason = get_entry_reason(data.iloc[i], signal_type)
                    trades.append({
                        'date': current_date,
                        'action': 'BUY',
                        'price': round(buy_price, 3),
                        'size': size,
                        'signal_type': signal_type,
                        'entry_reason': entry_reason  # 新增字段
                    })

        # ---------- 每日权益记录（必须执行） ----------
        if in_position:
            equity = cash + position * current_price
        else:
            equity = cash
        daily_equity.append(equity)

    # 若最后仍持仓，强制平仓
    if in_position and position > 0:
        last_price = data.iloc[-1]['close'] * (1 - slippage)
        cash += last_price * position
        profit = (last_price - entry_price) / entry_price
        trades.append({
            'date': data.index[-1],
            'action': 'SELL',
            'price': round(last_price, 3),
            'profit_pct': round(profit * 100, 2),
            'hold_days': hold_days,
            'reason': '期末平仓'
        })
        position = 0
        in_position = False

    # 生成交易记录和权益序列
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    # 长度应与 data 一致
    equity_series = pd.Series(daily_equity, index=data.index)
    metrics = calculate_metrics(daily_equity, trades)

    return trades_df, equity_series, metrics


def get_entry_reason(row, signal_type):
    """根据信号类型和行数据生成买入原因描述"""
    if signal_type == 'right':
        reasons = []
        # 均线多头
        if row.get('MA5', 0) > row.get('MA20', 0) and row.get('MA20', 0) > row.get('MA60', 0):
            reasons.append('均线多头')
        # MACD零上金叉
        if row.get('DIF', 0) > row.get('DEA', 0) and row.get('DIF', 0) > 0:
            reasons.append('MACD金叉')
        # 放量
        if row.get('volume', 0) > row.get('VOL_MA20', 1) * 1.5:
            reasons.append('放量')
        # 站上60日线
        if row.get('close', 0) > row.get('MA60', 0):
            reasons.append('站上60日线')
        # KDJ金叉
        if row.get('K', 0) > row.get('D', 0) and row.get('J', 0) > 20:
            reasons.append('KDJ金叉')
        # RSI强势（50~70）
        if 'RSI' in row and 50 < row['RSI'] < 70:
            reasons.append('RSI强势')
        # MACD红柱放大
        if 'MACD_bar' in row and 'MACD_bar_shift' in row:
            if row['MACD_bar'] > row['MACD_bar_shift']:
                reasons.append('MACD放大')
        return ' | '.join(reasons) if reasons else '右侧信号'

    elif signal_type == 'v_shape':
        drop = row.get('drop_used', np.nan)
        rebound = row.get('rebound_used', np.nan)
        vol_ratio_used = row.get('vol_ratio_used', np.nan)
        parts = []
        if not np.isnan(drop):
            parts.append(f"跌幅{drop*100:.1f}%")
        if not np.isnan(rebound):
            parts.append(f"反弹{rebound*100:.1f}%")
        if not np.isnan(vol_ratio_used):
            parts.append(f"量比{vol_ratio_used:.2f}")
        return ' | '.join(parts) if parts else 'V型反转'

    elif signal_type == 'custom':
        return '自定义策略'

    else:
        return '未知信号'

def calculate_metrics(daily_equity, trades):
    if not daily_equity or len(daily_equity) < 2:
        return {'error': '数据不足'}

    equity_series = pd.Series(daily_equity)
    returns = equity_series.pct_change().dropna()

    total_return = (equity_series.iloc[-1] / equity_series.iloc[0] - 1) * 100
    days = len(daily_equity)
    annual_return = ((1 + total_return / 100) ** (250 / days) - 1) * 100 if days > 0 else 0

    cum_max = equity_series.expanding().max()
    drawdown = (equity_series - cum_max) / cum_max
    max_drawdown = drawdown.min() * 100

    risk_free = 0.03 / 250
    sharpe = (returns.mean() - risk_free) / returns.std() * np.sqrt(250) if returns.std() > 0 else 0

    sell_trades = [t for t in trades if t['action'] == 'SELL']
    total_trades = len(sell_trades)
    win_trades = [t for t in sell_trades if t['profit_pct'] > 0]
    loss_trades = [t for t in sell_trades if t['profit_pct'] <= 0]
    win_rate = len(win_trades) / total_trades * 100 if total_trades > 0 else 0

    avg_win = np.mean([t['profit_pct'] for t in win_trades]) if win_trades else 0
    avg_loss = abs(np.mean([t['profit_pct'] for t in loss_trades])) if loss_trades else 1
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

    avg_hold_days = np.mean([t['hold_days'] for t in sell_trades]) if sell_trades else 0

    return {
        'total_return': round(total_return, 2),
        'annual_return': round(annual_return, 2),
        'max_drawdown': round(max_drawdown, 2),
        'sharpe_ratio': round(sharpe, 3),
        'total_trades': total_trades,
        'win_trades': len(win_trades),
        'loss_trades': len(loss_trades),
        'win_rate': round(win_rate, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_loss_ratio': round(profit_loss_ratio, 3),
        'avg_hold_days': round(avg_hold_days, 1),
        'final_equity': round(equity_series.iloc[-1], 2)
    }

# ============================================================
# 4. 可视化
# ============================================================

def plot_equity(equity_series):
    """净值曲线（与回撤曲线风格统一，浅色背景）"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity_series.index,
        y=equity_series,
        mode='lines',
        name='净值',
        line=dict(color='#1f77b4', width=2.5),
        line_shape='spline'  # 平滑
    ))
    fig.update_layout(
        title='净值曲线',
        height=400,
        margin=dict(l=40, r=40, t=40, b=40)  # 控制标题与图间距
    )
    fig.update_yaxes(title_text="净值")
    return fig


def plot_kline_with_signals(data, trades_df):
    """K线图与买卖点（含成交量副图），浅色背景，支持拖拽缩放"""
    # 创建子图：2行1列，共享X轴
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.05,
                        row_heights=[0.7, 0.3],
                        subplot_titles=('', ''))

    # ---- 上子图：K线 ----
    fig.add_trace(go.Candlestick(
        x=data.index,
        open=data['open'],
        high=data['high'],
        low=data['low'],
        close=data['close'],
        name='K线',
        increasing_line_color='#e74c3c',
        increasing_fillcolor='#e74c3c',
        decreasing_line_color='#2ecc71',
        decreasing_fillcolor='#2ecc71'
    ), row=1, col=1)

    # ---- 上子图：买卖点 ----
    if trades_df is not None and not trades_df.empty:
        buys = trades_df[trades_df['action'] == 'BUY']
        if not buys.empty:
            fig.add_trace(go.Scatter(
                x=buys['date'], y=buys['price'],
                mode='markers', name='买入',
                marker=dict(symbol='triangle-up', size=8,
                            color='white',
                            line=dict(color='#e74c3c', width=1.5)),
                hovertemplate='<b>买入</b><br>日期: %{x|%Y-%m-%d}<br>价格: %{y:.2f}<extra></extra>'
            ), row=1, col=1)
        sells = trades_df[trades_df['action'] == 'SELL']
        if not sells.empty:
            fig.add_trace(go.Scatter(
                x=sells['date'], y=sells['price'],
                mode='markers', name='卖出',
                marker=dict(symbol='triangle-down', size=8,
                            color='white',
                            line=dict(color='#2ecc71', width=1.5)),
                hovertemplate='<b>卖出</b><br>日期: %{x|%Y-%m-%d}<br>价格: %{y:.2f}<extra></extra>'
            ), row=1, col=1)

    # ---- 下子图：成交量（红涨绿跌） ----
    colors = ['#e74c3c' if close >= open else '#2ecc71' 
              for close, open in zip(data['close'], data['open'])]
    fig.add_trace(go.Bar(
        x=data.index,
        y=data['volume'],
        name='成交量',
        marker=dict(color=colors),
        hovertemplate='<b>成交量</b><br>日期: %{x|%Y-%m-%d}<br>成交: %{y:,.0f}<extra></extra>'
    ), row=2, col=1)

    # ---- 全局布局 ----
    fig.update_layout(
        title=dict(
            text='K线图与买卖点',
            x=0.5,
            xanchor='center',
            y=0.98,
            yanchor='top'
        ),
        height=600,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            bgcolor='rgba(255,255,255,0.8)'
        ),
        margin=dict(l=40, r=40, t=60, b=40),
        hovermode='x unified'
    )

    # ---- X轴设置（底部子图显示时间选择器） ----
    fig.update_xaxes(
        row=2, col=1,
        rangeslider_visible=False,
        rangeselector=dict(
            buttons=list([
                dict(count=1, label="1个月", step="month", stepmode="backward"),
                dict(count=3, label="3个月", step="month", stepmode="backward"),
                dict(count=6, label="6个月", step="month", stepmode="backward"),
                dict(count=1, label="1年", step="year", stepmode="backward"),
                dict(step="all", label="全部")
            ]),
            bgcolor='#e9ecef',
            activecolor='#007bff',
            font_color='black',
            borderwidth=1
        ),
        title_text="日期"
    )
    # 上子图X轴不显示标签
    fig.update_xaxes(row=1, col=1, showticklabels=False)

    # ---- Y轴设置 ----
    # 上子图：显示价格
    fig.update_yaxes(title_text="价格", row=1, col=1)
    # 下子图：隐藏Y轴标题和刻度（不显示价格/数值）
    fig.update_yaxes(
        title_text="",               # 清空标题
        showticklabels=False,        # 隐藏刻度标签
        showgrid=False,              # 隐藏网格线（可选）
        zeroline=False,              # 隐藏零线（可选）
        row=2, col=1
    )

    return fig

def plot_drawdown(equity_series):
    cum_max = equity_series.expanding().max()
    drawdown = (equity_series - cum_max) / cum_max * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=drawdown.index, y=drawdown,
                             mode='lines', name='回撤 (%)', fill='tozeroy', line=dict(color='red')))
    fig.update_layout(title='最大回撤曲线', height=300)
    fig.update_yaxes(title_text="回撤 (%)")
    return fig

# ============================================================
# 5. Streamlit 界面
# ============================================================

st.set_page_config(page_title="量化回测系统", layout="wide")

# 初始化 session_state 中的 api_key
if "deepseek_api_key" not in st.session_state:
    st.session_state.deepseek_api_key = ""

# ============================================================
# 初始化会话状态（必须在任何访问之前）
# ============================================================
if "deepseek_messages" not in st.session_state:
    st.session_state.deepseek_messages = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
if "generated_code" not in st.session_state:
    st.session_state.generated_code = ""
if "custom_strategy_code" not in st.session_state:
    st.session_state.custom_strategy_code = ""

st.title("📈 量化策略回测系统")
st.markdown("支持右侧趋势策略 & V型反转策略 & 自定义交易策略 & AI生成策略，数据来自 Baostock")

with st.sidebar:
    st.markdown("---")
    st.subheader("🔑 API Key 设置")

    # 如果尚未保存 Key，显示输入框
    if not st.session_state.deepseek_api_key:
        api_key_input = st.text_input(
            "请输入 DeepSeek API Key",
            type="password",
            placeholder="sk-...",
            help="在 https://platform.deepseek.com/ 获取"
        )
        if st.button("保存 API Key"):
            if api_key_input.startswith("sk-"):
                st.session_state.deepseek_api_key = api_key_input
                st.success("API Key 已保存（仅本次会话有效）")
                st.rerun()
            else:
                st.error("请输入有效的 API Key（以 sk- 开头）")
    else:
        st.success("✅ API Key 已加载")
        if st.button("重置 API Key"):
            st.session_state.deepseek_api_key = ""
            st.rerun()
    st.header("⚙️ 参数设置")
    symbol = st.text_input("股票代码 (如 600160)", value="600160")
    start_date = st.date_input("开始日期", value=datetime(2020, 1, 1))
    end_date = st.date_input("结束日期", value=datetime.now())
    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")

    strategy_type = st.selectbox(
        "选择策略",
        ["右侧趋势策略", "V型反转策略", "自定义策略", "🤖 AI 生成策略"]
    )

    if strategy_type == "🤖 AI 生成策略":
        st.subheader("🤖 用自然语言描述你的策略")
        st.markdown("""
        例如：
        - "当5日均线上穿20日均线时买入，跌破60日均线时卖出"
        - "RSI低于30时买入，高于70时卖出"
        - "MACD金叉且成交量放大时买入"
        """)

        # 显示聊天界面（上面的代码）
        # ...

        # 显示生成的代码（可编辑）
        if st.session_state.generated_code:
            st.subheader("📝 生成的策略代码")
            edited_code = st.text_area(
                "你可以直接编辑下方的代码（可选）",
                value=st.session_state.generated_code,
                height=300
            )

            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ 使用此策略回测"):
                    # 验证并保存代码
                    is_valid, msg = validate_strategy_code(edited_code)
                    if is_valid:
                        st.session_state.custom_strategy_code = edited_code
                        st.success("策略已保存，点击「运行回测」执行")
                    else:
                        st.error(f"代码验证失败: {msg}")
            with col2:
                if st.button("🔄 重新生成"):
                    st.session_state.generated_code = ""
                    st.rerun()

    if strategy_type == "自定义策略":
        st.subheader("✏️ 编辑策略代码")
        st.markdown(
            "请编写一个名为 `generate_signal` 的函数，接收 `df` 参数，返回包含 `signal` 和 `signal_type` 列的 DataFrame。")

        # 提供一个默认模板
        default_code = """def generate_signal(df):
        import pandas as pd
        import numpy as np
        data = df.copy()
        # 示例：简单的双均线金叉策略
        data['MA5'] = data['close'].rolling(5).mean()
        data['MA20'] = data['close'].rolling(20).mean()
        data['signal'] = (data['MA5'] > data['MA20']) & (data['MA5'].shift(1) <= data['MA20'].shift(1))
        data['signal_type'] = 'custom'
        # 注意：必须至少包含信号前一天的数据，建议保留所有行，只设置信号列
        return data
    """
        # 使用 st_ace 提供更好的编辑体验（若已安装）
        try:
            from streamlit_ace import st_ace

            user_code = st_ace(value=default_code, language='python', theme='monokai', keybinding='vscode',
                               font_size=14, height=400)
        except ImportError:
            user_code = st.text_area("策略代码", value=default_code, height=400)

    st.subheader("策略参数")
    if strategy_type == "右侧趋势策略":
        ma_short = st.slider("短期均线", 5, 20, 5)
        ma_mid = st.slider("中期均线", 10, 50, 20)
        ma_long = st.slider("长期均线", 30, 120, 60)
        vol_ratio = st.slider("放量倍数", 1.0, 3.0, 1.5, 0.1)
    elif strategy_type == "V型反转策略":
        lookback = st.slider("回看天数", 5, 20, 10)
        drop_threshold = st.slider("跌幅阈值", 0.10, 0.30, 0.15, 0.01)
        rebound_threshold = st.slider("反弹幅度", 0.01, 0.05, 0.01, 0.005)
        vol_ratio = st.slider("放量倍数", 1.0, 2.5, 1.3, 0.1)
    elif strategy_type == "🤖 AI 生成策略":
        # 检查 API Key 是否已设置
        if not st.session_state.get("deepseek_api_key"):
            st.warning("⚠️ 请先在左侧侧边栏设置 DeepSeek API Key")
            st.stop()  # 或跳过显示聊天界面
            # 不显示聊天输入框

        # 显示聊天界面...
        st.subheader("🤖 用自然语言描述策略")
        st.markdown("""
        **示例**：
        - "当5日均线上穿20日均线时买入"
        - "RSI低于30时买入，高于70时卖出"
        - "MACD金叉且成交量放大时买入"
        """)

        # --- 显示聊天历史 ---
        # 过滤掉 system 消息，只显示用户和助手
        for msg in st.session_state.deepseek_messages:
            if msg["role"] == "system":
                continue
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # --- 聊天输入框 ---
        if prompt := st.chat_input("描述你的交易策略..."):
            # 添加用户消息
            st.session_state.deepseek_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            # 调用 DeepSeek
            with st.chat_message("assistant"):
                with st.spinner("⏳ 正在生成策略代码..."):
                    # 构建 API 消息（不含 system，因为我们会单独传入）
                    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
                        m for m in st.session_state.deepseek_messages if m["role"] != "system"
                    ]
                    response = call_deepseek(api_messages)
                    if response.startswith("[ERROR]"):
                        st.error(response)
                    else:
                        st.code(response, language="python")
                        st.session_state.generated_code = response
                        st.session_state.deepseek_messages.append({"role": "assistant", "content": response})
                        # 自动提取代码并保存
                        code = extract_code(response)
                        is_valid, msg = validate_strategy_code(code)
                        if is_valid:
                            st.session_state.custom_strategy_code = code
                            st.success("✅ 策略代码已自动提取并保存，可点击「运行回测」执行。")
                        else:
                            st.warning(f"⚠️ 代码验证: {msg}，您可以手动编辑后使用。")

        # --- 显示当前生成的代码（可编辑） ---
        if st.session_state.generated_code:
            st.subheader("📝 生成的策略代码（可编辑）")
            edited_code = st.text_area(
                "你可以直接修改代码，然后点击下方按钮保存",
                value=st.session_state.generated_code,
                height=250,
                key="ai_edited_code"
            )
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("✅ 使用此策略回测", key="use_ai_code"):
                    # 验证并保存
                    code = extract_code(
                        edited_code) if edited_code != st.session_state.generated_code else st.session_state.generated_code
                    is_valid, msg = validate_strategy_code(code)
                    if is_valid:
                        st.session_state.custom_strategy_code = code
                        st.success("策略已保存，点击底部「运行回测」执行")
                    else:
                        st.error(f"代码验证失败: {msg}")
            with col_btn2:
                if st.button("🔄 重新生成", key="regenerate_ai"):
                    # 保留消息历史，但清空最后一条 assistant 回复，以便重新生成
                    if len(st.session_state.deepseek_messages) > 1 and st.session_state.deepseek_messages[-1][
                        "role"] == "assistant":
                        st.session_state.deepseek_messages.pop()
                        st.session_state.generated_code = ""
                        st.session_state.custom_strategy_code = ""
                        st.rerun()


    st.subheader("交易参数")
    initial_cash = st.number_input("初始资金", value=100000, step=10000)
    stop_loss = st.slider("止损比例", 0.05, 0.15, 0.08, 0.01)
    take_profit = st.slider("止盈比例", 0.10, 0.40, 0.20, 0.05)
    trailing_stop = st.slider("移动止损", 0.00, 0.10, 0.05, 0.01)
    position_pct = st.slider("单次建仓比例", 0.10, 0.99, 0.30, 0.05)

    run_btn = st.button("🚀 运行回测", type="primary")

# ---------- 主界面 ----------
if run_btn:
    with st.spinner("正在获取数据..."):
        df = fetch_stock_data(symbol, start_str, end_str)

    if df is None or df.empty:
        st.error("无法获取数据，请检查股票代码或网络")
        st.stop()

    with st.spinner("生成策略信号..."):
        if strategy_type == "🤖 AI 生成策略":
            # 使用 AI 生成的代码
            code = st.session_state.get("custom_strategy_code", "")
            if not code:
                st.error("请先生成或输入策略代码")
                st.stop()

            # 动态执行
            local_namespace = {}
            try:
                exec(code, {}, local_namespace)
                if 'generate_signal' not in local_namespace:
                    st.error("未找到 generate_signal 函数")
                    st.stop()
                generate_signal = local_namespace['generate_signal']
                df_signal = generate_signal(df)
                # 验证输出
                if 'signal' not in df_signal.columns or 'signal_type' not in df_signal.columns:
                    st.error("返回的 DataFrame 缺少 'signal' 或 'signal_type' 列")
                    st.stop()
                df_signal['signal'] = df_signal['signal'].astype(bool)
            except Exception as e:
                st.error(f"策略执行出错: {e}")
                st.stop()
        if strategy_type == "自定义策略":
            try:
                local_namespace = {}
                exec(user_code, {}, local_namespace)
                if 'generate_signal' not in local_namespace:
                    st.error("未找到名为 'generate_signal' 的函数。")
                    st.stop()
                generate_signal = local_namespace['generate_signal']
                df_signal = generate_signal(df)
                if not isinstance(df_signal, pd.DataFrame):
                    st.error("策略函数必须返回 DataFrame。")
                    st.stop()
                if 'signal' not in df_signal.columns or 'signal_type' not in df_signal.columns:
                    st.error("返回的 DataFrame 缺少 'signal' 或 'signal_type' 列。")
                    st.stop()
                df_signal['signal'] = df_signal['signal'].astype(bool)
            except Exception as e:
                st.error(f"策略代码执行出错: {e}")
                st.stop()
        else :
            if strategy_type == "右侧趋势策略":
                df_signal = generate_right_signal(df, ma_short, ma_mid, ma_long, vol_ratio)
            if strategy_type == "V型反转策略":
                df_signal = generate_v_shape_signal(df, lookback, drop_threshold, rebound_threshold, vol_ratio)

    with st.spinner("运行回测..."):
        max_hold = 20 if strategy_type == "V型反转策略" else 999
        trades, equity, metrics = run_backtest(
            df_signal,
            initial_cash=initial_cash,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trailing_stop=trailing_stop,
            position_pct=position_pct,
            max_hold_days=max_hold
        )

    if trades is None or 'error' in metrics:
        st.error(f"回测失败: {metrics.get('error', '未知错误')}")
        st.stop()

    st.success("回测完成！")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总收益率", f"{metrics['total_return']:.2f}%")
    col2.metric("年化收益率", f"{metrics['annual_return']:.2f}%")
    col3.metric("最大回撤", f"{metrics['max_drawdown']:.2f}%")
    col4.metric("夏普比率", f"{metrics['sharpe_ratio']:.3f}")

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("总交易次数", metrics['total_trades'])
    col6.metric("胜率", f"{metrics['win_rate']:.2f}%")
    col7.metric("盈亏比", f"{metrics['profit_loss_ratio']:.3f}")
    col8.metric("平均持仓(天)", f"{metrics['avg_hold_days']:.1f}")

    # 净值曲线
    st.plotly_chart(plot_equity(equity), use_container_width=True)
    st.markdown("<br>", unsafe_allow_html=True)  # 空行间隔

    # K线图与买卖点
    st.plotly_chart(plot_kline_with_signals(df_signal, trades), use_container_width=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # 最大回撤曲线
    st.plotly_chart(plot_drawdown(equity), use_container_width=True)

    with st.expander("📋 查看交易明细"):
        st.dataframe(trades, use_container_width=True)

    with st.expander("📊 详细绩效指标"):
        metrics_df = pd.DataFrame([metrics]).T.rename(columns={0: '数值'})
        st.dataframe(metrics_df, use_container_width=True)

else:
    st.info("👈 请在左侧设置参数后点击「运行回测」")
