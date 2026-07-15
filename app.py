"""
模块：主入口 (app.py) — Streamlit 用户界面
功能：多页面导航（策略回测 + 策略工坊）、侧边栏交易控制台、策略配置与回测结果展示
依赖：
    - config.py        系统配置（SYSTEM_PROMPT）
    - deepseek_api.py  DeepSeek API 客户端（call_deepseek, extract_code, validate_strategy_code）
    - data_loader.py   数据获取层（fetch_stock_data）
    - strategies.py    内置策略信号生成（generate_right_signal, generate_v_shape_signal）
    - backtest.py      回测引擎与绩效评估（run_backtest）
    - charts.py        可视化图表（plot_equity, plot_kline_with_signals, plot_drawdown）
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
from deepseek_api import call_deepseek, extract_code, validate_strategy_code, ensure_dependencies
from data_loader import fetch_stock_data
from strategies import generate_right_signal, generate_v_shape_signal
from backtest import run_backtest
from charts import plot_equity, plot_kline_with_signals, plot_drawdown

warnings.filterwarnings('ignore')
load_dotenv()

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
                # 自动安装代码中引用的缺失库
                installed = ensure_dependencies(code)
                if installed:
                    st.info(f"📦 自动安装了缺失库: {', '.join(installed)}")

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
# 7. 顶部导航栏与页面调度
# ============================================================
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
