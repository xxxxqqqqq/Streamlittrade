"""
QuantResearch — 图表优先 + 工具条 + 可展开面板
==============================================
设计理念：
  • 图表永远是主角 — K 线图占据核心视觉区域
  • 紧凑顶栏 — 股票/日期/资金/策略只配置一次，全局复用
  • 渐进式披露 — 高级分析工具默认折叠，按需展开
  • 三视图架构 — 策略研究 | 策略工坊 | 实盘监控
"""

# ============================================================
# 0. 导入依赖
# ============================================================
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import warnings
import os
from dotenv import load_dotenv

try:
    from streamlit_ace import st_ace
    ACE_AVAILABLE = True
except ImportError:
    ACE_AVAILABLE = False

from config import SYSTEM_PROMPT
from deepseek_api import call_deepseek, extract_code, validate_strategy_code, check_missing_imports
from data_loader import fetch_stock_data
from strategies import generate_right_signal, generate_v_shape_signal
from backtest import run_backtest
from charts import plot_equity, plot_kline_with_signals, plot_drawdown
from factor_analysis import (
    compute_all_factors, compute_ic_analysis, layer_backtest,
    factor_correlation, translate_factor
)
from optimizer import (
    grid_search, walk_forward_analysis, parameter_sensitivity,
    parse_strategy_params, make_strategy_wrapper
)
from portfolio import (
    batch_backtest, equal_weight, risk_parity, max_sharpe,
    kelly_allocation, compute_portfolio_metrics
)
from risk_model import (
    compute_var, stress_test, drawdown_analysis, monte_carlo_simulation
)
from overfit_check import (
    train_test_split_test, cscv_analysis, compute_pbo, white_noise_test
)
from live_signal import scan_signals, log_signal, get_signal_history, paper_trade

warnings.filterwarnings('ignore')
load_dotenv()


# ============================================================
# 1. 全局状态初始化
# ============================================================

def init_state():
    if "active_strategy_name" not in st.session_state:
        st.session_state.active_strategy_name = "内置-右侧趋势"
    if "custom_strategy_code" not in st.session_state:
        st.session_state.custom_strategy_code = ""
    if "deepseek_api_key" not in st.session_state:
        st.session_state.deepseek_api_key = ""
    if "deepseek_messages" not in st.session_state:
        st.session_state.deepseek_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if "generated_code" not in st.session_state:
        st.session_state.generated_code = ""
    # 共享数据缓存
    if "shared_data" not in st.session_state:
        st.session_state.shared_data = None
    if "shared_signal_df" not in st.session_state:
        st.session_state.shared_signal_df = None
    if "shared_trades" not in st.session_state:
        st.session_state.shared_trades = None
    if "shared_equity" not in st.session_state:
        st.session_state.shared_equity = None
    if "shared_metrics" not in st.session_state:
        st.session_state.shared_metrics = None
    if "shared_symbol" not in st.session_state:
        st.session_state.shared_symbol = "600160"
    if "shared_start" not in st.session_state:
        st.session_state.shared_start = "20200101"
    if "shared_end" not in st.session_state:
        st.session_state.shared_end = datetime.now().strftime("%Y%m%d")
    if "shared_cash" not in st.session_state:
        st.session_state.shared_cash = 100000
    # 交易参数
    if "trade_stop_loss" not in st.session_state:
        st.session_state.trade_stop_loss = 0.08
    if "trade_take_profit" not in st.session_state:
        st.session_state.trade_take_profit = 0.20
    if "trade_trailing_stop" not in st.session_state:
        st.session_state.trade_trailing_stop = 0.05
    if "trade_position_pct" not in st.session_state:
        st.session_state.trade_position_pct = 0.30
    if "trade_slippage" not in st.session_state:
        st.session_state.trade_slippage = 0.001
    if "trade_stamp_duty" not in st.session_state:
        st.session_state.trade_stamp_duty = 0.0005
    if "trade_signal_confirm" not in st.session_state:
        st.session_state.trade_signal_confirm = 1


def get_strategy():
    name = st.session_state.get("active_strategy_name", "内置-右侧趋势")
    code = st.session_state.get("custom_strategy_code", "")

    if "右侧趋势" in name:
        return generate_right_signal, {
            'ma_short': st.session_state.get("sp_ma_s", 5),
            'ma_mid': st.session_state.get("sp_ma_m", 20),
            'ma_long': st.session_state.get("sp_ma_l", 60),
            'vol_ratio': st.session_state.get("sp_vr", 1.5),
        }, name
    if "V型反转" in name or "v_shape" in name.lower():
        return generate_v_shape_signal, {
            'lookback': st.session_state.get("sp_v_lb", 10),
            'drop_threshold': st.session_state.get("sp_v_dt", 0.15),
            'rebound_threshold': st.session_state.get("sp_v_rb", 0.01),
            'vol_ratio': st.session_state.get("sp_v_vr", 1.3),
        }, name

    if code:
        try:
            local_ns = {}
            exec(code, {}, local_ns)
            if 'generate_signal' in local_ns:
                raw_func = local_ns['generate_signal']
                import inspect as _inspect
                sig = _inspect.signature(raw_func)
                if 'kwargs' not in str(sig) and len(sig.parameters) <= 1:
                    def _wrapped(df, **kwargs):
                        return raw_func(df)
                    return _wrapped, {}, name
                return raw_func, {}, name
        except Exception:
            pass

    return generate_right_signal, {
        'ma_short': 5, 'ma_mid': 20, 'ma_long': 60, 'vol_ratio': 1.5
    }, name


# ============================================================
# 2. 紧凑顶栏（唯一数据入口）
# ============================================================

def render_top_bar():
    c1, c2, c3, c4, c5, c6, c7 = st.columns([0.9, 1.1, 1.1, 0.8, 1.4, 0.8, 0.8])

    with c1:
        symbol = st.text_input(
            "股票", value=st.session_state.shared_symbol, placeholder="600160",
            label_visibility="collapsed", key="tb_symbol"
        )
    with c2:
        s_dt = datetime.strptime(st.session_state.shared_start, "%Y%m%d")
        start = st.date_input("开始", value=s_dt, key="tb_start", label_visibility="collapsed")
    with c3:
        e_dt = datetime.strptime(st.session_state.shared_end, "%Y%m%d")
        end = st.date_input("结束", value=e_dt, key="tb_end", label_visibility="collapsed")
    with c4:
        cash = st.number_input("资金", value=st.session_state.shared_cash, step=10000,
                               format="%d", key="tb_cash", label_visibility="collapsed")
    with c5:
        strat_options = ["内置-右侧趋势", "内置-V型反转", "自定义策略", "AI生成策略"]
        current = st.session_state.active_strategy_name
        idx = strat_options.index(current) if current in strat_options else 0
        strat = st.selectbox(
            "策略", strat_options, index=idx,
            key="tb_strategy", label_visibility="collapsed"
        )
    with c6:
        load_btn = st.button("📥 加载数据", use_container_width=True, key="tb_load")
    with c7:
        run_btn = st.button("▶ 运行回测", use_container_width=True, type="primary", key="tb_run")

    # 同步状态
    st.session_state.shared_symbol = symbol
    st.session_state.shared_start = start.strftime("%Y%m%d")
    st.session_state.shared_end = end.strftime("%Y%m%d")
    st.session_state.shared_cash = cash
    st.session_state.active_strategy_name = strat

    # 加载数据
    if load_btn or run_btn:
        with st.spinner(f"获取 {symbol} 数据..."):
            df = fetch_stock_data(symbol, st.session_state.shared_start, st.session_state.shared_end)
            if df is None or df.empty:
                st.error(f"无法获取 {symbol} 数据")
                st.stop()
            st.session_state.shared_data = df
            strategy_func, strategy_params, _ = get_strategy()
            st.session_state.shared_signal_df = strategy_func(df, **strategy_params)

    # 运行回测
    if run_btn and st.session_state.shared_data is not None:
        _do_backtest()

    return run_btn


def _do_backtest():
    strategy_func, strategy_params, label = get_strategy()
    df = st.session_state.shared_data
    st.session_state.shared_signal_df = strategy_func(df, **strategy_params)

    with st.spinner("回测中..."):
        trades, equity, metrics = run_backtest(
            st.session_state.shared_signal_df,
            initial_cash=st.session_state.shared_cash,
            stop_loss=st.session_state.trade_stop_loss,
            take_profit=st.session_state.trade_take_profit,
            trailing_stop=st.session_state.trade_trailing_stop,
            position_pct=st.session_state.trade_position_pct,
            slippage=st.session_state.trade_slippage,
            stamp_duty=st.session_state.trade_stamp_duty,
            signal_confirm=st.session_state.trade_signal_confirm,
        )

    if trades is None or 'error' in metrics:
        st.error(f"回测失败: {metrics.get('error', '')}")
        st.session_state.shared_metrics = None
        return

    st.session_state.shared_trades = trades
    st.session_state.shared_equity = equity
    st.session_state.shared_metrics = metrics


# ============================================================
# 3. 图表区域（主角）
# ============================================================

def render_charts():
    if st.session_state.shared_signal_df is None:
        st.info("👆 请先点击「📥 加载数据」或「▶ 运行回测」")
        return

    sub1, sub2 = st.tabs(["📈 K线图 + 买卖信号", "📊 净值曲线 + 回撤"])

    with sub1:
        plot_kline_with_signals(
            st.session_state.shared_signal_df,
            st.session_state.shared_trades
        )

    with sub2:
        eq = st.session_state.shared_equity
        if eq is not None:
            st.components.v1.html(
                plot_equity(eq, st.session_state.shared_cash),
                height=380, scrolling=False
            )
            st.plotly_chart(plot_drawdown(eq), use_container_width=True)
        else:
            st.info("请先运行回测")


# ============================================================
# 4. 指标卡片
# ============================================================

def render_metrics():
    m = st.session_state.shared_metrics
    if m is None:
        return

    # 第一行：5 个核心指标
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("📈 总收益", f"{m['total_return']:.2f}%")
    with c2:
        st.metric("📊 夏普比率", f"{m['sharpe_ratio']:.3f}")
    with c3:
        st.metric("📉 最大回撤", f"{m['max_drawdown']:.2f}%")
    with c4:
        st.metric("🎯 胜率", f"{m['win_rate']:.2f}%")
    with c5:
        st.metric("🛡️ Calmar", f"{m['calmar_ratio']:.3f}")

    # 第二行：5 个补充指标
    c6, c7, c8, c9, c10 = st.columns(5)
    with c6:
        st.metric("💰 盈亏因子", f"{m['profit_factor']:.3f}")
    with c7:
        st.metric("📐 Sortino", f"{m['sortino_ratio']:.3f}")
    with c8:
        st.metric("📋 盈亏比", f"{m['profit_loss_ratio']:.3f}")
    with c9:
        st.metric("🔄 交易次数", str(m['total_trades']))
    with c10:
        st.metric("💵 最终权益", f"{m['final_equity']:,.0f}")


# ============================================================
# 5. 可展开分析面板
# ============================================================

def render_factor_panel():
    if st.session_state.shared_data is None:
        st.info("请先加载数据")
        return
    if st.button("🧬 计算因子", key="pf_run"):
        with st.spinner("计算中..."):
            df_f = compute_all_factors(st.session_state.shared_data)
            ic_r = compute_ic_analysis(df_f)
            st.session_state._factor_df = df_f
            st.session_state._factor_ic = ic_r
    if hasattr(st.session_state, '_factor_ic') and st.session_state._factor_ic is not None:
        ic = st.session_state._factor_ic['ic_summary']
        st.dataframe(ic.head(8), use_container_width=True)
        st.caption("IC_IR > 0.3 有效，> 0.5 优秀")

        if not ic.empty:
            top = st.selectbox("分层回测因子", ic['因子'].tolist()[:5], key="pf_layer")
            if top:
                fname = top.split(' / ')[0]
                lr = layer_backtest(st.session_state._factor_df, fname)
                if lr is not None:
                    st.dataframe(lr, use_container_width=True)

        corr = factor_correlation(st.session_state._factor_df)
        if not corr.empty:
            st.subheader("因子相关性")
            st.dataframe(corr.style.background_gradient(cmap='RdYlGn', axis=None),
                         use_container_width=True)


def render_optimizer_panel():
    if st.session_state.shared_data is None:
        st.info("请先加载数据")
        return

    sf, sp, sl = get_strategy()
    is_b = "内置" in st.session_state.get("active_strategy_name", "内置")
    code = st.session_state.get("custom_strategy_code", "")
    ap = parse_strategy_params(code) if code else {}

    sub1, sub2, sub3 = st.tabs(["🔍 网格搜索", "🔄 前向推进", "📐 敏感度"])

    with sub1:
        if is_b:
            name = st.session_state.get("active_strategy_name", "")
            if "右侧趋势" in name:
                c1, c2, c3 = st.columns(3)
                with c1:
                    ma_v = st.multiselect("短期均线", [3,5,7,10,15], default=[5,10], key="gs_ma")
                with c2:
                    vr_v = st.multiselect("放量倍数", [1.0,1.3,1.5,1.8,2.0], default=[1.3,1.5], key="gs_vol")
                with c3:
                    mopt = st.selectbox("目标", ['sharpe_ratio','total_return','calmar_ratio'],
                        format_func=lambda x: {'sharpe_ratio':'夏普','total_return':'总收益','calmar_ratio':'Calmar'}[x])
                if st.button("🚀 搜索", key="gs_run"):
                    with st.spinner("搜索中..."):
                        r = grid_search(st.session_state.shared_data, sf,
                                        {'ma_short': ma_v, 'vol_ratio': vr_v}, run_backtest, mopt)
                        if not r.empty:
                            st.dataframe(r.head(10), use_container_width=True)
                            b = r.iloc[0]
                            st.success(f"🏆 最优: ma_short={b['ma_short']}, vol_ratio={b['vol_ratio']}, Sharpe={b.get('sharpe_ratio',0):.3f}")
            elif "V型反转" in name or "v_shape" in name.lower():
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    lb_v = st.multiselect("回看天数", [5,7,10,15,20], default=[10,15], key="gs_lb")
                with c2:
                    dt_v = st.multiselect("跌幅阈值", [0.10,0.15,0.20,0.25], default=[0.15,0.20], key="gs_dt")
                with c3:
                    rb_v = st.multiselect("反弹幅度", [0.01,0.02,0.03,0.05], default=[0.01,0.02], key="gs_rb")
                with c4:
                    mopt = st.selectbox("目标", ['sharpe_ratio','total_return','calmar_ratio'],
                        format_func=lambda x: {'sharpe_ratio':'夏普','total_return':'总收益','calmar_ratio':'Calmar'}[x])
                if st.button("🚀 搜索", key="gs_run"):
                    with st.spinner("搜索中..."):
                        param_grid = {'lookback': lb_v, 'drop_threshold': dt_v, 'rebound_threshold': rb_v}
                        r = grid_search(st.session_state.shared_data, sf, param_grid, run_backtest, mopt)
                        if not r.empty:
                            st.dataframe(r.head(10), use_container_width=True)
                            st.success("✅ 搜索完成")
        elif ap:
            st.success(f"识别到 {len(ap)} 个参数: {', '.join(ap.keys())}")
            sel = {}
            ac = st.columns(min(len(ap), 4))
            for i, (pn, pv) in enumerate(ap.items()):
                with ac[i % len(ac)]:
                    s = st.multiselect(pn, pv, default=pv[:3] if len(pv)>3 else pv, key=f"gs_ap_{pn}")
                    if s:
                        sel[pn] = s
            if sel and st.button("🚀 搜索", key="gs_auto"):
                with st.spinner("搜索中..."):
                    wf = make_strategy_wrapper(sf, code)
                    r = grid_search(st.session_state.shared_data, wf, sel, run_backtest)
                    if not r.empty:
                        st.dataframe(r.head(10), use_container_width=True)
        else:
            st.warning("策略未声明 # @PARAMS: 注释")

    with sub2:
        tm = st.slider("训练(月)", 6, 24, 12, key="wfa_t")
        em = st.slider("测试(月)", 1, 6, 3, key="wfa_e")
        if st.button("🔄 WFA", key="wfa_run"):
            with st.spinner("分析中..."):
                # 自适应参数网格
                name = st.session_state.get("active_strategy_name", "")
                if "V型反转" in name or "v_shape" in name.lower():
                    wfa_grid = {'lookback': [10, 15], 'drop_threshold': [0.15, 0.20]}
                else:
                    wfa_grid = {'ma_short': [5, 10], 'vol_ratio': [1.3, 1.5]}
                wfa = walk_forward_analysis(st.session_state.shared_data, sf, run_backtest,
                                            wfa_grid, train_months=tm, test_months=em)
                if not wfa['wfa_results'].empty:
                    c1,c2,c3=st.columns(3)
                    c1.metric("IS夏普", wfa['is_sharpe'])
                    c2.metric("OOS夏普", wfa['oos_sharpe'])
                    c3.metric("鲁棒性", f"{wfa['robustness']:.0%}")
                    st.dataframe(wfa['wfa_results'], use_container_width=True)

    with sub3:
        name = st.session_state.get("active_strategy_name", "")
        if "V型反转" in name or "v_shape" in name.lower():
            bl = st.number_input("基准回看天数", 5, 20, 10, key="sens_lb")
            if st.button("📐 分析", key="sens_run"):
                with st.spinner("计算中..."):
                    s = parameter_sensitivity(st.session_state.shared_data, sf, run_backtest,
                                              {'lookback': bl, 'drop_threshold': 0.15},
                                              'lookback', (bl-3, bl+5))
                    if not s.empty:
                        st.dataframe(s, use_container_width=True)
                        st.line_chart(s.set_index('参数值')['夏普比率'])
        else:
            bm = st.number_input("基准短期均线", 3, 20, 5, key="sens_ma")
            if st.button("📐 分析", key="sens_run"):
                with st.spinner("计算中..."):
                    s = parameter_sensitivity(st.session_state.shared_data, sf, run_backtest,
                                              {'ma_short': bm, 'vol_ratio': 1.5}, 'ma_short', (bm-3, bm+5))
                    if not s.empty:
                        st.dataframe(s, use_container_width=True)
                        st.line_chart(s.set_index('参数值')['夏普比率'])


def render_overfit_panel():
    if st.session_state.shared_data is None:
        st.info("请先加载数据")
        return

    sf, sp, _ = get_strategy()

    if st.button("🔬 运行过拟合检测", key="of_run"):
        with st.spinner("检测中..."):
            split = train_test_split_test(st.session_state.shared_data, sf, run_backtest, **sp)
            is_m = split.get('样本内(IS)', {})
            oos_m = split.get('样本外(OOS)', {})

            c1, c2 = st.columns(2)
            if 'error' not in is_m:
                c1.metric("IS 夏普", f"{is_m.get('sharpe_ratio',0):.3f}")
                c1.metric("IS 收益", f"{is_m.get('total_return',0):.2f}%")
                c1.metric("IS 回撤", f"{is_m.get('max_drawdown',0):.2f}%")
            if 'error' not in oos_m:
                c2.metric("OOS 夏普", f"{oos_m.get('sharpe_ratio',0):.3f}")
                c2.metric("OOS 收益", f"{oos_m.get('total_return',0):.2f}%")
                c2.metric("OOS 回撤", f"{oos_m.get('max_drawdown',0):.2f}%")

            cscv = cscv_analysis(st.session_state.shared_data, sf, run_backtest, n_splits=8, **sp)
            st.metric("CSCV 稳定性", cscv['stability_score'])
            st.info(cscv['warning'])
            if not cscv['segments'].empty:
                st.line_chart(cscv['segments'].set_index('分段')['夏普比率'])

            rets = st.session_state.shared_data['close'].pct_change().dropna()
            wn = white_noise_test(rets, [1, 5, 10, 20])
            st.subheader("白噪声检验")
            st.dataframe(wn, use_container_width=True)
            st.caption("p < 0.05 = 可预测")

            oos_s = float(oos_m.get('sharpe_ratio',0)) if 'error' not in oos_m else 0
            if cscv['stability_score'] > 1.0 and oos_s > 0:
                st.success("✅ 策略通过过拟合检测")
            else:
                st.warning("⚠️ 可能过拟合，建议优化策略")


def render_risk_panel():
    if st.session_state.shared_data is None:
        st.info("请先加载数据")
        return

    if st.button("🛡️ 运行风险分析", key="risk_run"):
        with st.spinner("分析中..."):
            rets = st.session_state.shared_data['close'].pct_change().dropna()

            c1, c2, c3 = st.columns(3)
            with c1:
                vh = compute_var(rets, 0.95, 'historical')
                st.metric("VaR(95%) 历史", f"{vh['VaR']}%", help=vh['VaR_金额'])
            with c2:
                vp = compute_var(rets, 0.95, 'parametric')
                st.metric("VaR(95%) 参数", f"{vp['VaR']}%")
            with c3:
                vc = compute_var(rets, 0.95, 'cornish_fisher')
                st.metric("VaR(95%) CF", f"{vc['VaR']}%")

            stress = stress_test(rets)
            st.subheader("压力测试")
            st.dataframe(stress, use_container_width=True)

            st.subheader("蒙特卡洛模拟 (252天)")
            paths = monte_carlo_simulation(rets, n_simulations=300, horizon_days=252)
            st.line_chart(paths.iloc[:, :30])
            st.metric("中位数终值", f"{paths.iloc[-1].median():,.0f} 元")
            st.metric("5%最差", f"{paths.iloc[-1].quantile(0.05):,.0f} 元")


def render_portfolio_panel():
    if st.session_state.shared_data is None:
        st.info("请先加载数据")
        return

    sf, sp, _ = get_strategy()
    syms = st.text_area("股票池(每行一个)", "600160\n000001\n600519", height=80, key="pf_syms")
    if st.button("📊 批量回测", key="pf_run_btn"):
        symbols = [s.strip() for s in syms.split('\n') if s.strip()]
        with st.spinner(f"回测 {len(symbols)} 只..."):
            r = batch_backtest(symbols, fetch_stock_data, sf, run_backtest,
                              st.session_state.shared_start, st.session_state.shared_end)
        if not r.empty:
            st.dataframe(r, use_container_width=True)
            ok = r[r['状态'] == '成功']
            if not ok.empty:
                st.success(f"✅ {len(ok)}/{len(symbols)} 成功")


def render_export_panel():
    if st.session_state.shared_trades is None:
        st.info("请先运行回测")
        return
    c1, c2 = st.columns(2)
    with c1:
        csv = st.session_state.shared_trades.to_csv(index=False)
        st.download_button("📥 交易明细 CSV", data=csv,
                          file_name="trades.csv", mime="text/csv", use_container_width=True)
    with c2:
        if st.session_state.shared_metrics:
            st.download_button("📥 绩效指标 CSV",
                              data=pd.DataFrame([st.session_state.shared_metrics]).to_csv(index=False),
                              file_name="metrics.csv", mime="text/csv", use_container_width=True)


# ============================================================
# 6. 策略研究主视图
# ============================================================

def research_tab():
    render_top_bar()

    # 指标卡片放在 K 线图上方
    render_metrics()

    # K 线图（主角）
    render_charts()

    # 内置策略参数
    if "内置" in st.session_state.get("active_strategy_name", "内置"):
        with st.expander("⚙️ 策略参数", expanded=False):
            name = st.session_state.active_strategy_name
            if "右侧趋势" in name:
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.slider("短期均线", 3, 20, 5, key="sp_ma_s")
                with c2:
                    st.slider("中期均线", 10, 50, 20, key="sp_ma_m")
                with c3:
                    st.slider("长期均线", 30, 120, 60, key="sp_ma_l")
                with c4:
                    st.slider("放量倍数", 1.0, 3.0, 1.5, 0.1, key="sp_vr")
            elif "V型反转" in name or "v_shape" in name.lower():
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    st.slider("回看天数", 5, 20, 10, key="sp_v_lb")
                with c2:
                    st.slider("跌幅阈值", 0.10, 0.30, 0.15, 0.01, key="sp_v_dt")
                with c3:
                    st.slider("反弹幅度", 0.01, 0.05, 0.01, 0.005, key="sp_v_rb")
                with c4:
                    st.slider("放量倍数", 1.0, 2.5, 1.3, 0.1, key="sp_v_vr")

    # 交易参数（所有策略通用）
    with st.expander("💼 交易参数", expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.session_state.trade_stop_loss = st.slider(
                "硬止损 %", 3, 20, int(st.session_state.trade_stop_loss * 100),
                key="tp_sl") / 100
        with c2:
            st.session_state.trade_take_profit = st.slider(
                "止盈目标 %", 10, 50, int(st.session_state.trade_take_profit * 100),
                key="tp_tp") / 100
        with c3:
            st.session_state.trade_trailing_stop = st.slider(
                "移动止损回撤 %", 0, 15, int(st.session_state.trade_trailing_stop * 100),
                key="tp_ts") / 100
        with c4:
            st.session_state.trade_position_pct = st.slider(
                "建仓比例 %", 10, 99, int(st.session_state.trade_position_pct * 100),
                key="tp_pp") / 100
        c5, c6, c7 = st.columns(3)
        with c5:
            st.session_state.trade_slippage = st.number_input(
                "滑点", value=st.session_state.trade_slippage, format="%.3f", key="tp_slip")
        with c6:
            st.session_state.trade_stamp_duty = st.number_input(
                "印花税(卖出)", value=st.session_state.trade_stamp_duty, format="%.4f", key="tp_duty")
        with c7:
            st.session_state.trade_signal_confirm = st.slider(
                "信号确认天数", 1, 5, st.session_state.trade_signal_confirm, key="tp_sc")

    # 交易记录（K线图下方，默认展示）
    with st.expander("📋 交易明细", expanded=True):
        if st.session_state.shared_trades is not None and not st.session_state.shared_trades.empty:
            st.dataframe(st.session_state.shared_trades, use_container_width=True, height=200)
        else:
            st.info("请先运行回测")

    # 可展开分析面板（放在 K 线图下方）
    st.caption("🔬 分析工具 — 点击展开")
    with st.expander("🧬 因子研究", expanded=False):
        render_factor_panel()
    with st.expander("🔧 参数优化", expanded=False):
        render_optimizer_panel()
    with st.expander("📦 组合管理", expanded=False):
        render_portfolio_panel()
    with st.expander("🛡️ 风险分析", expanded=False):
        render_risk_panel()
    with st.expander("🔬 过拟合检测", expanded=False):
        render_overfit_panel()
    with st.expander("📥 数据导出", expanded=False):
        render_export_panel()


# ============================================================
# 7. 策略工坊视图
# ============================================================

def workshop_tab():
    st.title("🤖 策略工坊")
    st.caption("AI 生成或手动编写策略 — 保存后回到「策略研究」直接回测")

    # API Key
    if not st.session_state.get("deepseek_api_key"):
        st.warning("⚠️ 使用 AI 对话需配置 DeepSeek API Key")
        with st.expander("🔑 设置 API Key"):
            key = st.text_input("API Key", type="password", placeholder="sk-...", key="ws_key")
            if st.button("💾 保存", key="ws_save_key"):
                if key.startswith("sk-"):
                    st.session_state.deepseek_api_key = key
                    st.success("✅ 已保存")
                    st.rerun()
                else:
                    st.error("请输入有效的 API Key（以 sk- 开头）")

    tab_ai, tab_manual = st.tabs(["🤖 AI 对话生成", "💻 手动编辑器"])

    with tab_ai:
        if not st.session_state.get("deepseek_api_key"):
            st.info("请先在上方配置 API Key")
        else:
            for msg in st.session_state.deepseek_messages:
                if msg["role"] == "system":
                    continue
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            if prompt := st.chat_input("用自然语言描述交易策略..."):
                st.session_state.deepseek_messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)
                with st.chat_message("assistant"):
                    with st.spinner("⏳ DeepSeek 生成中..."):
                        api_msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + [
                            m for m in st.session_state.deepseek_messages if m["role"] != "system"
                        ]
                        resp = call_deepseek(api_msgs)
                        if resp.startswith("[ERROR]"):
                            st.error(resp)
                        else:
                            st.code(resp, language="python")
                            st.session_state.generated_code = resp
                            st.session_state.deepseek_messages.append({"role": "assistant", "content": resp})
                            code = extract_code(resp)
                            is_valid, msg = validate_strategy_code(code)
                            if is_valid:
                                st.session_state.custom_strategy_code = code
                                st.session_state.active_strategy_name = "AI生成策略"
                                st.success("✅ 策略已保存！回到「策略研究」即可回测")
                            else:
                                st.warning(f"⚠️ 需调整: {msg}")

            if st.session_state.get("generated_code"):
                st.markdown("---")
                st.subheader("📝 代码微调")
                edited = st.text_area("编辑", value=st.session_state.generated_code, height=200, key="ws_edit")
                if st.button("💾 保存修改", key="ws_save_edit"):
                    code = extract_code(edited)
                    is_v, msg = validate_strategy_code(code)
                    if is_v:
                        st.session_state.custom_strategy_code = code
                        st.session_state.active_strategy_name = "AI生成策略"
                        st.success("已保存")
                    else:
                        st.error(msg)
                if st.button("🗑️ 清空对话", key="ws_clear"):
                    st.session_state.deepseek_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                    st.session_state.generated_code = ""
                    st.rerun()

    with tab_manual:
        st.markdown("### 💻 手动编写策略")
        st.caption("定义 `generate_signal(df)` 函数，返回含 `signal` 和 `signal_type` 列的 DataFrame")

        default = st.session_state.get("custom_strategy_code") or (
            "# @PARAMS: ma_short=3,15,2; ma_long=10,60,5\n"
            "def generate_signal(df, **kwargs):\n"
            "    import pandas as pd\n"
            "    ma_short = kwargs.get('ma_short', 5)\n"
            "    ma_long = kwargs.get('ma_long', 20)\n"
            "    data = df.copy()\n"
            "    data['MA_S'] = data['close'].rolling(ma_short).mean()\n"
            "    data['MA_L'] = data['close'].rolling(ma_long).mean()\n"
            "    data['signal'] = (data['MA_S'] > data['MA_L']) & (data['MA_S'].shift(1) <= data['MA_L'].shift(1))\n"
            "    data['signal_type'] = 'custom'\n"
            "    return data\n"
        )
        manual = st.text_area("策略代码", value=default, height=350, key="ws_manual")

        c1, c2, c3 = st.columns(3)
        with c1:
            if st.button("💾 保存策略", type="primary", key="ws_save_man", use_container_width=True):
                is_v, msg = validate_strategy_code(manual)
                if is_v:
                    st.session_state.custom_strategy_code = manual
                    st.session_state.active_strategy_name = "自定义策略"
                    st.success("✅ 已保存！")
                else:
                    st.error(f"验证失败: {msg}")
        with c2:
            if st.button("🧪 语法检查", key="ws_test", use_container_width=True):
                is_v, msg = validate_strategy_code(manual)
                if is_v:
                    st.success("✅ 语法正确")
                else:
                    st.error(f"❌ {msg}")

        # 模板库
        with st.expander("📚 策略模板库"):
            templates = {
                "双均线金叉": "def generate_signal(df):\n    import pandas as pd\n    data = df.copy()\n    data['MA5'] = data['close'].rolling(5).mean()\n    data['MA20'] = data['close'].rolling(20).mean()\n    data['signal'] = (data['MA5'] > data['MA20']) & (data['MA5'].shift(1) <= data['MA20'].shift(1))\n    data['signal_type'] = 'custom'\n    return data",
                "MACD金叉": "def generate_signal(df):\n    import pandas as pd\n    data = df.copy()\n    e1 = data['close'].ewm(span=12, adjust=False).mean()\n    e2 = data['close'].ewm(span=26, adjust=False).mean()\n    data['DIF'] = e1 - e2\n    data['DEA'] = data['DIF'].ewm(span=9, adjust=False).mean()\n    data['signal'] = (data['DIF'] > data['DEA']) & (data['DIF'].shift(1) <= data['DEA'].shift(1))\n    data['signal_type'] = 'custom'\n    return data",
                "RSI超卖反弹": "def generate_signal(df):\n    import pandas as pd\n    import numpy as np\n    data = df.copy()\n    delta = data['close'].diff()\n    gain = delta.clip(lower=0).rolling(14).mean()\n    loss = (-delta.clip(upper=0)).rolling(14).mean()\n    data['RSI'] = 100 - (100 / (1 + gain / loss))\n    data['signal'] = (data['RSI'] < 30) & (data['RSI'].shift(1) >= 30)\n    data['signal_type'] = 'custom'\n    return data",
                "布林带突破": "def generate_signal(df):\n    import pandas as pd\n    import numpy as np\n    data = df.copy()\n    data['MA20'] = data['close'].rolling(20).mean()\n    data['STD'] = data['close'].rolling(20).std()\n    data['Upper'] = data['MA20'] + 2 * data['STD']\n    data['signal'] = (data['close'] > data['Upper']) & (data['volume'] > data['volume'].rolling(20).mean() * 1.5)\n    data['signal_type'] = 'custom'\n    return data",
                "放量突破": "def generate_signal(df):\n    import pandas as pd\n    data = df.copy()\n    data['VOL_MA20'] = data['volume'].rolling(20).mean()\n    data['RET'] = data['close'].pct_change()\n    data['signal'] = (data['volume'] > data['VOL_MA20'] * 2) & (data['RET'] > 0.02)\n    data['signal_type'] = 'custom'\n    return data",
            }
            names = list(templates.keys())
            for r in range(0, len(names), 3):
                cols = st.columns(3)
                for i in range(3):
                    idx = r + i
                    if idx >= len(names):
                        break
                    n = names[idx]
                    with cols[i]:
                        if st.button(f"📋 {n}", key=f"tmpl_{idx}", use_container_width=True):
                            st.session_state.generated_code = templates[n]
                            st.session_state.custom_strategy_code = templates[n]
                            st.session_state.active_strategy_name = n
                            st.success(f"✅ 已加载「{n}」")
                            st.rerun()


# ============================================================
# 8. 实盘监控视图
# ============================================================

def live_tab():
    st.title("📡 实盘监控")
    st.caption(f"策略: **{st.session_state.get('active_strategy_name', '内置-右侧趋势')}**")

    sf, sp, _ = get_strategy()

    sub1, sub2, sub3 = st.tabs(["🔍 信号扫描", "📋 信号日志", "💰 模拟交易"])

    with sub1:
        syms = st.text_area("监控股票", "600160\n000001\n600519", height=100, key="live_syms")
        if st.button("🔍 立即扫描", type="primary", key="live_scan"):
            symbols = [s.strip() for s in syms.split('\n') if s.strip()]
            with st.spinner(f"扫描 {len(symbols)} 只..."):
                signals = scan_signals(symbols, fetch_stock_data, sf, **sp)
            if not signals.empty:
                st.dataframe(signals, use_container_width=True)
                buys = signals[signals['信号'].str.contains('买入')]
                if not buys.empty:
                    st.success(f"🟢 {len(buys)} 只买入信号！")
                    for _, row in buys.iterrows():
                        log_signal(row['股票'], 'BUY', row['最新价'] or 0,
                                  row.get('置信度', '—'), "自动扫描")
                else:
                    st.info("当前无买入信号")

    with sub2:
        days = st.slider("最近天数", 1, 90, 30, key="log_days")
        log_df = get_signal_history(days=days)
        if not log_df.empty:
            st.dataframe(log_df, use_container_width=True)
            st.metric("总信号数", len(log_df))
        else:
            st.info("暂无记录")

    with sub3:
        import json
        paper_path = "paper_trade.json"
        state = {'balance': 100000, 'position': 0, 'trades': []}
        if os.path.exists(paper_path):
            try:
                with open(paper_path, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            except Exception:
                pass

        c1, c2 = st.columns(2)
        c1.metric("💰 可用资金", f"{state['balance']:,.0f} 元")
        c2.metric("📦 持仓", f"{state['position']} 股")

        ps = st.text_input("交易股票", "600160", key="paper_sym")
        pp = st.number_input("成交价", value=10.0, step=0.01, key="paper_prc")
        cx, cy = st.columns(2)
        with cx:
            if st.button("🟢 买入", type="primary", use_container_width=True):
                r = paper_trade(ps, 'BUY', pp, state['balance'], state['position'])
                st.success(r['trade'].get('说明', ''))
                st.metric("剩余", f"{r['balance']:,.0f}")
        with cy:
            if st.button("🔴 卖出", use_container_width=True):
                r = paper_trade(ps, 'SELL', pp, state['balance'], state['position'])
                st.success(r['trade'].get('说明', ''))
                st.metric("剩余", f"{r['balance']:,.0f}")

        if state.get('trades'):
            with st.expander("📋 交易历史"):
                st.dataframe(pd.DataFrame(state['trades']), use_container_width=True)


# ============================================================
# 9. 主入口
# ============================================================

def main():
    st.set_page_config(
        page_title="QuantResearch - 量化策略研究",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    init_state()

    # 三视图 Tab
    t1, t2, t3 = st.tabs(["📊 策略研究", "🤖 策略工坊", "📡 实盘监控"])

    with t1:
        research_tab()

    with t2:
        workshop_tab()

    with t3:
        live_tab()


if __name__ == "__main__":
    main()
