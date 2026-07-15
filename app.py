"""
模块：主入口 (app.py) — Streamlit 用户界面
功能：多页面导航（策略回测 + 策略工坊 + 因子分析 + 参数优化 + 组合管理 + 风险分析 + 过拟合检测 + 实盘信号）
依赖：
    - config.py           系统配置（SYSTEM_PROMPT）
    - deepseek_api.py     DeepSeek API 客户端（call_deepseek, extract_code, validate_strategy_code）
    - data_loader.py      数据获取层（fetch_stock_data）
    - strategies.py       内置策略信号生成（generate_right_signal, generate_v_shape_signal）
    - backtest.py         回测引擎与绩效评估（run_backtest）
    - charts.py           可视化图表（plot_equity, plot_kline_with_signals, plot_drawdown）
    - factor_analysis.py  多因子分析（compute_all_factors, compute_ic_analysis, layer_backtest, factor_correlation）
    - optimizer.py        参数优化（grid_search, walk_forward_analysis, parameter_sensitivity）
    - portfolio.py        组合管理（batch_backtest, equal_weight, risk_parity, max_sharpe, kelly_allocation）
    - risk_model.py       风险模型（compute_var, stress_test, drawdown_analysis, monte_carlo_simulation）
    - overfit_check.py    过拟合检测（train_test_split_test, cscv_analysis, compute_pbo, white_noise_test）
    - live_signal.py      实盘信号（scan_signals, log_signal, get_signal_history, paper_trade）
"""
# ============================================================
# 0. 导入依赖
# ============================================================
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
from dotenv import load_dotenv

# 可选：增强代码编辑器
try:
    from streamlit_ace import st_ace  # type: ignore[import-unresolved]
    ACE_AVAILABLE = True
except ImportError:
    ACE_AVAILABLE = False

# 本地模块导入
from config import SYSTEM_PROMPT
from deepseek_api import call_deepseek, extract_code, validate_strategy_code, check_missing_imports
from data_loader import fetch_stock_data
from strategies import generate_right_signal, generate_v_shape_signal
from backtest import run_backtest
from charts import plot_equity, plot_kline_with_signals, plot_drawdown
from factor_analysis import compute_all_factors, compute_ic_analysis, layer_backtest, factor_correlation, translate_factor
from optimizer import grid_search, walk_forward_analysis, parameter_sensitivity, parse_strategy_params, make_strategy_wrapper
from portfolio import batch_backtest, equal_weight, risk_parity, max_sharpe, kelly_allocation, compute_portfolio_metrics
from risk_model import compute_var, stress_test, drawdown_analysis, monte_carlo_simulation
from overfit_check import train_test_split_test, cscv_analysis, compute_pbo, white_noise_test
from live_signal import scan_signals, log_signal, get_signal_history, paper_trade

warnings.filterwarnings('ignore')
load_dotenv()


# ============================================================
# 0.1 通用策略调度 —— 各高级模块统一调用此函数获取当前策略
# ============================================================

def _get_current_strategy():
    """
    根据 st.session_state 返回当前激活的策略函数

    支持三种来源：
    - 内置策略 → 直接返回 generate_right_signal 或 generate_v_shape_signal
    - 自定义代码 → 动态编译并返回 generate_signal 函数
    - AI 生成代码 → 同自定义，从 st.session_state.custom_strategy_code 获取

    Returns:
        tuple: (strategy_func, strategy_params, strategy_label)
            - strategy_func:  策略信号生成函数
            - strategy_params: 内置策略参数 dict（自定义/AI 则为空）
            - strategy_label:  策略名称
    """
    name = st.session_state.get("active_strategy_name", "内置-右侧趋势")
    code = st.session_state.get("custom_strategy_code", "")

    # --- 内置策略 ---
    if "右侧趋势" in name:
        params = {'ma_short': 5, 'ma_mid': 20, 'ma_long': 60, 'vol_ratio': 1.5}
        return generate_right_signal, params, name
    elif "V型反转" in name or "v_shape" in name.lower():
        params = {'lookback': 10, 'drop_threshold': 0.15, 'rebound_threshold': 0.01, 'v_vol_ratio': 1.3}
        return generate_v_shape_signal, params, name

    # --- 自定义 / AI 策略 ---
    if code:
        try:
            local_ns = {}
            exec(code, {}, local_ns)
            if 'generate_signal' in local_ns:
                raw_func = local_ns['generate_signal']
                # 自动包装：如果策略不接受 kwargs，包装一下使其兼容
                import inspect as _inspect
                _sig = _inspect.signature(raw_func)
                if 'kwargs' not in str(_sig) and len(_sig.parameters) <= 1:
                    def _wrapped(df, **kwargs):
                        return raw_func(df)
                    return _wrapped, {}, name
                return raw_func, {}, name
        except Exception:
            pass

    # --- 兜底：右侧趋势 ---
    return generate_right_signal, {'ma_short': 5, 'ma_mid': 20, 'ma_long': 60, 'vol_ratio': 1.5}, name


# 参数/指标列名中英文对照
_METRIC_LABELS = {
    'ma_short': '短期均线/ma_short',
    'ma_mid': '中期均线/ma_mid',
    'ma_long': '长期均线/ma_long',
    'vol_ratio': '放量倍数/vol_ratio',
    'total_return': '总收益率/total_return',
    'sharpe_ratio': '夏普比率/sharpe_ratio',
    'max_drawdown': '最大回撤/max_drawdown',
    'win_rate': '胜率/win_rate',
    'calmar_ratio': 'Calmar比率/calmar_ratio',
    'profit_factor': '盈亏因子/profit_factor',
    'total_trades': '交易次数/total_trades',
    'annual_return': '年化收益/annual_return',
    'sortino_ratio': 'Sortino比率/sortino_ratio',
    'param_value': '参数值/param_value',
    'param_name': '参数名/param_name',
}


def _translate_columns(df, labels=None):
    """给 DataFrame 列名加中文翻译，格式：中文/英文"""
    if labels is None:
        labels = _METRIC_LABELS
    df = df.copy()
    rename_map = {c: labels[c] for c in df.columns if c in labels}
    df.rename(columns=rename_map, inplace=True)
    return df


# ============================================================
# 1. 页面配置与全局状态初始化
# ============================================================
st.set_page_config(page_title="量化回测系统", layout="wide")

# 持久化的跨页面状态
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
# 2. Page 1: 策略回测中心
# ============================================================
def backtest_page():
    """策略回测主页面：侧边栏交易控制台 + 策略配置 + 回测结果看板"""
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

    # ================================================================
    # 侧边栏 — 极简交易控制台
    # ================================================================
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
        st.caption(f"📌 当前策略：**{st.session_state.active_strategy_name}**")

        run_btn = st.button("🚀 运行回测", type="primary", use_container_width=True)

        st.markdown("---")
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
    # 主区域 — 紧凑策略配置栏
    # ================================================================
    strategy_type = st.radio(
        "策略来源",
        ["📈 内置", "✏️ 自定义", "🤖 AI"],
        horizontal=True,
        key="backtest_strategy_type",
        help="内置=预设策略 | 自定义=手动编码 | AI=DeepSeek 生成"
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

    # ================================================================
    # 高级交易参数（折叠面板）
    # ================================================================
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
        _execute_backtest(
            symbol, start_str, end_str, initial_cash,
            strategy_type, builtin_sub, user_code,
            ma_short, ma_mid, ma_long, vol_ratio,
            lookback, drop_threshold, rebound_threshold, v_vol_ratio,
            stop_loss, take_profit, position_pct,
            trailing_stop, use_atr_stop, atr_multiple,
            signal_confirm, slippage, stamp_duty
        )
    else:
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
# 3. 回测执行逻辑
# ============================================================
def _execute_backtest(symbol, start_str, end_str, initial_cash,
                      strategy_type, builtin_sub, user_code,
                      ma_short, ma_mid, ma_long, vol_ratio,
                      lookback, drop_threshold, rebound_threshold, v_vol_ratio,
                      stop_loss, take_profit, position_pct,
                      trailing_stop, use_atr_stop, atr_multiple,
                      signal_confirm, slippage, stamp_duty):
    """执行完整回测流程：获取数据 → 生成信号 → 运行回测 → 渲染结果"""
    # 获取行情数据
    with st.spinner("正在获取数据..."):
        df = fetch_stock_data(symbol, start_str, end_str)
    if df is None or df.empty:
        st.error("无法获取数据，请检查股票代码或网络")
        st.stop()

    # 根据策略类型生成交易信号
    with st.spinner("生成策略信号..."):
        if strategy_type == "📈 内置":
            if builtin_sub == "📈 右侧趋势":
                df_signal = generate_right_signal(df, ma_short, ma_mid, ma_long, vol_ratio)
            else:
                df_signal = generate_v_shape_signal(df, lookback, drop_threshold, rebound_threshold, v_vol_ratio)
            st.session_state.active_strategy_name = builtin_sub

        elif strategy_type in ("✏️ 自定义", "🤖 AI"):
            code = user_code if strategy_type == "✏️ 自定义" else st.session_state.get("custom_strategy_code", "")
            if not code:
                st.error("请先准备策略代码（在「策略工坊」页面生成或编写）")
                st.stop()
            try:
                # 检查代码中引用的库是否已安装
                missing = check_missing_imports(code)
                if missing:
                    cmds = ' '.join(f'`pip install {m}`' for m in missing)
                    st.error(f"❌ 策略代码引用了未安装的库：{', '.join(missing)}\n\n请在终端执行：{cmds}")
                    st.stop()

                local_namespace = {}
                exec(code, {}, local_namespace)
                if 'generate_signal' not in local_namespace:
                    st.error("未找到 generate_signal 函数")
                    st.stop()
                df_signal = local_namespace['generate_signal'](df)
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
            label = "自定义策略" if strategy_type == "✏️ 自定义" else "AI生成策略"
            st.session_state.active_strategy_name = label
        else:
            st.error("未知策略类型")
            st.stop()

    # 运行回测
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
    _render_results(symbol, start_str, end_str, df_signal, trades, equity, metrics, initial_cash)


# ============================================================
# 4. 结果渲染
# ============================================================
def _render_results(symbol, start_str, end_str, df_signal, trades, equity, metrics, initial_cash):
    """渲染回测结果：指标卡片、图表、交易明细、导出按钮"""
    # 核心指标行 1
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📈 总收益率", f"{metrics['total_return']:.2f}%")
    c2.metric("📅 年化收益", f"{metrics['annual_return']:.2f}%")
    c3.metric("📉 最大回撤", f"{metrics['max_drawdown']:.2f}%")
    c4.metric("📊 夏普比率", f"{metrics['sharpe_ratio']:.3f}")
    c5.metric("🎯 胜率", f"{metrics['win_rate']:.2f}%")

    # 高级指标行 2
    c6, c7, c8, c9, c10 = st.columns(5)
    c6.metric("🛡️ Calmar", f"{metrics['calmar_ratio']:.3f}",
              help="年化收益÷最大回撤，越高越好")
    c7.metric("📐 Sortino", f"{metrics['sortino_ratio']:.3f}",
              help="仅惩罚下行波动的夏普改进版")
    c8.metric("💰 盈亏因子", f"{metrics['profit_factor']:.3f}",
              help="总盈利÷总亏损，>1.5 为优秀")
    c9.metric("🔄 交易次数", metrics['total_trades'])
    c10.metric("📋 盈亏比", f"{metrics['profit_loss_ratio']:.3f}")

    # 补充指标行 3
    ca, cb, cc = st.columns(3)
    ca.metric("📊 最大连亏(次)", metrics['max_consecutive_loss'])
    cb.metric("⏱️ 平均持仓(天)", f"{metrics['avg_hold_days']:.1f}")
    cc.metric("💵 最终权益", f"{metrics['final_equity']:,.0f}")

    # 图表
    st.markdown("---")
    st.components.v1.html(plot_equity(equity, initial_cash), height=450, scrolling=False)
    plot_kline_with_signals(df_signal, trades)
    st.plotly_chart(plot_drawdown(equity), use_container_width=True)

    # 明细 & 导出
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


# ============================================================
# 5. Page 2: 策略工坊
# ============================================================
def workshop_page():
    """策略工坊页面：AI 对话生成策略 + 手动代码编辑器 + 策略模板库"""
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
        for msg in st.session_state.deepseek_messages:
            if msg["role"] == "system":
                continue
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

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
            "策略代码", value=default_code, height=350, key="manual_code_editor"
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

        # 策略模板库
        with st.expander("📚 策略模板库（点击加载）"):
            _render_strategy_templates()


# ============================================================
# 6. 策略模板库
# ============================================================
def _render_strategy_templates():
    """渲染 5 套经典量化策略模板按钮"""
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


# ============================================================
# 7. Page 3: 因子分析
# ============================================================
def factor_page():
    """因子分析页面：IC 分析、分层回测、因子相关性"""
    st.title("🧬 因子分析")
    st.markdown("计算多因子 IC、分层回测，评估因子预测能力")

    symbol = st.text_input("股票代码", value="600160", key="factor_symbol")
    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("开始日期", value=datetime(2020, 1, 1), key="factor_start")
    with col2:
        end = st.date_input("结束日期", value=datetime.now(), key="factor_end")

    if st.button("🧬 开始分析", type="primary"):
        with st.spinner("获取数据并计算因子..."):
            df = fetch_stock_data(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            if df is None or df.empty:
                st.error("数据获取失败")
                st.stop()

            df_factors = compute_all_factors(df)

        # IC 分析
        st.subheader("📊 IC 分析（信息系数）")
        with st.spinner("计算 IC..."):
            ic_result = compute_ic_analysis(df_factors)
        if not ic_result['ic_summary'].empty:
            st.dataframe(ic_result['ic_summary'], use_container_width=True)
            st.caption("IC_IR > 0.3 为有效因子，> 0.5 为优秀因子")
        else:
            st.warning("数据不足，无法计算 IC")

        # 分层回测
        st.subheader("📈 分层回测")
        factor_names = ic_result['ic_summary']['因子'].tolist()[:5] if not ic_result['ic_summary'].empty else []
        top_factor_label = st.selectbox("选择因子", factor_names, key="layer_factor")
        if top_factor_label:
            # 从翻译名中提取原始因子名（格式：原始名 / 中文名）
            top_factor = top_factor_label.split(' / ')[0]
            layer_result = layer_backtest(df_factors, top_factor)
            if layer_result is not None:
                st.dataframe(layer_result, use_container_width=True)

        # 相关性矩阵
        st.subheader("🔗 因子相关性")
        corr_matrix = factor_correlation(df_factors)
        if not corr_matrix.empty:
            st.dataframe(corr_matrix.style.background_gradient(cmap='RdYlGn', axis=None),
                         use_container_width=True)
            st.caption("|r| > 0.7 表示两个因子高度相关，可考虑去除其一")
    else:
        st.info("👆 输入股票代码和日期范围，点击「开始分析」")


# ============================================================
# 8. Page 4: 参数优化
# ============================================================
def optimizer_page():
    """参数优化页面：网格搜索、前向推进分析、敏感度测试"""
    st.title("🔧 参数优化")
    st.markdown("网格搜索 + 前向推进分析，找到最优策略参数")

    strategy_func, strategy_params, strategy_label = _get_current_strategy()
    is_builtin = "内置" in strategy_label
    custom_code = st.session_state.get("custom_strategy_code", "")
    auto_params = parse_strategy_params(custom_code) if custom_code else {}
    wrapped_func = make_strategy_wrapper(strategy_func, custom_code) if (not is_builtin and custom_code) else strategy_func

    symbol = st.text_input("股票代码", value="600160", key="opt_symbol")
    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("开始日期", value=datetime(2020, 1, 1), key="opt_start")
    with col2:
        end = st.date_input("结束日期", value=datetime.now(), key="opt_end")

    tab_gs, tab_wfa, tab_sens = st.tabs(["🔍 网格搜索", "🔄 前向推进(WFA)", "📐 参数敏感度"])

    with tab_gs:
        st.markdown("### 网格搜索最优参数")

        if is_builtin:
            st.caption(f"📌 内置策略：{strategy_label}")
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                ma_vals = st.multiselect("短期均线", [3, 5, 7, 10, 15], default=[5, 10], key="gs_ma")
            with col_b:
                vol_vals = st.multiselect("放量倍数", [1.0, 1.3, 1.5, 1.8, 2.0], default=[1.3, 1.5], key="gs_vol")
            with col_c:
                metric_opt = st.selectbox("优化目标", ['sharpe_ratio', 'total_return', 'calmar_ratio', 'profit_factor'],
                                           format_func=lambda x: {'sharpe_ratio': '夏普比率', 'total_return': '总收益率',
                                                                  'calmar_ratio': 'Calmar比率', 'profit_factor': '盈亏因子'}[x])
            if st.button("🚀 运行网格搜索", type="primary", key="run_gs"):
                with st.spinner("正在搜索最优参数..."):
                    df = fetch_stock_data(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
                    if df is None or df.empty:
                        st.error("数据获取失败")
                        st.stop()
                    param_grid = {'ma_short': ma_vals, 'vol_ratio': vol_vals}
                    result = grid_search(df, strategy_func, param_grid, run_backtest, metric_opt)
                    if not result.empty:
                        st.success(f"✅ 找到 {len(result)} 组有效参数")
                        st.dataframe(_translate_columns(result), use_container_width=True)
                        best = result.iloc[0]
                        st.metric("🏆 最优参数", f"短期均线={best['ma_short']}, 放量倍数={best['vol_ratio']}")
                        st.metric("📊 最优夏普", f"{best.get('sharpe_ratio', 0):.3f}")
                    else:
                        st.warning("未找到有效参数组合")

        elif auto_params:
            st.success(f"📌 自定义策略：{strategy_label} → 识别到 {len(auto_params)} 个参数：{', '.join(auto_params.keys())}")
            selected_params = {}
            acols = st.columns(min(len(auto_params), 4))
            for i, (pname, pvalues) in enumerate(auto_params.items()):
                with acols[i % len(acols)]:
                    selected = st.multiselect(pname, pvalues, default=pvalues[:3] if len(pvalues) > 3 else pvalues,
                                              key=f"gs_auto_{pname}")
                    if selected:
                        selected_params[pname] = selected
            if selected_params and st.button("🚀 运行网格搜索", type="primary", key="run_gs_auto"):
                with st.spinner("搜索中..."):
                    df = fetch_stock_data(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
                    if df is not None and not df.empty:
                        result = grid_search(df, wrapped_func, selected_params, run_backtest)
                        if not result.empty:
                            st.success(f"✅ 找到 {len(result)} 组有效参数")
                            st.dataframe(_translate_columns(result.head(10)), use_container_width=True)
                        else:
                            st.warning("未找到有效参数组合")
        else:
            st.warning("⚠️ 当前策略无 `# @PARAMS:` 注释。请在策略代码顶部添加参数声明，例如：\n\n"
                       "`# @PARAMS: ma_short=3,15,2; ma_long=10,60,5`\n\n"
                       "然后 `def generate_signal(df, **kwargs):` 中用 `kwargs.get('ma_short', 5)` 取值。")

    with tab_wfa:
        st.markdown("### 前向推进分析 (Walk-Forward Analysis)")
        st.caption("滚动窗口训练+测试，评估策略在不同市场阶段的稳定性")

        train_m = st.slider("训练窗口(月)", 6, 24, 12, key="wfa_train")
        test_m = st.slider("测试窗口(月)", 1, 6, 3, key="wfa_test")

        if st.button("🔄 运行 WFA", type="primary", key="run_wfa"):
            with st.spinner("正在执行前向推进分析..."):
                df = fetch_stock_data(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
                if df is None or df.empty:
                    st.error("数据获取失败")
                    st.stop()

                param_grid = {'ma_short': [5, 10], 'vol_ratio': [1.3, 1.5]}
                wfa_result = walk_forward_analysis(df, strategy_func, run_backtest,
                                                    param_grid, train_months=train_m, test_months=test_m)

                if not wfa_result['wfa_results'].empty:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("样本内夏普", wfa_result['is_sharpe'])
                    c2.metric("样本外夏普", wfa_result['oos_sharpe'])
                    c3.metric("鲁棒性评分", f"{wfa_result['robustness']:.0%}",
                              help="OOS/IS 比值，>70% 说明策略鲁棒")
                    st.dataframe(wfa_result['wfa_results'], use_container_width=True)
                else:
                    st.warning("数据不足以执行 WFA")

    with tab_sens:
        st.markdown("### 参数敏感度分析")
        st.caption("在最优参数附近微调，观察指标变化")

        base_ma = st.number_input("基准短期均线", 3, 20, 5, key="sens_ma")
        base_vol = st.number_input("基准放量倍数", 1.0, 3.0, 1.5, 0.1, key="sens_vol")

        if st.button("📐 分析敏感度", type="primary", key="run_sens"):
            with st.spinner("计算参数敏感度..."):
                df = fetch_stock_data(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
                if df is None or df.empty:
                    st.error("数据获取失败")
                    st.stop()

                sens_result = parameter_sensitivity(df, strategy_func, run_backtest,
                                                     {'ma_short': base_ma, 'vol_ratio': base_vol},
                                                     'ma_short', (base_ma - 3, base_ma + 5))
                if not sens_result.empty:
                    st.dataframe(_translate_columns(sens_result), use_container_width=True)
                    st.line_chart(sens_result.set_index('参数值')['夏普比率'])


# ============================================================
# 9. Page 5: 组合管理
# ============================================================
def portfolio_page():
    """组合管理页面：多股票批量回测、仓位分配"""
    st.title("📦 组合管理")
    st.markdown("多股票批量回测 + 智能仓位分配")

    strategy_func, strategy_params, strategy_label = _get_current_strategy()
    st.caption(f"📌 当前策略：**{strategy_label}**")

    tab_batch, tab_alloc = st.tabs(["📊 批量回测", "⚖️ 仓位分配"])

    with tab_batch:
        symbols_input = st.text_area("股票代码（每行一个）", value="600160\n000001\n600519", height=100,
                                      key="batch_symbols")
        col1, col2 = st.columns(2)
        with col1:
            start = st.date_input("开始日期", value=datetime(2020, 1, 1), key="batch_start")
        with col2:
            end = st.date_input("结束日期", value=datetime.now(), key="batch_end")

        if st.button("📊 批量回测", type="primary", key="run_batch"):
            symbols = [s.strip() for s in symbols_input.split('\n') if s.strip()]
            if not symbols:
                st.warning("请输入股票代码")
            else:
                with st.spinner(f"正在回测 {len(symbols)} 只股票..."):
                    result = batch_backtest(symbols, fetch_stock_data, strategy_func,
                                           run_backtest, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
                if not result.empty:
                    st.dataframe(result, use_container_width=True)
                    # 高亮成功行
                    success = result[result['状态'] == '成功']
                    if not success.empty:
                        st.success(f"✅ {len(success)}/{len(symbols)} 只回测成功")

    with tab_alloc:
        st.markdown("### 仓位分配算法")
        st.caption("基于回测结果计算最优仓位权重")

        alloc_method = st.selectbox("分配方法", ['equal', 'risk_parity', 'max_sharpe', 'kelly'],
                                     format_func=lambda x: {'equal': '等权分配', 'risk_parity': '风险平价',
                                                            'max_sharpe': '最大夏普', 'kelly': '凯利公式(半凯利)'}[x])

        if st.button("⚖️ 计算权重", type="primary", key="run_alloc"):
            st.info("此功能需先运行批量回测获取各股票收益数据。\n请在「批量回测」标签页先执行回测。")


# ============================================================
# 10. Page 6: 风险分析
# ============================================================
def risk_page():
    """风险分析页面：VaR、压力测试、回撤分析、蒙特卡洛模拟"""
    st.title("🛡️ 风险分析")
    st.markdown("VaR/CVaR 计算 · 压力测试 · 回撤深度分析 · 蒙特卡洛模拟")

    strategy_func, strategy_params, strategy_label = _get_current_strategy()

    symbol = st.text_input("股票代码", value="600160", key="risk_symbol")
    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("开始日期", value=datetime(2020, 1, 1), key="risk_start")
    with col2:
        end = st.date_input("结束日期", value=datetime.now(), key="risk_end")

    if st.button("🛡️ 运行风险分析", type="primary", key="run_risk"):
        with st.spinner("获取数据..."):
            df = fetch_stock_data(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            if df is None or df.empty:
                st.error("数据获取失败")
                st.stop()
            returns = df['close'].pct_change().dropna()

        # VaR
        st.subheader("📉 VaR & CVaR")
        col_v1, col_v2, col_v3 = st.columns(3)
        with col_v1:
            var_h = compute_var(returns, 0.95, 'historical')
            st.metric("历史VaR(95%)/" + "Historical VaR", f"{var_h['VaR']}%", help=var_h['VaR_金额'])
        with col_v2:
            var_p = compute_var(returns, 0.95, 'parametric')
            st.metric("参数VaR(95%)/" + "Parametric VaR", f"{var_p['VaR']}%")
        with col_v3:
            var_cf = compute_var(returns, 0.95, 'cornish_fisher')
            st.metric("CF-VaR(95%)/" + "Cornish-Fisher VaR", f"{var_cf['VaR']}%")

        # 压力测试
        st.subheader("🌪️ 压力测试")
        stress = stress_test(returns)
        st.dataframe(stress, use_container_width=True)

        # 回撤分析
        st.subheader("📊 回撤深度分析")
        # 用回测引擎的结果
        with st.spinner("运行回测获取权益曲线..."):
            df_signal = strategy_func(df, **strategy_params)
            trades, equity, _ = run_backtest(df_signal)
            if equity is not None:
                dd_result = drawdown_analysis(equity)
                col_d1, col_d2, col_d3 = st.columns(3)
                col_d1.metric("最大回撤深度", dd_result['max_drawdown_depth'])
                col_d2.metric("平均恢复天数", dd_result['avg_recovery_days'])
                col_d3.metric("回撤时间占比", dd_result['total_drawdown_ratio'])
                if not dd_result['drawdown_periods'].empty:
                    st.dataframe(dd_result['drawdown_periods'], use_container_width=True)

        # 蒙特卡洛
        st.subheader("🎲 蒙特卡洛模拟")
        n_sim = st.slider("模拟次数", 100, 2000, 500, 100, key="mc_n")
        if st.button("🎲 运行模拟", key="run_mc"):
            with st.spinner("生成模拟路径..."):
                paths = monte_carlo_simulation(returns, n_simulations=n_sim, horizon_days=252)
                st.line_chart(paths.iloc[:, :50])  # 只显示前 50 条
                final_vals = paths.iloc[-1]
                st.metric("中位数终值", f"{final_vals.median():,.0f} 元")
                st.metric("5%最差", f"{final_vals.quantile(0.05):,.0f} 元")
    else:
        st.info("👆 输入股票代码，点击「运行风险分析」")


# ============================================================
# 11. Page 7: 过拟合检测
# ============================================================
def overfit_page():
    """过拟合检测页面：IS/OOS 分割、CSCV、PBO、白噪声检验"""
    st.title("🔬 过拟合检测")
    st.markdown("样本内外测试 · CSCV 交叉验证 · PBO 概率 · 白噪声检验")

    strategy_func, strategy_params, strategy_label = _get_current_strategy()
    st.caption(f"📌 当前策略：**{strategy_label}**")

    symbol = st.text_input("股票代码", value="600160", key="of_symbol")
    col1, col2 = st.columns(2)
    with col1:
        start = st.date_input("开始日期", value=datetime(2020, 1, 1), key="of_start")
    with col2:
        end = st.date_input("结束日期", value=datetime.now(), key="of_end")

    if st.button("🔬 运行检测", type="primary", key="run_of"):
        with st.spinner("获取数据..."):
            df = fetch_stock_data(symbol, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
            if df is None or df.empty:
                st.error("数据获取失败")
                st.stop()
            returns = df['close'].pct_change().dropna()

        tab_is, tab_cscv, tab_pbo, tab_wn = st.tabs(["📊 IS/OOS", "🔄 CSCV", "🎯 PBO", "🔊 白噪声"])

        with tab_is:
            st.subheader("样本内/外分割测试")
            split = train_test_split_test(df, strategy_func, run_backtest, **strategy_params)
            col_a, col_b = st.columns(2)
            with col_a:
                st.markdown("**样本内 (IS)**")
                is_m = split['样本内(IS)']
                if 'error' not in is_m:
                    st.metric("夏普", f"{is_m.get('sharpe_ratio', 0):.3f}")
                    st.metric("收益", f"{is_m.get('total_return', 0):.2f}%")
                    st.metric("回撤", f"{is_m.get('max_drawdown', 0):.2f}%")
                else:
                    st.error(is_m['error'])
            with col_b:
                st.markdown("**样本外 (OOS)**")
                oos_m = split['样本外(OOS)']
                if 'error' not in oos_m:
                    st.metric("夏普", f"{oos_m.get('sharpe_ratio', 0):.3f}")
                    st.metric("收益", f"{oos_m.get('total_return', 0):.2f}%")
                    st.metric("回撤", f"{oos_m.get('max_drawdown', 0):.2f}%")
                else:
                    st.error(oos_m['error'])

        with tab_cscv:
            st.subheader("CSCV 组合交叉验证")
            n_splits = st.slider("分段数", 5, 20, 10, key="cscv_n")
            cscv = cscv_analysis(df, strategy_func, run_backtest, n_splits=n_splits, **strategy_params)
            st.metric("稳定性评分", cscv['stability_score'], help=">1.5=稳定, <0.5=极不稳定")
            st.metric("负夏普占比", cscv['neg_sharpe_ratio'])
            st.info(cscv['warning'])
            if not cscv['segments'].empty:
                st.dataframe(cscv['segments'], use_container_width=True)
                st.line_chart(cscv['segments'].set_index('分段')['夏普比率'])

        with tab_pbo:
            st.subheader("回测过拟合概率 (PBO)")
            st.caption("需要先运行参数优化的网格搜索")
            if st.button("🎯 计算 PBO", key="run_pbo"):
                with st.spinner("运行网格搜索..."):
                    param_grid = {'ma_short': [3, 5, 7, 10, 15], 'vol_ratio': [1.0, 1.3, 1.5, 1.8, 2.0]}
                    gs = grid_search(df, strategy_func, param_grid, run_backtest)
                    if not gs.empty:
                        pbo_result = compute_pbo(gs)
                        st.metric("PBO", f"{pbo_result['PBO']*100:.1f}%" if pbo_result['PBO'] else 'N/A')
                        st.info(pbo_result.get('风险等级', ''))
                        st.caption(pbo_result.get('PBO_解释', ''))
                    else:
                        st.warning("网格搜索无结果")

        with tab_wn:
            st.subheader("白噪声检验 (Ljung-Box)")
            wn = white_noise_test(returns, [1, 5, 10, 20])
            st.dataframe(wn, use_container_width=True)
            st.caption("p < 0.05 说明存在自相关，可预测；否则接近白噪声，技术分析可能无效")
    else:
        st.info("👆 输入股票代码，点击「运行检测」")


# ============================================================
# 12. Page 8: 实盘信号
# ============================================================
def live_page():
    """实盘信号页面：定时扫描、信号日志、模拟交易"""
    st.title("📡 实盘信号")
    st.markdown("定时扫描买入信号 · 信号历史日志 · 模拟交易")

    strategy_func, strategy_params, strategy_label = _get_current_strategy()
    st.caption(f"📌 当前策略：**{strategy_label}**")

    tab_scan, tab_log, tab_paper = st.tabs(["🔍 信号扫描", "📋 信号日志", "💰 模拟交易"])

    with tab_scan:
        st.subheader("扫描当前买入信号")
        symbols_input = st.text_area("监控股票（每行一个）", value="600160\n000001\n600519",
                                      height=100, key="live_symbols")

        if st.button("🔍 立即扫描", type="primary", key="run_scan"):
            symbols = [s.strip() for s in symbols_input.split('\n') if s.strip()]
            with st.spinner(f"扫描 {len(symbols)} 只股票..."):
                signals = scan_signals(symbols, fetch_stock_data, strategy_func, **strategy_params)
            if not signals.empty:
                st.dataframe(signals, use_container_width=True)
                buys = signals[signals['信号'].str.contains('买入')]
                if not buys.empty:
                    st.success(f"🟢 {len(buys)} 只股票出现买入信号！")
                    for _, row in buys.iterrows():
                        log_signal(row['股票'], 'BUY', row['最新价'] or 0,
                                  row.get('置信度', '—'), f"自动扫描触发")

    with tab_log:
        st.subheader("信号历史")
        days = st.slider("最近天数", 1, 90, 30, key="log_days")
        log_df = get_signal_history(days=days)
        if not log_df.empty:
            st.dataframe(log_df, use_container_width=True)
            st.metric("总信号数", len(log_df))
        else:
            st.info("暂无信号记录，请先执行信号扫描")

    with tab_paper:
        st.subheader("模拟交易")
        st.caption("基于扫描信号执行模拟买卖，跟踪虚拟资金和持仓")

        # 读取当前状态
        import json
        paper_path = "paper_trade.json"
        state = {'balance': 100000, 'position': 0, 'trades': []}
        if os.path.exists(paper_path):
            try:
                with open(paper_path, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            except Exception:
                pass

        col_a, col_b = st.columns(2)
        col_a.metric("💰 可用资金", f"{state['balance']:,.0f} 元")
        col_b.metric("📦 持仓", f"{state['position']} 股")

        paper_symbol = st.text_input("交易股票", value="600160", key="paper_symbol")
        paper_price = st.number_input("成交价", value=10.0, step=0.01, key="paper_price")
        col_x, col_y = st.columns(2)
        with col_x:
            if st.button("🟢 买入", type="primary", use_container_width=True):
                result = paper_trade(paper_symbol, 'BUY', paper_price,
                                    state['balance'], state['position'])
                st.success(result['trade'].get('说明', ''))
                st.metric("剩余资金", f"{result['balance']:,.0f}")
        with col_y:
            if st.button("🔴 卖出", type="primary", use_container_width=True):
                result = paper_trade(paper_symbol, 'SELL', paper_price,
                                    state['balance'], state['position'])
                st.success(result['trade'].get('说明', ''))
                st.metric("剩余资金", f"{result['balance']:,.0f}")

        if state.get('trades'):
            with st.expander("📋 交易历史"):
                st.dataframe(pd.DataFrame(state['trades']), use_container_width=True)


# ============================================================
# ============================================================
# 13. Page 9: 线性工作流 — 策略开发全流程
# ============================================================

_WORKFLOW_STEPS = [
    ("🤖", "策略创建", "在策略工坊中 AI 生成或手动编写策略"),
    ("📊", "策略回测", "完整回测：选股+配参+高级风控+图表"),
    ("🔧", "参数优化", "网格搜索最优参数（仅内置策略）"),
    ("🔬", "过拟合检测", "IS/OOS + CSCV + PBO 三轮验证"),
    ("🧬", "因子研究", "验证策略所用因子的有效性"),
    ("📦", "批量验证", "多股票批量回测，筛选标的"),
    ("🛡️", "风险评估", "VaR + 压力测试 + 蒙特卡洛"),
    ("📡", "实盘准备", "信号扫描 + 模拟交易"),
]


def workflow_page():
    """线性工作流页面：8 步向导，从上到下串联整个策略开发流程"""
    st.title("🚀 策略开发工作流")
    st.caption(f"📌 当前策略：**{st.session_state.get('active_strategy_name', '内置-右侧趋势')}**")

    # ---- 步骤状态（需在侧边栏之前定义） ----
    if "workflow_step" not in st.session_state:
        st.session_state["workflow_step"] = 0
    total = len(_WORKFLOW_STEPS)
    current = st.session_state["workflow_step"]

    # ---- 共享侧边栏 ----
    with st.sidebar:
        st.header("📌 工作流状态")
        st.caption(f"策略：**{st.session_state.get('active_strategy_name', '内置-右侧趋势')}**")
        st.progress((current + 1) / total)
        st.caption(f"进度：{current + 1}/{total}")

        # 所有步骤共享的标的和周期
        if current >= 1:
            st.markdown("---")
            st.markdown("### ⚙️ 回测配置")
            symbol = st.text_input("股票代码", value="600160", key="wf_symbol_shared")
            col_s2, col_e2 = st.columns(2)
            with col_s2:
                wf_start = st.date_input("开始", value=datetime(2020, 1, 1), key="wf_start_shared")
            with col_e2:
                wf_end = st.date_input("结束", value=datetime.now(), key="wf_end_shared")
            start_str = wf_start.strftime("%Y%m%d")
            end_str = wf_end.strftime("%Y%m%d")
            wf_cash = st.number_input("💰 资金", value=100000, step=10000, format="%d", key="wf_cash_shared")
        else:
            symbol = "600160"
            start_str = "20200101"
            end_str = datetime.now().strftime("%Y%m%d")
            wf_cash = 100000

        st.markdown("---")
        if st.button("🤖 策略工坊", use_container_width=True, key="wf_sidebar_workshop"):
            st.session_state["_current_page"] = "workshop"
            st.rerun()
        with st.expander("🔑 DeepSeek API Key"):
            if not st.session_state.deepseek_api_key:
                api_key_input = st.text_input("API Key", type="password", placeholder="sk-...", key="wf_api_key")
                if st.button("保存", key="wf_save_key"):
                    if api_key_input.startswith("sk-"):
                        st.session_state.deepseek_api_key = api_key_input
                        st.success("✅ 已保存")
                        st.rerun()
            else:
                st.success("✅ 已配置")

    # 进度条
    st.progress((current + 1) / total, f"步骤 {current + 1}/{total}")

    # 步骤按钮行
    cols = st.columns(total)
    for i, (icon, name, _) in enumerate(_WORKFLOW_STEPS):
        with cols[i]:
            label = f"{icon} {name}"
            if i == current:
                st.button(label, key=f"wf_step_{i}", type="primary", use_container_width=True, disabled=True)
            elif i < current:
                if st.button(label, key=f"wf_step_{i}", use_container_width=True):
                    st.session_state["workflow_step"] = i
                    st.rerun()
            else:
                st.button(label, key=f"wf_step_{i}", use_container_width=True, disabled=True)

    _icon, _name, hint = _WORKFLOW_STEPS[current]
    st.info(f"💡 **当前步骤：{_WORKFLOW_STEPS[current][1]}** — {_WORKFLOW_STEPS[current][2]}")

    st.markdown("---")
    strategy_func, strategy_params, strategy_label = _get_current_strategy()

    # ============ 步骤 0：策略创建 ============
    if current == 0:
        st.subheader("🤖 步骤 1/8：选择或创建策略")

        st.markdown("### 📚 经典策略模板")
        st.caption("点击卡片即可加载，加载后可修改代码")

        templates_data = [
            {"name": "双均线金叉", "type": "趋势跟踪", "diff": "⭐ 入门",
             "desc": "5日线上穿20日线时买入，简单经典的入门策略",
             "code": """def generate_signal(df):
    import pandas as pd
    data = df.copy()
    data['MA5'] = data['close'].rolling(5).mean()
    data['MA20'] = data['close'].rolling(20).mean()
    data['signal'] = (data['MA5'] > data['MA20']) & (data['MA5'].shift(1) <= data['MA20'].shift(1))
    data['signal_type'] = 'custom'
    return data"""},
            {"name": "MACD金叉", "type": "趋势跟踪", "diff": "⭐ 入门",
             "desc": "MACD指标金叉买入，捕捉中短期趋势转折",
             "code": """def generate_signal(df):
    import pandas as pd
    data = df.copy()
    e1 = data['close'].ewm(span=12, adjust=False).mean()
    e2 = data['close'].ewm(span=26, adjust=False).mean()
    data['DIF'] = e1 - e2
    data['DEA'] = data['DIF'].ewm(span=9, adjust=False).mean()
    data['signal'] = (data['DIF'] > data['DEA']) & (data['DIF'].shift(1) <= data['DEA'].shift(1))
    data['signal_type'] = 'custom'
    return data"""},
            {"name": "布林带突破", "type": "突破策略", "diff": "⭐⭐ 进阶",
             "desc": "股价突破布林带上轨且放量，捕捉强势突破行情",
             "code": """def generate_signal(df):
    import pandas as pd
    import numpy as np
    data = df.copy()
    data['MA20'] = data['close'].rolling(20).mean()
    data['STD'] = data['close'].rolling(20).std()
    data['Upper'] = data['MA20'] + 2 * data['STD']
    data['signal'] = (data['close'] > data['Upper']) & (data['volume'] > data['volume'].rolling(20).mean() * 1.5)
    data['signal_type'] = 'custom'
    return data"""},
            {"name": "RSI超卖反弹", "type": "均值回归", "diff": "⭐⭐ 进阶",
             "desc": "RSI低于30超卖区后反弹，捕捉超跌反弹机会",
             "code": """def generate_signal(df):
    import pandas as pd
    import numpy as np
    data = df.copy()
    delta = data['close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    data['RSI'] = 100 - (100 / (1 + gain / loss))
    data['signal'] = (data['RSI'] < 30) & (data['RSI'].shift(1) >= 30)
    data['signal_type'] = 'custom'
    return data"""},
            {"name": "放量突破", "type": "量价策略", "diff": "⭐ 入门",
             "desc": "成交量放大2倍且涨幅超2%，识别主力资金进场",
             "code": """def generate_signal(df):
    import pandas as pd
    data = df.copy()
    data['VOL_MA20'] = data['volume'].rolling(20).mean()
    data['RET'] = data['close'].pct_change()
    data['signal'] = (data['volume'] > data['VOL_MA20'] * 2) & (data['RET'] > 0.02)
    data['signal_type'] = 'custom'
    return data"""},
            {"name": "AI 对话生成", "type": "🤖 智能生成", "diff": "✨ 推荐",
             "desc": "用自然语言描述想法，DeepSeek 自动编写策略代码",
             "code": None, "action": "goto_workshop"},
        ]

        for row_start in range(0, len(templates_data), 3):
            row_items = templates_data[row_start:row_start + 3]
            cols = st.columns(3)
            for j, t in enumerate(row_items):
                with cols[j]:
                    with st.container(border=True):
                        st.markdown(f"**{t['name']}**  `{t['type']}`")
                        st.caption(t['desc'])
                        st.markdown(f"{t['diff']}")
                        if t.get('action') == 'goto_workshop':
                            if st.button("🤖 去策略工坊", key=f"wf_tmpl_{row_start+j}", use_container_width=True):
                                st.session_state["_current_page"] = "workshop"
                                st.rerun()
                        else:
                            if st.button("📋 加载此策略", key=f"wf_tmpl_{row_start+j}", use_container_width=True):
                                st.session_state.custom_strategy_code = t['code']
                                st.session_state.active_strategy_name = t['name']
                                st.success(f"✅ 「{t['name']}」已就绪！")
                                st.rerun()

        st.markdown("---")
        st.markdown("### 📌 当前策略状态")
        if st.session_state.get("custom_strategy_code"):
            st.success(f"✅ **{strategy_label}** 已加载")
            with st.expander("📝 查看/编辑代码"):
                edited = st.text_area("策略代码", value=st.session_state.custom_strategy_code, height=200, key="wf_edit_code")
                if st.button("💾 保存修改", key="wf_save_edit"):
                    is_valid, msg = validate_strategy_code(edited)
                    if is_valid:
                        st.session_state.custom_strategy_code = edited
                        st.success("✅ 已保存")
                        st.rerun()
                    else:
                        st.error(f"验证失败: {msg}")
        else:
            st.info("ℹ️ 尚未选择策略，将使用默认「右侧趋势」内置策略")

    # ============ 步骤 1：完整策略回测 ============
    elif current == 1:
        st.subheader("📊 步骤 2/8：策略回测")
        left, right = st.columns([1, 1])

        with left:
            st.markdown("### 🎯 策略配置")
            wf_strategy_type = st.radio("策略来源", ["📈 内置", "✏️ 自定义", "🤖 AI"], horizontal=True, key="wf_strategy_type")
            wf_user_code = ""
            wf_ma_s, wf_ma_m, wf_ma_l = 5, 20, 60
            wf_vol_r = 1.5
            wf_lookback, wf_drop, wf_rebound = 10, 0.15, 0.01
            wf_v_vol = 1.3
            wf_builtin_sub = "📈 右侧趋势"

            if wf_strategy_type == "📈 内置":
                wf_builtin_sub = st.radio("子策略", ["📈 右侧趋势", "🔍 V型反转"], horizontal=True, key="wf_builtin")
                if wf_builtin_sub == "📈 右侧趋势":
                    st.caption("均线多头 + MACD金叉 + 放量突破")
                    p1, p2 = st.columns(2)
                    with p1:
                        wf_ma_s = st.slider("短期均线", 3, 20, 5, key="wf_ma_short")
                        wf_ma_m = st.slider("中期均线", 10, 50, 20, key="wf_ma_mid")
                    with p2:
                        wf_ma_l = st.slider("长期均线", 30, 120, 60, key="wf_ma_long")
                        wf_vol_r = st.slider("放量倍数", 1.0, 3.0, 1.5, 0.1, key="wf_vol_ratio")
                else:
                    st.caption("急跌企稳 + 放量反弹捕捉")
                    p1, p2 = st.columns(2)
                    with p1:
                        wf_lookback = st.slider("回看天数", 5, 20, 10, key="wf_lookback")
                        wf_drop = st.slider("跌幅阈值", 0.10, 0.30, 0.15, 0.01, key="wf_drop")
                    with p2:
                        wf_rebound = st.slider("反弹幅度", 0.01, 0.05, 0.01, 0.005, key="wf_rebound")
                        wf_v_vol = st.slider("放量倍数", 1.0, 2.5, 1.3, 0.1, key="wf_v_vol5")
            elif wf_strategy_type == "✏️ 自定义":
                wf_user_code = st.text_area("策略代码", value=st.session_state.get("custom_strategy_code", ""), height=180, key="wf_custom_code")
            elif wf_strategy_type == "🤖 AI":
                code = st.session_state.get("custom_strategy_code", "")
                if code:
                    st.success(f"✅ AI策略已就绪")
                    with st.expander("📝 查看代码"):
                        st.code(code, language="python")
                else:
                    st.warning("⚠️ 请先到「策略工坊」AI生成策略")

        with right:
            st.markdown("### 💼 交易设置")
            st.info("💡 股票、日期、资金在左侧边栏配置")

        with st.expander("🛡️ 风险控制参数", expanded=False):
            col_t1, col_t2 = st.columns(2)
            with col_t1:
                wf_sl = st.slider("硬止损", 0.03, 0.20, 0.08, 0.01, key="wf_sl")
                wf_tp = st.slider("止盈目标", 0.10, 0.50, 0.20, 0.05, key="wf_tp")
                wf_pos = st.slider("建仓比例", 0.10, 0.99, 0.30, 0.05, key="wf_pos")
            with col_t2:
                wf_ts = st.slider("移动止损回撤", 0.00, 0.15, 0.05, 0.01, key="wf_ts")
                wf_atr = st.checkbox("ATR动态止损", value=False, key="wf_atr")
                wf_atr_m = 2.0
                if wf_atr:
                    wf_atr_m = st.slider("ATR倍数", 1.0, 4.0, 2.0, 0.5, key="wf_atr_m")
                wf_sc = st.slider("信号确认天数", 1, 5, 1, key="wf_sc")
            wf_slip = st.number_input("滑点", value=0.001, format="%.3f", key="wf_slip")
            wf_duty = st.number_input("印花税（卖出）", value=0.0005, format="%.4f", key="wf_duty")

        st.markdown("---")
        if st.button("🚀 开始回测", type="primary", key="wf_run_bt", use_container_width=True):
            with st.spinner("获取数据..."):
                df = fetch_stock_data(symbol, start_str, end_str)
            if df is None or df.empty:
                st.error("数据获取失败")
            else:
                try:
                    if wf_strategy_type == "📈 内置":
                        if wf_builtin_sub == "📈 右侧趋势":
                            df_signal = generate_right_signal(df, wf_ma_s, wf_ma_m, wf_ma_l, wf_vol_r)
                        else:
                            df_signal = generate_v_shape_signal(df, wf_lookback, wf_drop, wf_rebound, wf_v_vol)
                    else:
                        code_to_use = wf_user_code if wf_strategy_type == "✏️ 自定义" else st.session_state.get("custom_strategy_code", "")
                        if not code_to_use:
                            st.error("请先准备策略代码")
                            st.stop()
                        local_ns = {}
                        exec(code_to_use, {}, local_ns)
                        df_signal = local_ns['generate_signal'](df)

                    max_hold = 20 if (wf_strategy_type == "📈 内置" and wf_builtin_sub == "🔍 V型反转") else 999
                    trades, equity, metrics = run_backtest(
                        df_signal, initial_cash=wf_cash,
                        stop_loss=wf_sl, take_profit=wf_tp, trailing_stop=wf_ts,
                        use_atr_stop=wf_atr, atr_multiple=wf_atr_m,
                        stamp_duty=wf_duty, signal_confirm=wf_sc,
                        slippage=wf_slip, position_pct=wf_pos, max_hold_days=max_hold
                    )

                    if 'error' in metrics:
                        st.error(f"回测失败: {metrics['error']}")
                    else:
                        st.success("✅ 回测完成！")
                        c1, c2, c3, c4, c5 = st.columns(5)
                        c1.metric("📈 总收益", f"{metrics['total_return']:.2f}%")
                        c2.metric("📊 夏普", f"{metrics['sharpe_ratio']:.3f}")
                        c3.metric("📉 最大回撤", f"{metrics['max_drawdown']:.2f}%")
                        c4.metric("🎯 胜率", f"{metrics['win_rate']:.2f}%")
                        c5.metric("🔄 交易次数", metrics['total_trades'])
                        c6, c7, c8, c9, c10 = st.columns(5)
                        c6.metric("🛡️ Calmar", f"{metrics['calmar_ratio']:.3f}")
                        c7.metric("📐 Sortino", f"{metrics['sortino_ratio']:.3f}")
                        c8.metric("💰 盈亏因子", f"{metrics['profit_factor']:.3f}")
                        c9.metric("📋 盈亏比", f"{metrics['profit_loss_ratio']:.3f}")
                        c10.metric("💵 最终权益", f"{metrics['final_equity']:,.0f}")
                        st.components.v1.html(plot_equity(equity, wf_cash), height=400, scrolling=False)
                        plot_kline_with_signals(df_signal, trades)
                        st.plotly_chart(plot_drawdown(equity), use_container_width=True)
                        with st.expander("📋 交易明细"):
                            st.dataframe(trades, use_container_width=True)
                        sharpe = metrics.get('sharpe_ratio', 0)
                        if sharpe > 1.0:
                            st.success("✅ 夏普 > 1.0，策略表现优秀，建议继续！")
                        elif sharpe > 0:
                            st.info("ℹ️ 夏普为正但偏低，可以考虑优化参数后继续。")
                        else:
                            st.warning("⚠️ 夏普为负，策略可能无效，请回到步骤1改进策略。")
                except Exception as e:
                    st.error(f"执行出错: {e}")

    # ============ 步骤 2：参数优化 ============
    elif current == 2:
        st.subheader("🔧 步骤 3/8：参数优化")
        is_builtin = "内置" in strategy_label
        custom_code = st.session_state.get("custom_strategy_code", "")
        auto_params = parse_strategy_params(custom_code) if custom_code else {}
        wrapped_func = make_strategy_wrapper(strategy_func, custom_code) if (not is_builtin and custom_code) else strategy_func

        if is_builtin:
            col_a, col_b = st.columns(2)
            with col_a:
                ma_vals = st.multiselect("短期均线", [3, 5, 7, 10, 15], default=[5, 10], key="wf_ma")
            with col_b:
                vol_vals = st.multiselect("放量倍数", [1.0, 1.3, 1.5, 1.8, 2.0], default=[1.3, 1.5], key="wf_vol")
            if st.button("🚀 运行网格搜索", type="primary", key="wf_run_gs"):
                with st.spinner("搜索中..."):
                    df = fetch_stock_data(symbol, start_str, end_str)
                    if df is not None and not df.empty:
                        param_grid = {'ma_short': ma_vals, 'vol_ratio': vol_vals}
                        result = grid_search(df, strategy_func, param_grid, run_backtest)
                        if not result.empty:
                            st.dataframe(_translate_columns(result.head(10)), use_container_width=True)
                            best = result.iloc[0]
                            st.success(f"🏆 最优：短期均线={best['ma_short']}, 放量倍数={best['vol_ratio']}, 夏普={best.get('sharpe_ratio', 0):.3f}")

        elif auto_params:
            st.success(f"✅ 识别到 {len(auto_params)} 个参数：{', '.join(auto_params.keys())}")
            selected_params = {}
            cols_param = st.columns(min(len(auto_params), 4))
            for i, (pname, pvalues) in enumerate(auto_params.items()):
                with cols_param[i % len(cols_param)]:
                    sel = st.multiselect(pname, pvalues, default=pvalues[:3] if len(pvalues) > 3 else pvalues, key=f"wf_ap_{pname}")
                    if sel:
                        selected_params[pname] = sel
            if selected_params and st.button("🚀 运行网格搜索", type="primary", key="wf_run_gs_custom"):
                with st.spinner("搜索中..."):
                    df = fetch_stock_data(symbol, start_str, end_str)
                    if df is not None and not df.empty:
                        result = grid_search(df, wrapped_func, selected_params, run_backtest)
                        if not result.empty:
                            st.dataframe(_translate_columns(result.head(10)), use_container_width=True)
                            best = result.iloc[0]
                            st.success(f"🏆 最优参数组合，夏普={best.get('sharpe_ratio', 0):.3f}")
        else:
            st.warning("⚠️ 当前策略未声明 `# @PARAMS:` 注释，无法自动优化参数。")
            st.markdown("""
            **如何让 AI 策略支持参数优化：**
            1. 回到「策略工坊」，重新生成策略
            2. 或在策略代码顶部加一行：
            ```python
            # @PARAMS: ma_short=3,15,2; ma_long=10,60,5
            def generate_signal(df, **kwargs):
                ma_short = kwargs.get('ma_short', 5)
                ...
            ```
            """)

    # ============ 步骤 3：过拟合检测 ============
    elif current == 3:
        st.subheader("🔬 步骤 4/8：过拟合检测")
        if st.button("🔬 运行检测", type="primary", key="wf_run_of"):
            with st.spinner("获取数据..."):
                df = fetch_stock_data(symbol, start_str, end_str)
            if df is None or df.empty:
                st.error("数据获取失败")
            else:
                split = train_test_split_test(df, strategy_func, run_backtest, **strategy_params)
                col_a, col_b = st.columns(2)
                is_m = split.get('样本内(IS)', {})
                oos_m = split.get('样本外(OOS)', {})
                if 'error' not in is_m:
                    col_a.metric("IS 夏普", f"{is_m.get('sharpe_ratio', 0):.3f}")
                    col_a.metric("IS 收益", f"{is_m.get('total_return', 0):.2f}%")
                if 'error' not in oos_m:
                    col_b.metric("OOS 夏普", f"{oos_m.get('sharpe_ratio', 0):.3f}")
                    col_b.metric("OOS 收益", f"{oos_m.get('total_return', 0):.2f}%")
                cscv = cscv_analysis(df, strategy_func, run_backtest, n_splits=8, **strategy_params)
                st.metric("CSCV 稳定性", cscv['stability_score'], help=">1.5=稳定, <0.5=极不稳定")
                st.info(cscv['warning'])
                stability = cscv.get('stability_score', 0)
                oos_sharpe = float(oos_m.get('sharpe_ratio', 0)) if 'error' not in oos_m else 0
                if stability > 1.0 and oos_sharpe > 0:
                    st.success("✅ 策略通过过拟合检测！")
                else:
                    st.warning("⚠️ 策略可能过拟合，建议回到步骤1优化策略。")

    # ============ 步骤 4：因子研究 ============
    elif current == 4:
        st.subheader("🧬 步骤 5/8：因子有效性研究")
        if st.button("🧬 开始分析", type="primary", key="wf_run_factor"):
            with st.spinner("计算因子..."):
                df = fetch_stock_data(symbol, start_str, end_str)
                if df is not None and not df.empty:
                    df_factors = compute_all_factors(df)
                    ic_result = compute_ic_analysis(df_factors)
                    if not ic_result['ic_summary'].empty:
                        st.subheader("📊 IC 排名（Top 5）")
                        st.dataframe(ic_result['ic_summary'].head(5), use_container_width=True)
                        st.caption("IC_IR > 0.3 为有效因子")

    # ============ 步骤 5：批量验证 ============
    elif current == 5:
        st.subheader("📦 步骤 6/8：多股票批量验证")
        symbols_input = st.text_area("测试股票（每行一个）", value="600160\n000001\n600519", height=80, key="wf_batch")
        if st.button("📊 批量回测", type="primary", key="wf_run_batch"):
            symbols = [s.strip() for s in symbols_input.split('\n') if s.strip()]
            with st.spinner(f"回测 {len(symbols)} 只..."):
                result = batch_backtest(symbols, fetch_stock_data, strategy_func,
                                       run_backtest, start_str, end_str)
            if not result.empty:
                st.dataframe(result, use_container_width=True)
                success = result[result['状态'] == '成功']
                st.success(f"✅ {len(success)}/{len(symbols)} 只成功")

    # ============ 步骤 6：风险评估 ============
    elif current == 6:
        st.subheader("🛡️ 步骤 7/8：风险评估")
        if st.button("🛡️ 运行分析", type="primary", key="wf_run_risk"):
            with st.spinner("分析中..."):
                df = fetch_stock_data(symbol, start_str, end_str)
                if df is not None and not df.empty:
                    returns = df['close'].pct_change().dropna()
                    var_h = compute_var(returns, 0.95, 'historical')
                    stress = stress_test(returns)
                    c1, c2 = st.columns(2)
                    c1.metric("📉 VaR(95%)", f"{var_h['VaR']}%", help=var_h['VaR_金额'])
                    c2.metric("📉 CVaR(95%)", f"{var_h['CVaR']}%")
                    st.subheader("🌪️ 压力测试")
                    st.dataframe(stress, use_container_width=True)

    # ============ 步骤 7：实盘准备 ============
    elif current == 7:
        st.subheader("📡 步骤 8/8：实盘信号准备")
        symbols_input = st.text_area("监控股票", value="600160\n000001\n600519", height=80, key="wf_live")
        if st.button("🔍 扫描信号", type="primary", key="wf_run_scan"):
            symbols = [s.strip() for s in symbols_input.split('\n') if s.strip()]
            with st.spinner(f"扫描 {len(symbols)} 只..."):
                signals = scan_signals(symbols, fetch_stock_data, strategy_func, **strategy_params)
            if not signals.empty:
                st.dataframe(signals, use_container_width=True)
                buys = signals[signals['信号'].str.contains('买入')]
                if not buys.empty:
                    st.success(f"🟢 {len(buys)} 只出现买入信号！")
                else:
                    st.info("当前无买入信号")
        st.markdown("---")
        st.success("🎉 恭喜！你已完成完整的策略开发工作流。\n\n"
                   "如果策略通过了所有检测（回测盈利 + 过拟合检测通过 + 风险可控），"
                   "可以进入「📡 实盘信号」页面进行模拟交易。")

    # ---- 底部导航 ----
    st.markdown("---")
    col_prev, col_blank, col_next = st.columns([1, 3, 1])
    with col_prev:
        if current > 0:
            if st.button("⬅️ 上一步", use_container_width=True, key="wf_prev"):
                st.session_state["workflow_step"] = current - 1
                st.rerun()
    with col_next:
        if current < total - 1:
            if st.button("下一步 ➡️", type="primary", use_container_width=True, key="wf_next"):
                st.session_state["workflow_step"] = current + 1
                st.rerun()


# ============================================================
# 14. 顶部导航栏与页面调度
# ============================================================
if "import os" not in dir():
    import os  # for live_page paper trading

if "_current_page" not in st.session_state:
    st.session_state["_current_page"] = "workflow"

# 主工具行 (2列)
nav_col1, nav_col2 = st.columns(2)
with nav_col1:
    btn_type_wf = "primary" if st.session_state["_current_page"] == "workflow" else "secondary"
    if st.button("🚀 工作流", use_container_width=True, type=btn_type_wf, key="nav_btn_workflow"):
        st.session_state["_current_page"] = "workflow"
        st.rerun()
with nav_col2:
    btn_type_ws = "primary" if st.session_state["_current_page"] == "workshop" else "secondary"
    if st.button("🤖 策略工坊", use_container_width=True, type=btn_type_ws, key="nav_btn_workshop"):
        st.session_state["_current_page"] = "workshop"
        st.rerun()

# 高级工具行 (6列)
nav_cols = st.columns(6)
pages = [
    ("factor", "🧬 因子分析"),
    ("optimizer", "🔧 参数优化"),
    ("portfolio", "📦 组合管理"),
    ("risk", "🛡️ 风险分析"),
    ("overfit", "🔬 过拟合检测"),
    ("live", "📡 实盘信号"),
]
for i, (page_id, page_label) in enumerate(pages):
    with nav_cols[i]:
        btn_type = "primary" if st.session_state["_current_page"] == page_id else "secondary"
        if st.button(page_label, use_container_width=True, type=btn_type, key=f"nav_btn_{page_id}"):
            st.session_state["_current_page"] = page_id
            st.rerun()

st.markdown("---")

# 页面调度
if st.session_state["_current_page"] == "workflow":
    workflow_page()
elif st.session_state["_current_page"] == "backtest":
    backtest_page()
elif st.session_state["_current_page"] == "workshop":
    workshop_page()
elif st.session_state["_current_page"] == "factor":
    factor_page()
elif st.session_state["_current_page"] == "optimizer":
    optimizer_page()
elif st.session_state["_current_page"] == "portfolio":
    portfolio_page()
elif st.session_state["_current_page"] == "risk":
    risk_page()
elif st.session_state["_current_page"] == "overfit":
    overfit_page()
elif st.session_state["_current_page"] == "live":
    live_page()
