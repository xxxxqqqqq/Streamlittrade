"""
模块：实盘信号 (live_signal.py)
功能：定时扫描信号、信号推送（控制台/文件）、模拟交易日志
依赖：pandas, numpy, datetime, json, time
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
import time
from typing import Dict, List, Optional, Callable


# ============================================================
# 信号扫描
# ============================================================

def scan_signals(symbols: List[str],
                 fetch_data_func: Callable,
                 strategy_func: Callable,
                 end_date: Optional[str] = None,
                 **strategy_kwargs) -> pd.DataFrame:
    """
    扫描多只股票，返回当前买入信号

    Args:
        symbols:          股票代码列表
        fetch_data_func:  数据获取函数
        strategy_func:    策略函数
        end_date:         截止日期，默认今天
        **strategy_kwargs: 策略参数

    Returns:
        pd.DataFrame: 信号汇总表
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')

    # 往前取 120 天数据用于计算指标
    start_date = (datetime.now() - timedelta(days=180)).strftime('%Y%m%d')

    signals = []

    for symbol in symbols:
        try:
            df = fetch_data_func(symbol, start_date, end_date)
            if df is None or df.empty or len(df) < 50:
                signals.append({
                    '股票': symbol,
                    '信号': '数据不足',
                    '最新价': None,
                    '置信度': None
                })
                continue

            # 生成信号
            df_signal = strategy_func(df, **strategy_kwargs)

            # 取最近一天
            latest = df_signal.iloc[-1]
            has_signal = latest.get('signal', False)

            # 计算置信度（基于连续信号天数）
            confidence = _calc_confidence(df_signal)

            signals.append({
                '股票': symbol,
                '信号': '🟢 买入' if has_signal else '⚪ 观望',
                '最新价': round(float(latest['close']), 2),
                '置信度': confidence,
                '时间': datetime.now().strftime('%Y-%m-%d %H:%M'),
                '涨跌幅%': round(float(latest.get('ret_1d', latest.get('close', 0) / df_signal.iloc[-2]['close'] - 1)) * 100, 2) if len(df_signal) > 1 else None
            })

        except Exception as e:
            signals.append({
                '股票': symbol,
                '信号': f'错误: {str(e)[:30]}',
                '最新价': None,
                '置信度': None
            })

    return pd.DataFrame(signals)


def _calc_confidence(df_signal: pd.DataFrame, lookback: int = 5) -> str:
    """根据最近 N 天信号密度计算置信度"""
    if 'signal' not in df_signal.columns or len(df_signal) < lookback:
        return '未知'

    recent = df_signal['signal'].iloc[-lookback:].astype(bool)
    true_count = recent.sum()

    if true_count >= 4:
        return '⭐⭐⭐ 高'
    elif true_count >= 2:
        return '⭐⭐ 中'
    elif true_count >= 1:
        return '⭐ 低'
    else:
        return '—'


# ============================================================
# 信号日志
# ============================================================

SIGNAL_LOG_PATH = "signal_log.json"


def log_signal(symbol: str, signal_type: str, price: float,
               confidence: str, note: str = ""):
    """
    将信号记录到本地 JSON 日志

    Args:
        symbol:      股票代码
        signal_type: 'BUY' / 'SELL'
        price:       当前价格
        confidence:  置信度
        note:        备注
    """
    log_entry = {
        '时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '股票': symbol,
        '信号': signal_type,
        '价格': price,
        '置信度': confidence,
        '备注': note
    }

    # 读取现有日志
    logs = []
    if os.path.exists(SIGNAL_LOG_PATH):
        try:
            with open(SIGNAL_LOG_PATH, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except Exception:
            logs = []

    logs.append(log_entry)

    # 只保留最近 500 条
    if len(logs) > 500:
        logs = logs[-500:]

    with open(SIGNAL_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def get_signal_history(symbol: Optional[str] = None,
                       signal_type: Optional[str] = None,
                       days: int = 30) -> pd.DataFrame:
    """
    读取信号历史记录

    Args:
        symbol:      筛选股票，None = 全部
        signal_type: 'BUY' / 'SELL'，None = 全部
        days:        最近 N 天

    Returns:
        pd.DataFrame: 信号历史
    """
    if not os.path.exists(SIGNAL_LOG_PATH):
        return pd.DataFrame()

    try:
        with open(SIGNAL_LOG_PATH, 'r', encoding='utf-8') as f:
            logs = json.load(f)
    except Exception:
        return pd.DataFrame()

    df = pd.DataFrame(logs)

    if df.empty:
        return df

    # 筛选
    if '时间' in df.columns:
        df['时间'] = pd.to_datetime(df['时间'])
        cutoff = datetime.now() - timedelta(days=days)
        df = df[df['时间'] >= cutoff]

    if symbol and '股票' in df.columns:
        df = df[df['股票'] == symbol]
    if signal_type and '信号' in df.columns:
        df = df[df['信号'] == signal_type]

    return df.sort_values('时间', ascending=False) if '时间' in df.columns else df


# ============================================================
# 模拟交易
# ============================================================

def paper_trade(symbol: str,
                signal: str,
                price: float,
                balance: float = 100000,
                position: int = 0,
                paper_log_path: str = "paper_trade.json") -> Dict:
    """
    模拟交易：记录虚拟买卖，跟踪持仓和资金

    Args:
        symbol:         股票代码
        signal:         'BUY' / 'SELL'
        price:          成交价
        balance:        当前资金
        position:       当前持仓股数
        paper_log_path: 模拟交易日志路径

    Returns:
        dict: 更新后的 balance, position, 交易确认
    """
    # 读取当前状态
    state = {'balance': balance, 'position': position, 'trades': []}
    if os.path.exists(paper_log_path):
        try:
            with open(paper_log_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
        except Exception:
            pass

    result = {
        '时间': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        '股票': symbol,
        '操作': signal,
        '价格': price
    }

    if signal == 'BUY' and state['position'] == 0:
        # 全仓买入
        shares = int(state['balance'] * 0.95 / price / 100) * 100  # 按手
        if shares > 0:
            cost = shares * price * (1 + 0.0003)  # 佣金
            state['balance'] -= cost
            state['position'] = shares
            result['股数'] = shares
            result['花费'] = round(cost, 2)
            result['说明'] = f"买入 {shares} 股 @ {price}"
        else:
            result['说明'] = '资金不足，无法买入'

    elif signal == 'SELL' and state['position'] > 0:
        revenue = state['position'] * price * (1 - 0.0003 - 0.001)  # 佣金+印花税
        state['balance'] += revenue
        result['股数'] = state['position']
        result['收入'] = round(revenue, 2)
        result['说明'] = f"卖出 {state['position']} 股 @ {price}"
        state['position'] = 0

    else:
        result['说明'] = f"忽略：已有持仓={state['position']}" if state['position'] > 0 else '无持仓可卖'

    # 保存状态
    state['trades'].append(result)
    if len(state['trades']) > 200:
        state['trades'] = state['trades'][-200:]

    # 确保目录存在
    os.makedirs(os.path.dirname(paper_log_path) or '.', exist_ok=True)
    with open(paper_log_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    return {
        'balance': round(state['balance'], 2),
        'position': state['position'],
        'trade': result
    }
