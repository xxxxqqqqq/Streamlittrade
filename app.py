# ============================================================
# 0. 导入依赖
# ============================================================
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
from dotenv import load_dotenv

# 尝试导入增强代码编辑器（可选）
try:
    from streamlit_ace import st_ace  # type: ignore[import-unresolved]
    ACE_AVAILABLE = True
except ImportError:
    ACE_AVAILABLE = False

warnings.filterwarnings('ignore')

# ============================================================
# 1. 配置与常量
# ============================================================
load_dotenv()  # 加载 .env 文件（若有）

# DeepSeek API 密钥（将由用户在界面上输入，不写死在代码中）
# 此处仅声明变量，实际值从 st.session_state 获取
DEEPSEEK_API_KEY = ""

# DeepSeek 系统提示词（固定指令，用于引导 AI 生成标准策略代码）
SYSTEM_PROMPT = """你是一个量化交易策略代码生成助手。你的任务是根据用户的自然语言描述，生成符合以下规范的 Python 策略代码。

【输入数据说明】
函数接收一个参数 `df`，它是一个 Pandas DataFrame，至少包含以下列：
- open, high, low, close, volume（均为数值类型）
- 日期已作为索引（DatetimeIndex）

你可以基于这些列计算任意衍生指标，也可以利用这些数据模拟任何交易逻辑。

【代码规范】
1. 必须定义一个名为 `generate_signal` 的函数
2. 函数接收 `df` 作为唯一参数
3. 函数必须返回一个 DataFrame，且必须包含以下两列：
   - 'signal': 布尔类型，True 表示买入信号，False 表示无信号
   - 'signal_type': 字符串，固定为 'custom'
4. 可以在函数内部使用任何 Python 库（如 pandas, numpy, statsmodels, scipy 等），但需确保代码自包含（即所需的 import 语句写在函数内部或顶部）。
5. 代码应避免使用外部数据（除非用户明确要求，并说明如何获取），目前只基于 `df` 提供的数据。

【策略逻辑限制】
- 策略逻辑可以是任何类型：技术指标、统计套利、机器学习（需注意性能）、事件驱动、模式识别等。
- 不限制策略的复杂度，但需保证回测可执行（即信号生成不能依赖未来数据，不能使用未来的价格计算信号，否则回测无效）。

【输出要求 - 极其重要】
- 只输出 Python 纯代码，不要使用任何 Markdown 代码块标记（如 ```python 或 ```）
- 不要添加任何解释文字，代码必须可以直接复制并运行，无语法错误
- 代码必须从 `import` 或 `def generate_signal` 直接开始
- 将所有的import放在方法的内部

【示例】
用户说："当5日均线上穿20日均线时买入"
你应输出：
def generate_signal(df):
    import pandas as pd
    import numpy as np
    data = df.copy()
    data['MA5'] = data['close'].rolling(5).mean()
    data['MA20'] = data['close'].rolling(20).mean()
    data['signal'] = (data['MA5'] > data['MA20']) & (data['MA5'].shift(1) <= data['MA20'].shift(1))
    data['signal_type'] = 'custom'
    return data

--- 另一个示例（非技术指标）---
用户说："当成交量突然放大到过去20日均量的3倍以上时买入"
你应输出：
def generate_signal(df):
    import pandas as pd
    import numpy as np
    data = df.copy()
    data['vol_ma20'] = data['volume'].rolling(20).mean()
    data['signal'] = data['volume'] > data['vol_ma20'] * 3
    data['signal_type'] = 'custom'
    return data

现在，请根据用户的策略描述生成代码，严格遵守纯代码输出要求。"""


# ============================================================
# 2. DeepSeek API 工具函数
# ============================================================

def call_deepseek(messages, model="deepseek-chat", temperature=0.3, max_tokens=2000):
    """
    调用 DeepSeek API 生成策略代码
    使用 requests 直接调用，避免 openai 库的编码问题
    :param messages: 对话消息列表
    :param model: 模型名称
    :param temperature: 温度参数
    :param max_tokens: 最大输出 token 数
    :return: 生成的文本或错误信息
    """
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
    从 DeepSeek 返回的文本中提取纯 Python 代码
    支持去除 Markdown 代码块标记
    """
    # 匹配 ```python ... ``` 或 ``` ... ```
    pattern = r"```(?:python)?\s*\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        code = matches[0].strip()
        # 如果提取的代码中仍包含 def generate_signal，直接返回
        if "def generate_signal" in code:
            return code
        else:
            # 否则尝试从 def 开始截取
            if "def generate_signal" in text:
                start = text.find("def generate_signal")
                code = text[start:].strip()
                if code.endswith("```"):
                    code = code[:-3].strip()
                return code
    # 如果没有代码块标记，直接查找 def
    if "def generate_signal" in text:
        start = text.find("def generate_signal")
        code = text[start:].strip()
        if code.endswith("```"):
            code = code[:-3].strip()
        return code
    return text.strip()


def validate_strategy_code(code):
    """
    验证生成的代码是否符合基础规范
    检查语法和是否包含必要的函数
    :return: (is_valid, message)
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
# 3. 数据获取（基于 Baostock，带内存缓存）
# ============================================================
@st.cache_data(ttl=3600)
def fetch_stock_data(symbol, start_date, end_date, max_retries=2):
    """
    获取 A 股历史日线数据（前复权）
    仅使用 Streamlit 内存缓存，不保存到硬盘
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
# 4. 内置策略信号生成函数
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
    增强版右侧趋势策略
    条件：均线多头 + MACD零上金叉 + 放量突破 + 站上60日线 + (RSI强势 或 MACD红柱放大)
    返回包含 signal 和 signal_type 的 DataFrame
    """
    data = df.copy()
    data = data[~data.index.duplicated(keep='first')].sort_index()

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
    data['MACD_bar_shift'] = data['MACD_bar'].shift(1)

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

    # 条件
    cond1 = (data['MA5'] > data['MA20']) & (data['MA20'] > data['MA60'])   # 均线多头
    cond2 = (data['DIF'] > data['DEA']) & (data['DIF'] > 0)               # MACD零上金叉
    cond3 = data['volume'] > data['VOL_MA20'] * vol_ratio                 # 放量突破
    cond4 = data['close'] > data['MA60']                                  # 站上生命线
    cond5 = (data['K'] > data['D']) & (data['J'] > 20)                    # KDJ金叉
    cond6 = (data['RSI'] > rsi_lower) & (data['RSI'] < rsi_upper)         # RSI强势
    cond7 = data['MACD_bar'] > data['MACD_bar_shift']                     # MACD红柱放大

    core_signal = cond1 & cond2 & cond3 & cond4
    data['score'] = (cond1.astype(int) + cond2.astype(int) + cond3.astype(int) +
                     cond4.astype(int) + cond5.astype(int) + cond6.astype(int) + cond7.astype(int))
    data['signal'] = core_signal & (cond6 | cond7)
    data['signal_type'] = 'right'
    return data


def generate_v_shape_signal(df, lookback=10, drop_threshold=0.15,
                            rebound_threshold=0.01, vol_ratio=1.3, confirm_days=2):
    """
    V型反转策略：急跌 → 企稳 → 放量反弹
    返回带 signal 的 DataFrame
    """
    data = df.copy()
    data = data[~data.index.duplicated(keep='first')].sort_index()
    data['signal'] = False
    data['signal_type'] = 'v_shape'
    data['VOL_MA20'] = data['volume'].rolling(20).mean()

    # 存储触发参数供买入原因使用
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

        # 触发信号
        data.iloc[i, data.columns.get_loc('signal')] = True
        data.iloc[i, data.columns.get_loc('drop_used')] = max_drawdown
        data.iloc[i, data.columns.get_loc('rebound_used')] = rebound
        data.iloc[i, data.columns.get_loc('vol_ratio_used')] = vol_ratio_curr

    return data


# ============================================================
# 5. 回测引擎及相关辅助函数
# ============================================================
def get_entry_reason(row, signal_type):
    """
    根据信号类型和行数据生成买入原因描述
    """
    if signal_type == 'right':
        reasons = []
        if row.get('MA5', 0) > row.get('MA20', 0) and row.get('MA20', 0) > row.get('MA60', 0):
            reasons.append('均线多头')
        if row.get('DIF', 0) > row.get('DEA', 0) and row.get('DIF', 0) > 0:
            reasons.append('MACD金叉')
        if row.get('volume', 0) > row.get('VOL_MA20', 1) * 1.5:
            reasons.append('放量')
        if row.get('close', 0) > row.get('MA60', 0):
            reasons.append('站上60日线')
        if row.get('K', 0) > row.get('D', 0) and row.get('J', 0) > 20:
            reasons.append('KDJ金叉')
        if 'RSI' in row and 50 < row['RSI'] < 70:
            reasons.append('RSI强势')
        if 'MACD_bar' in row and 'MACD_bar_shift' in row and row['MACD_bar'] > row['MACD_bar_shift']:
            reasons.append('MACD放大')
        return ' | '.join(reasons) if reasons else '右侧信号'

    elif signal_type == 'v_shape':
        parts = []
        if not np.isnan(row.get('drop_used', np.nan)):
            parts.append(f"跌幅{row['drop_used']*100:.1f}%")
        if not np.isnan(row.get('rebound_used', np.nan)):
            parts.append(f"反弹{row['rebound_used']*100:.1f}%")
        if not np.isnan(row.get('vol_ratio_used', np.nan)):
            parts.append(f"量比{row['vol_ratio_used']:.2f}")
        return ' | '.join(parts) if parts else 'V型反转'

    elif signal_type == 'custom':
        return '自定义策略'

    else:
        return '未知信号'


def run_backtest(df, initial_cash=100000, commission=0.0003, slippage=0.001,
                 stop_loss=0.08, take_profit=0.20, trailing_stop=0.05,
                 use_atr_stop=False, atr_period=14, atr_multiple=2.0,
                 stamp_duty=0.0005, signal_confirm=1,
                 max_hold_days=20, position_pct=0.30):
    """
    核心回测引擎（专业版）
    - ATR 动态止损：基于波动率自适应调整止损位
    - 印花税：A股卖出单边征收（默认0.05%）
    - 信号确认：要求信号持续N天才触发买入，过滤假突破
    返回交易明细、每日权益序列和绩效指标
    """
    data = df.copy()
    data = data[data['signal'].notna()]
    if data.empty:
        return None, None, {'error': '无有效数据'}

    if 'MA20' not in data.columns:
        data['MA20'] = data['close'].rolling(20).mean()

    # ---- ATR 计算（用于动态止损）----
    if use_atr_stop:
        data['TR'] = np.maximum(
            data['high'] - data['low'],
            np.maximum(
                abs(data['high'] - data['close'].shift(1)),
                abs(data['low'] - data['close'].shift(1))
            )
        )
        data['ATR'] = data['TR'].rolling(atr_period).mean()

    # ---- 信号确认：连续N天出信号才算有效 ----
    if signal_confirm > 1:
        confirm_count = data['signal'].astype(int).rolling(signal_confirm).sum()
        data['signal_confirmed'] = (confirm_count >= signal_confirm) & data['signal']
    else:
        data['signal_confirmed'] = data['signal']

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
        sold_this_step = False

        # ---- 持仓卖出判断 ----
        if in_position:
            hold_days += 1
            highest_price = max(highest_price, current_high)
            should_sell = False
            sell_reason = ""

            if hold_days >= 2:  # T+1
                # ATR 动态止损（优先于固定比例移动止损）
                if use_atr_stop and not np.isnan(data.iloc[i].get('ATR', np.nan)):
                    atr_stop_price = highest_price - atr_multiple * data.iloc[i]['ATR']
                    if current_price <= atr_stop_price:
                        should_sell = True
                        sell_reason = f"ATR动态止损 ({atr_multiple:.1f}xATR)"
                elif current_price <= entry_price * (1 - stop_loss):
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
                fee = sell_price * position * (commission + stamp_duty)  # 含印花税
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

        # ---- 买入信号（使用确认后的信号）----
        if not in_position and not sold_this_step and data.iloc[i]['signal_confirmed']:
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
                    entry_reason = get_entry_reason(data.iloc[i], signal_type)
                    trades.append({
                        'date': current_date,
                        'action': 'BUY',
                        'price': round(buy_price, 3),
                        'size': size,
                        'signal_type': signal_type,
                        'entry_reason': entry_reason
                    })

        # ---- 记录每日权益 ----
        equity = cash + position * current_price if in_position else cash
        daily_equity.append(equity)

    # 期末强制平仓（含印花税）
    if in_position and position > 0:
        last_price = data.iloc[-1]['close'] * (1 - slippage)
        fee = last_price * position * (commission + stamp_duty)
        cash += last_price * position - fee
        profit = (last_price - entry_price) / entry_price
        trades.append({
            'date': data.index[-1],
            'action': 'SELL',
            'price': round(last_price, 3),
            'profit_pct': round(profit * 100, 2),
            'hold_days': hold_days,
            'reason': '期末平仓'
        })

    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    equity_series = pd.Series(daily_equity, index=data.index)
    metrics = calculate_metrics(daily_equity, trades)
    return trades_df, equity_series, metrics


def calculate_metrics(daily_equity, trades):
    """计算绩效指标"""
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

    # ---- 高级绩效指标 ----
    # Calmar 比率（年化收益 / 最大回撤绝对值）
    calmar = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0

    # 盈亏因子（总盈利 / 总亏损）
    total_win = sum([t['profit_pct'] for t in win_trades]) if win_trades else 0
    total_loss = abs(sum([t['profit_pct'] for t in loss_trades])) if loss_trades else 1
    profit_factor = total_win / total_loss if total_loss > 0 else 0

    # 最大连续亏损次数
    max_consecutive_loss = 0
    current_streak = 0
    for t in sell_trades:
        if t['profit_pct'] <= 0:
            current_streak += 1
            max_consecutive_loss = max(max_consecutive_loss, current_streak)
        else:
            current_streak = 0

    # Sortino 比率（使用下行标准差）
    downside_returns = returns[returns < 0]
    downside_std = downside_returns.std() if len(downside_returns) > 1 else 0
    sortino = (returns.mean() - risk_free) / downside_std * np.sqrt(250) if downside_std > 0 else 0

    return {
        'total_return': round(total_return, 2),
        'annual_return': round(annual_return, 2),
        'max_drawdown': round(max_drawdown, 2),
        'sharpe_ratio': round(sharpe, 3),
        'sortino_ratio': round(sortino, 3),
        'calmar_ratio': round(calmar, 3),
        'total_trades': total_trades,
        'win_trades': len(win_trades),
        'loss_trades': len(loss_trades),
        'win_rate': round(win_rate, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'profit_loss_ratio': round(profit_loss_ratio, 3),
        'profit_factor': round(profit_factor, 3),
        'max_consecutive_loss': max_consecutive_loss,
        'avg_hold_days': round(avg_hold_days, 1),
        'final_equity': round(equity_series.iloc[-1], 2)
    }


# ============================================================
# 6. 可视化函数
# ============================================================
def plot_equity(equity_series):
    """绘制净值曲线"""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=equity_series.index,
        y=equity_series,
        mode='lines',
        name='净值',
        line=dict(color='#1f77b4', width=2.5),
        line_shape='spline'
    ))
    fig.update_layout(title='净值曲线', height=400, margin=dict(l=40, r=40, t=40, b=40))
    fig.update_yaxes(title_text="净值")
    return fig


def plot_kline_with_signals(data, trades_df):
    """使用 Highcharts Stock 绘制 K 线图 — 雪球同款引擎（navigator + 十字光标 + 懒加载风格）"""
    import json

    # ---- 检测 Streamlit 主题 ----
    try:
        theme = st.config.get_option('theme.base')
    except Exception:
        theme = 'light'
    is_dark = (theme == 'dark')

    RED = '#cf2a2a'
    GREEN = '#009975'
    if is_dark:
        BG = '#0d1117'
        TEXT = '#c9d1d9'
        GRID = '#1a2535'
        CROSSHAIR = '#30363d'
        NAV_COLOR = '#444'
        NAV_FILL = 'rgba(255,255,255,0.05)'
    else:
        BG = '#ffffff'
        TEXT = '#333333'
        GRID = '#e8e8e8'
        CROSSHAIR = '#d0d0d0'
        NAV_COLOR = '#999'
        NAV_FILL = 'rgba(0,0,0,0.03)'

    # ---- 转换 K 线 + 成交量数据 ----
    ohlc = []
    volumes = []
    for idx, row in data.iterrows():
        ts = int(idx.timestamp() * 1000)
        o = round(float(row['open']), 2)
        h = round(float(row['high']), 2)
        l = round(float(row['low']), 2)
        c = round(float(row['close']), 2)
        v = int(row['volume'])
        is_up = c >= o
        ohlc.append([ts, o, h, l, c])
        volumes.append({'x': ts, 'y': v, 'color': RED if is_up else GREEN,
                        'up': is_up})

    # ---- 买卖标记（flags 系列） ----
    buys = []
    sells = []
    if trades_df is not None and not trades_df.empty:
        for _, row in trades_df.iterrows():
            ts = int(row['date'].timestamp() * 1000)
            if row['action'] == 'BUY':
                reason = row.get('entry_reason', '')
                buys.append({
                    'x': ts,
                    'title': '多',
                    'text': f"买入 {row['price']:.2f}" + (f" ({reason})" if reason else "")
                })
            else:
                profit = row.get('profit_pct', None)
                reason = row.get('reason', '')
                txt = f"卖出 {row['price']:.2f}"
                if profit is not None:
                    txt += f" | {profit:+.2f}%"
                if reason:
                    txt += f" | {reason}"
                sells.append({'x': ts, 'title': '空', 'text': txt})

    # ---- 构建 Highcharts Stock HTML ----
    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.bootcdn.net/ajax/libs/highcharts/11.4.0/highstock.js">
</script>
<style>
*{{margin:0;padding:0}}
html,body{{width:100%;height:100%;background:transparent;overflow:hidden}}
#hc{{width:100%;height:100%}}
</style></head>
<body><div id="hc"></div>
<script>
(function(){{
var ohlc={json.dumps(ohlc)};
var volumes={json.dumps(volumes)};
var buys={json.dumps(buys)};
var sells={json.dumps(sells)};
var RED="{RED}",GREEN="{GREEN}",TEXT="{TEXT}",GRID="{GRID}",
    CROSS="{CROSSHAIR}",BG="{BG}",NAVC="{NAV_COLOR}",NAVF="{NAV_FILL}";

Highcharts.stockChart('hc',{{
  chart:{{
    backgroundColor:'transparent',spacing:[5,5,10,5],
    panning:true,zoomType:'x',marginRight:10
  }},
  title:{{text:'K线图与买卖点',align:'left',x:0,
    style:{{color:'#ffffff',fontSize:'16px',fontWeight:'bold'}}}},

  // ======= 范围选择器（切时间） =======
  rangeSelector:{{
    buttons:[
      {{type:'month',count:1,text:'1月'}},
      {{type:'month',count:3,text:'3月'}},
      {{type:'month',count:6,text:'半年'}},
      {{type:'year', count:1,text:'1年'}},
      {{type:'all',text:'全部'}}
    ],
    selected:4,inputEnabled:false,
    buttonTheme:{{style:{{color:TEXT}}}}
  }},

  // ======= Navigator 迷你全景图 + 拖拽滑块（雪球标志） =======
  navigator:{{
    enabled:true,height:42,maskFill:'rgba(128,128,128,0.2)',
    series:{{type:'area',color:NAVC,fillColor:NAVF,lineWidth:1}},
    xAxis:{{labels:{{style:{{color:TEXT}}}},gridLineColor:GRID}},
    handles:{{backgroundColor:'#666',borderColor:'#999'}}
  }},
  scrollbar:{{enabled:false}},

  // ======= 十字光标 =======
  tooltip:{{split:true,shared:true,
    backgroundColor:BG,borderColor:CROSS,
    style:{{color:TEXT,fontSize:'12px'}}
  }},
  crosshair:{{color:CROSS,dashStyle:'dot'}},

  // ======= 禁止悬停变暗 =======
  plotOptions:{{
    series:{{states:{{inactive:{{opacity:1}}}}}},
    candlestick:{{states:{{hover:{{brightness:0}}}}}},
    column:{{states:{{hover:{{brightness:0}}}}}}
  }},

  // ======= 图例在下方 =======
  legend:{{
    align:'left',verticalAlign:'bottom',y:-5,
    itemStyle:{{color:TEXT}},itemHoverStyle:{{color:TEXT}},
    backgroundColor:'transparent'
  }},

  // ======= Y 轴：价格左侧 / 成交量右侧（错开布局，防止重叠）=======
  yAxis:[{{
    labels:{{enabled:true,align:'left',x:0,
      style:{{color:'#ffffff',fontSize:'14px'}}}},
    gridLineColor:GRID,gridLineWidth:0.5,
    opposite:false,lineColor:GRID,tickColor:TEXT,
    tickLength:5,tickWidth:1,tickAmount:7,
    showFirstLabel:true,showLastLabel:true,
    height:'66%',
    resize:{{enabled:true}}
  }},{{
    labels:{{enabled:false}},gridLineWidth:0,
    opposite:true,top:'70%',height:'30%',
    lineWidth:0,tickWidth:0,offset:0
  }}],

  // ======= X 轴 =======
  xAxis:{{
    labels:{{style:{{color:'#ffffff',fontSize:'14px'}}}},
    gridLineColor:GRID,lineColor:GRID,tickColor:GRID
  }},

  // ======= 数据系列 =======
  series:[{{
    id:'kline',type:'candlestick',name:'K线',data:ohlc,
    upColor:RED,color:GREEN,upLineColor:RED,lineColor:GREEN,
    tooltip:{{valueDecimals:2}},
    dataGrouping:{{enabled:true,forced:true,units:[
      ['day',[1]],['week',[1]],['month',[1]],['year',[1]]
    ]}}
  }},{{
    type:'column',name:'成交量',data:volumes,yAxis:1,
    turboThreshold:0,dataGrouping:{{enabled:true,forced:true}},
    tooltip:{{pointFormat:'成交量: <b>{{point.y:,.0f}}</b> 手'}}
  }},{{
    type:'flags',name:'买入',data:buys,onSeries:'kline',
    color:RED,fillColor:'rgba(0,0,0,0)',shape:'squarepin',
    style:{{color:RED,fontSize:'10px',fontWeight:'bold'}},
    tooltip:{{pointFormat:'{{point.text}}'}}
  }},{{
    type:'flags',name:'卖出',data:sells,onSeries:'kline',
    color:GREEN,fillColor:'rgba(0,0,0,0)',shape:'squarepin',
    style:{{color:GREEN,fontSize:'10px',fontWeight:'bold'}},
    tooltip:{{pointFormat:'{{point.text}}'}}
  }}]
}});
}})();
</script></body></html>'''

    st.components.v1.html(html, height=600, scrolling=False)


def plot_drawdown(equity_series):
    """绘制最大回撤曲线"""
    cum_max = equity_series.expanding().max()
    drawdown = (equity_series - cum_max) / cum_max * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=drawdown.index, y=drawdown,
        mode='lines', name='回撤 (%)',
        fill='tozeroy', line=dict(color='red')
    ))
    fig.update_layout(title='最大回撤曲线', height=300)
    fig.update_yaxes(title_text="回撤 (%)")
    return fig


# ============================================================
# 7. Streamlit 界面 — 多页面导航
# ============================================================
st.set_page_config(page_title="量化回测系统", layout="wide")

# ---- 初始化 session state ----
if "deepseek_api_key" not in st.session_state:
    st.session_state.deepseek_api_key = ""
if "deepseek_messages" not in st.session_state:
    st.session_state.deepseek_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
if "generated_code" not in st.session_state:
    st.session_state.generated_code = ""
if "custom_strategy_code" not in st.session_state:
    st.session_state.custom_strategy_code = ""
if "active_strategy_name" not in st.session_state:
    st.session_state.active_strategy_name = "内置-右侧趋势"


# ============================================================
# Page 1: 📊 策略回测中心
# ============================================================
def backtest_page():
    st.title("📈 量化策略回测系统")

    DEFAULT_CUSTOM_CODE = """def generate_signal(df):
    import pandas as pd
    import numpy as np
    data = df.copy()
    # 示例：双均线金叉策略
    data['MA5'] = data['close'].rolling(5).mean()
    data['MA20'] = data['close'].rolling(20).mean()
    data['signal'] = (data['MA5'] > data['MA20']) & (data['MA5'].shift(1) <= data['MA20'].shift(1))
    data['signal_type'] = 'custom'
    return data
"""

    # ---- 侧边栏：极简交易控制台 ----
    with st.sidebar:
        st.header("📊 交易控制台")

        symbol = st.text_input("股票代码", value="600160", placeholder="如 600160")

        col_s, col_e = st.columns(2)
        with col_s:
            start_date = st.date_input("开始日期", value=datetime(2020, 1, 1))
        with col_e:
            end_date = st.date_input("结束日期", value=datetime.now())
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        initial_cash = st.number_input("💰 初始资金", value=100000, step=10000, format="%d")

        st.markdown("---")

        # 当前策略指示器
        strategy_label = st.session_state.active_strategy_name
        st.caption(f"📌 当前策略：**{strategy_label}**")

        run_btn = st.button("🚀 运行回测", type="primary", use_container_width=True)

        st.markdown("---")

        # API Key（折叠）
        with st.expander("🔑 DeepSeek API Key"):
            if not st.session_state.deepseek_api_key:
                api_key_input = st.text_input(
                    "API Key", type="password", placeholder="sk-...",
                    label_visibility="collapsed", key="sidebar_api_key"
                )
                if st.button("保存 Key", key="save_api_key_sidebar"):
                    if api_key_input.startswith("sk-"):
                        st.session_state.deepseek_api_key = api_key_input
                        st.success("✅ 已保存")
                        st.rerun()
                    else:
                        st.error("请输入有效的 API Key（以 sk- 开头）")
            else:
                st.success("✅ API Key 已配置")
                if st.button("🗑️ 重置 Key", key="reset_api_key_sidebar"):
                    st.session_state.deepseek_api_key = ""
                    st.rerun()

    # ================================================================
    # 主区域 — 紧凑策略栏
    # ================================================================
    strategy_type = st.radio(
        "策略来源",
        ["📈 内置", "✏️ 自定义", "🤖 AI"],
        horizontal=True,
        key="backtest_strategy_type",
        help="内置=预设策略 | 自定义=手动编码 | AI=DeepSeek生成"
    )

    # ---- 策略参数默认值 ----
    user_code = ""
    ma_short, ma_mid, ma_long = 5, 20, 60
    vol_ratio = 1.5
    lookback, drop_threshold, rebound_threshold = 10, 0.15, 0.01
    v_vol_ratio = 1.3
    builtin_sub = "📈 右侧趋势"

    # ---- 内置策略 ----
    if strategy_type == "📈 内置":
        builtin_sub = st.radio(
            "子策略", ["📈 右侧趋势", "🔍 V型反转"],
            horizontal=True, key="builtin_sub_radio"
        )
        if builtin_sub == "📈 右侧趋势":
            p1, p2, p3, p4 = st.columns(4)
            with p1:
                ma_short = st.slider("短期均线", 5, 20, 5, key="ma_short")
            with p2:
                ma_mid = st.slider("中期均线", 10, 50, 20, key="ma_mid")
            with p3:
                ma_long = st.slider("长期均线", 30, 120, 60, key="ma_long")
            with p4:
                vol_ratio = st.slider("放量倍数", 1.0, 3.0, 1.5, 0.1, key="r_vol_ratio")
        else:
            p1, p2, p3, p4 = st.columns(4)
            with p1:
                lookback = st.slider("回看天数", 5, 20, 10, key="v_lookback")
            with p2:
                drop_threshold = st.slider("跌幅阈值", 0.10, 0.30, 0.15, 0.01, key="v_drop")
            with p3:
                rebound_threshold = st.slider("反弹幅度", 0.01, 0.05, 0.01, 0.005, key="v_rebound")
            with p4:
                v_vol_ratio = st.slider("放量倍数", 1.0, 2.5, 1.3, 0.1, key="v_vol_ratio2")

    # ---- 自定义策略 ----
    elif strategy_type == "✏️ 自定义":
        existing_code = st.session_state.get("custom_strategy_code", "")
        user_code = st.text_area(
            "策略代码（在「策略工坊」页面编写）",
            value=existing_code if existing_code else DEFAULT_CUSTOM_CODE,
            height=200, key="backtest_custom_code"
        )

    # ---- AI 策略 ----
    elif strategy_type == "🤖 AI":
        code = st.session_state.get("custom_strategy_code", "")
        if code:
            st.success("✅ 已加载 AI 生成策略 — 在「策略工坊」页面可修改")
            with st.expander("📝 查看策略代码"):
                st.code(code, language="python")
        else:
            st.warning("⚠️ 尚未生成 AI 策略，请切换到「🤖 策略工坊」页面创建")

    # ---- 高级交易参数（折叠）----
    with st.expander("📐 高级交易参数", expanded=False):
        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            stop_loss = st.slider("硬止损比例", 0.03, 0.20, 0.08, 0.01,
                                  help="亏损超此比例立即止损")
            take_profit = st.slider("目标止盈比例", 0.10, 0.50, 0.20, 0.05,
                                    help="盈利达此比例自动止盈")
            position_pct = st.slider("单次建仓比例", 0.10, 0.99, 0.30, 0.05,
                                     help="每次买入占总资金比例")
        with col_t2:
            trailing_stop = st.slider("移动止损回撤", 0.00, 0.15, 0.05, 0.01,
                                      help="从最高点回撤此比例退出（0=关闭）")
            use_atr_stop = st.checkbox("启用 ATR 动态止损", value=False,
                                       help="基于波动率自适应止损")
            atr_multiple = 2.0
            if use_atr_stop:
                atr_multiple = st.slider("ATR 止损倍数", 1.0, 4.0, 2.0, 0.5,
                                         help="止损价=最高价 - N×ATR，常用2~3倍")
        with col_t3:
            signal_confirm = st.slider("信号确认天数", 1, 5, 1,
                                       help="信号持续N天才买入，过滤假突破")
            slippage = st.number_input("滑点比例", value=0.001, format="%.4f")
            stamp_duty = st.number_input("印花税率（卖出）", value=0.0005, format="%.4f",
                                         help="A股卖出单边0.05%，买入免征")

    st.markdown("---")

    # ================================================================
    # 回测结果看板
    # ================================================================
    if run_btn:
        # ---- 获取数据 ----
        with st.spinner("正在获取数据..."):
            df = fetch_stock_data(symbol, start_str, end_str)
        if df is None or df.empty:
            st.error("无法获取数据，请检查股票代码或网络")
            st.stop()

        # ---- 生成信号 ----
        with st.spinner("生成策略信号..."):
            if strategy_type == "📈 内置":
                if builtin_sub == "📈 右侧趋势":
                    df_signal = generate_right_signal(df, ma_short, ma_mid, ma_long, vol_ratio)
                else:
                    df_signal = generate_v_shape_signal(df, lookback, drop_threshold, rebound_threshold, v_vol_ratio)
                st.session_state.active_strategy_name = builtin_sub

            elif strategy_type == "✏️ 自定义":
                code = user_code if user_code else st.session_state.get("custom_strategy_code", "")
                if not code:
                    st.error("请先编写策略代码")
                    st.stop()
                try:
                    local_namespace = {}
                    exec(code, {}, local_namespace)
                    if 'generate_signal' not in local_namespace:
                        st.error("未找到 generate_signal 函数")
                        st.stop()
                    generate_signal = local_namespace['generate_signal']
                    df_signal = generate_signal(df)
                    if not isinstance(df_signal, pd.DataFrame):
                        st.error("策略函数必须返回 DataFrame")
                        st.stop()
                    if 'signal' not in df_signal.columns or 'signal_type' not in df_signal.columns:
                        st.error("返回值缺少 signal 或 signal_type 列")
                        st.stop()
                    df_signal['signal'] = df_signal['signal'].astype(bool)
                except Exception as e:
                    st.error(f"策略执行出错: {e}")
                    st.stop()
                st.session_state.active_strategy_name = "自定义策略"

            elif strategy_type == "🤖 AI":
                code = st.session_state.get("custom_strategy_code", "")
                if not code:
                    st.error("请先在「策略工坊」页面生成 AI 策略代码")
                    st.stop()
                try:
                    local_namespace = {}
                    exec(code, {}, local_namespace)
                    if 'generate_signal' not in local_namespace:
                        st.error("未找到 generate_signal 函数")
                        st.stop()
                    generate_signal = local_namespace['generate_signal']
                    df_signal = generate_signal(df)
                    if 'signal' not in df_signal.columns or 'signal_type' not in df_signal.columns:
                        st.error("返回值缺少 signal 或 signal_type 列")
                        st.stop()
                    df_signal['signal'] = df_signal['signal'].astype(bool)
                except Exception as e:
                    st.error(f"策略执行出错: {e}")
                    st.stop()
                st.session_state.active_strategy_name = "AI生成策略"
            else:
                st.error("未知策略类型")
                st.stop()

        # ---- 运行回测 ----
        with st.spinner("运行回测..."):
            max_hold = 20 if (strategy_type == "📈 内置" and builtin_sub == "🔍 V型反转") else 999
            trades, equity, metrics = run_backtest(
                df_signal,
                initial_cash=initial_cash,
                stop_loss=stop_loss,
                take_profit=take_profit,
                trailing_stop=trailing_stop,
                use_atr_stop=use_atr_stop,
                atr_multiple=atr_multiple,
                stamp_duty=stamp_duty,
                signal_confirm=signal_confirm,
                slippage=slippage,
                position_pct=position_pct,
                max_hold_days=max_hold
            )

        if trades is None or 'error' in metrics:
            st.error(f"回测失败: {metrics.get('error', '未知错误')}")
            st.stop()

        st.success("回测完成！")

        # ---- 核心指标行 1 ----
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("📈 总收益率", f"{metrics['total_return']:.2f}%")
        c2.metric("📅 年化收益", f"{metrics['annual_return']:.2f}%")
        c3.metric("📉 最大回撤", f"{metrics['max_drawdown']:.2f}%")
        c4.metric("📊 夏普比率", f"{metrics['sharpe_ratio']:.3f}")
        c5.metric("🎯 胜率", f"{metrics['win_rate']:.2f}%")

        # ---- 高级指标行 2 ----
        c6, c7, c8, c9, c10 = st.columns(5)
        c6.metric("🛡️ Calmar", f"{metrics['calmar_ratio']:.3f}",
                  help="年化收益÷最大回撤，越高越好")
        c7.metric("📐 Sortino", f"{metrics['sortino_ratio']:.3f}",
                  help="仅惩罚下行波动的夏普改进版")
        c8.metric("💰 盈亏因子", f"{metrics['profit_factor']:.3f}",
                  help="总盈利÷总亏损，>1.5为优秀")
        c9.metric("🔄 交易次数", metrics['total_trades'])
        c10.metric("📋 盈亏比", f"{metrics['profit_loss_ratio']:.3f}")

        # ---- 补充指标行 3 ----
        ca, cb, cc = st.columns(3)
        ca.metric("📊 最大连亏(次)", metrics['max_consecutive_loss'])
        cb.metric("⏱️ 平均持仓(天)", f"{metrics['avg_hold_days']:.1f}")
        cc.metric("💵 最终权益", f"{metrics['final_equity']:,.0f}")

        # ---- 图表 ----
        st.markdown("---")
        st.plotly_chart(plot_equity(equity), use_container_width=True)
        plot_kline_with_signals(df_signal, trades)
        st.plotly_chart(plot_drawdown(equity), use_container_width=True)

        # ---- 明细 & 导出 ----
        cd1, cd2 = st.columns(2)
        with cd1:
            with st.expander("📋 交易明细"):
                st.dataframe(trades, use_container_width=True)
        with cd2:
            with st.expander("📊 完整绩效指标"):
                st.dataframe(
                    pd.DataFrame([metrics]).T.rename(columns={0: '数值'}),
                    use_container_width=True
                )

        st.markdown("---")
        ce1, ce2 = st.columns(2)
        with ce1:
            csv_t = trades.to_csv(index=False) if not trades.empty else ""
            st.download_button(
                "📥 导出交易明细 CSV", data=csv_t,
                file_name=f"trades_{symbol}_{start_str}_{end_str}.csv",
                mime="text/csv", disabled=trades.empty, use_container_width=True
            )
        with ce2:
            st.download_button(
                "📥 导出绩效指标 CSV",
                data=pd.DataFrame([metrics]).to_csv(index=False),
                file_name=f"metrics_{symbol}_{start_str}_{end_str}.csv",
                mime="text/csv", use_container_width=True
            )

    else:
        # ---- 空状态引导 ----
        st.info("👈 在左侧配置股票与资金，选择策略后点击「运行回测」")

        col_w1, col_w2, col_w3 = st.columns(3)
        with col_w1:
            st.markdown("""
            ### 📈 内置策略
            - **右侧趋势**：均线多头 + MACD金叉 + 放量突破
            - **V型反转**：急跌企稳 + 放量反弹捕捉
            """)
        with col_w2:
            st.markdown("""
            ### ✏️ 自定义策略
            - 编写 `generate_signal(df)` 函数
            - 支持任意 Python 库
            - 实时验证与回测
            """)
        with col_w3:
            st.markdown("""
            ### 🤖 AI 策略
            - 自然语言描述交易逻辑
            - DeepSeek 自动生成代码
            - 在「策略工坊」页面使用
            """)


# ============================================================
# Page 2: 🤖 策略工坊（AI 生成 + 手动编辑器 + 模板库）
# ============================================================
def workshop_page():
    st.title("🤖 策略工坊")
    st.markdown("使用 AI 对话生成策略，或手动编写——生成的策略可在「策略回测」页面直接使用")

    if not st.session_state.get("deepseek_api_key"):
        st.warning("⚠️ 请先在「策略回测」页面侧边栏底部设置 DeepSeek API Key")
        return

    tab_ai, tab_manual = st.tabs(["🤖 AI 对话生成", "💻 手动代码编辑器"])

    # ================================================================
    # Tab 1: AI 对话生成
    # ================================================================
    with tab_ai:
        # 显示聊天历史
        for msg in st.session_state.deepseek_messages:
            if msg["role"] == "system":
                continue
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        # 聊天输入
        if prompt := st.chat_input("用自然语言描述你的交易策略..."):
            st.session_state.deepseek_messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("⏳ DeepSeek 正在生成策略代码..."):
                    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
                        m for m in st.session_state.deepseek_messages if m["role"] != "system"
                    ]
                    response = call_deepseek(api_messages)
                    if response.startswith("[ERROR]"):
                        st.error(response)
                    else:
                        st.code(response, language="python")
                        st.session_state.generated_code = response
                        st.session_state.deepseek_messages.append(
                            {"role": "assistant", "content": response}
                        )
                        code = extract_code(response)
                        is_valid, msg = validate_strategy_code(code)
                        if is_valid:
                            st.session_state.custom_strategy_code = code
                            st.session_state.active_strategy_name = "AI生成策略"
                            st.success("✅ 策略已自动保存！切换到「策略回测」页面，选择 🤖 AI 即可回测")
                        else:
                            st.warning(f"⚠️ 代码需手动调整: {msg}")

        # 代码编辑区（生成后显示）
        if st.session_state.generated_code:
            st.markdown("---")
            st.subheader("📝 代码微调")
            edited_code = st.text_area(
                "编辑后点击保存", value=st.session_state.generated_code,
                height=250, key="ai_edited_code"
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("💾 保存修改", key="save_ai_code", use_container_width=True):
                    code = extract_code(edited_code)
                    is_valid, msg = validate_strategy_code(code)
                    if is_valid:
                        st.session_state.custom_strategy_code = code
                        st.session_state.generated_code = edited_code
                        st.session_state.active_strategy_name = "AI生成策略"
                        st.success("已保存！去「策略回测」页面使用")
                    else:
                        st.error(f"验证失败: {msg}")
            with c2:
                if st.button("🔄 重新生成", key="regenerate_ai", use_container_width=True):
                    if len(st.session_state.deepseek_messages) > 1 and \
                       st.session_state.deepseek_messages[-1]["role"] == "assistant":
                        st.session_state.deepseek_messages.pop()
                        st.session_state.generated_code = ""
                        st.session_state.custom_strategy_code = ""
                        st.rerun()
            with c3:
                if st.button("🗑️ 清空对话", key="clear_chat", use_container_width=True):
                    st.session_state.deepseek_messages = [
                        {"role": "system", "content": SYSTEM_PROMPT}
                    ]
                    st.session_state.generated_code = ""
                    st.rerun()

    # ================================================================
    # Tab 2: 手动代码编辑器
    # ================================================================
    with tab_manual:
        st.markdown("### 💻 手动编写策略")
        st.markdown("定义 `generate_signal(df)` 函数，`df` 为包含 open/high/low/close/volume 的 DataFrame")

        default_code = """def generate_signal(df):
    import pandas as pd
    import numpy as np
    data = df.copy()
    # ==== 在此编写你的策略逻辑 ====
    data['MA5'] = data['close'].rolling(5).mean()
    data['MA20'] = data['close'].rolling(20).mean()
    data['signal'] = (data['MA5'] > data['MA20']) & (data['MA5'].shift(1) <= data['MA20'].shift(1))
    data['signal_type'] = 'custom'
    return data
"""
        manual_code = st.text_area(
            "策略代码",
            value=default_code,
            height=350,
            key="manual_code_editor"
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("💾 保存并设为当前策略", type="primary", key="save_manual", use_container_width=True):
                is_valid, msg = validate_strategy_code(manual_code)
                if is_valid:
                    st.session_state.custom_strategy_code = manual_code
                    st.session_state.active_strategy_name = "手动编写策略"
                    st.success("✅ 已保存！切换到「策略回测」页面，选择 ✏️ 自定义即可")
                else:
                    st.error(f"验证失败: {msg}")
        with c2:
            if st.button("🧪 语法检查", key="test_manual", use_container_width=True):
                is_valid, msg = validate_strategy_code(manual_code)
                if is_valid:
                    st.success("✅ 语法正确，generate_signal 函数定义完整")
                else:
                    st.error(f"❌ {msg}")

        # ---- 策略模板库 ----
        with st.expander("📚 策略模板库（点击加载）"):
            templates = {
                "双均线金叉": """def generate_signal(df):
    import pandas as pd
    data = df.copy()
    data['MA5'] = data['close'].rolling(5).mean()
    data['MA20'] = data['close'].rolling(20).mean()
    data['signal'] = (data['MA5'] > data['MA20']) & (data['MA5'].shift(1) <= data['MA20'].shift(1))
    data['signal_type'] = 'custom'
    return data""",
                "MACD金叉": """def generate_signal(df):
    import pandas as pd
    data = df.copy()
    e1 = data['close'].ewm(span=12, adjust=False).mean()
    e2 = data['close'].ewm(span=26, adjust=False).mean()
    data['DIF'] = e1 - e2
    data['DEA'] = data['DIF'].ewm(span=9, adjust=False).mean()
    data['MACD'] = (data['DIF'] - data['DEA']) * 2
    data['signal'] = (data['DIF'] > data['DEA']) & (data['DIF'].shift(1) <= data['DEA'].shift(1))
    data['signal_type'] = 'custom'
    return data""",
                "RSI超卖反弹": """def generate_signal(df):
    import pandas as pd
    import numpy as np
    data = df.copy()
    delta = data['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    data['RSI'] = 100 - (100 / (1 + gain / loss))
    data['signal'] = (data['RSI'] < 30) & (data['RSI'].shift(1) >= 30)
    data['signal_type'] = 'custom'
    return data""",
                "布林带突破": """def generate_signal(df):
    import pandas as pd
    import numpy as np
    data = df.copy()
    data['MA20'] = data['close'].rolling(20).mean()
    data['STD'] = data['close'].rolling(20).std()
    data['Upper'] = data['MA20'] + 2 * data['STD']
    data['signal'] = (data['close'] > data['Upper']) & (data['volume'] > data['volume'].rolling(20).mean() * 1.5)
    data['signal_type'] = 'custom'
    return data""",
                "放量突破": """def generate_signal(df):
    import pandas as pd
    data = df.copy()
    data['VOL_MA20'] = data['volume'].rolling(20).mean()
    data['RET'] = data['close'].pct_change()
    data['signal'] = (data['volume'] > data['VOL_MA20'] * 2) & (data['RET'] > 0.02)
    data['signal_type'] = 'custom'
    return data""",
            }

            tmpl_names = list(templates.keys())
            cols_per_row = 3
            for row_start in range(0, len(tmpl_names), cols_per_row):
                row_names = tmpl_names[row_start:row_start + cols_per_row]
                cols = st.columns(len(row_names))
                for i, name in enumerate(row_names):
                    with cols[i]:
                        if st.button(f"📋 {name}", key=f"tmpl_{row_start + i}", use_container_width=True):
                            st.session_state.generated_code = templates[name]
                            st.session_state.custom_strategy_code = templates[name]
                            st.session_state.active_strategy_name = name
                            st.success(f"✅ 已加载「{name}」模板")
                            st.rerun()


# ---- 顶部导航栏 ----
if "_current_page" not in st.session_state:
    st.session_state["_current_page"] = "backtest"

nav_col1, nav_col2 = st.columns(2)
with nav_col1:
    btn_type_bt = "primary" if st.session_state["_current_page"] == "backtest" else "secondary"
    if st.button("📊 策略回测", use_container_width=True, type=btn_type_bt, key="nav_btn_backtest"):
        st.session_state["_current_page"] = "backtest"
        st.rerun()
with nav_col2:
    btn_type_ws = "primary" if st.session_state["_current_page"] == "workshop" else "secondary"
    if st.button("🤖 策略工坊", use_container_width=True, type=btn_type_ws, key="nav_btn_workshop"):
        st.session_state["_current_page"] = "workshop"
        st.rerun()

st.markdown("---")

if st.session_state["_current_page"] == "backtest":
    backtest_page()
else:
    workshop_page()