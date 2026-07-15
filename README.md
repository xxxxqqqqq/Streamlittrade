```text
本项目为简单的量化策略回测网站，目的为寻找最好的量化策略，早日退休

项目启动命令：streamlit run app.py 

主文件结构图（项目模块总览）
Streamlittrade/
├── app.py                     # 🚀 主入口 — Streamlit 用户界面（页面导航、侧边栏、策略配置、结果渲染）
├── config.py                  # ⚙️ 系统配置 — DeepSeek 系统提示词（SYSTEM_PROMPT）、API 常量
├── deepseek_api.py            # 🤖 AI 客户端 — DeepSeek API 调用、代码提取（extract_code）、语法验证（validate_strategy_code）
├── data_loader.py             # 📡 数据获取 — Baostock A 股日线数据（前复权 + 内存缓存 + 重试）
├── strategies.py              # 📈 策略信号 — 右侧趋势策略（generate_right_signal）、V型反转策略（generate_v_shape_signal）
├── backtest.py                # 🔬 回测引擎 — 事件驱动回测、ATR 动态止损、印花税模拟、12 项绩效指标（run_backtest）
├── charts.py                  # 📊 可视化 — 净值曲线（Plotly）、K 线图（Highcharts Stock）、最大回撤曲线
├── requirements.txt           # Python 依赖清单
├── packages.txt               # Streamlit Cloud 系统依赖
├── deepseekapi.env            # API Key 环境变量模板
└── README.md                  # 项目说明文档

模块依赖关系
config.py ─────────────────────────────────────────────────────────────┐
    ↑                                                                   │
deepseek_api.py ←── config.py                                           │
    ↑                                                                   │
data_loader.py                                                          │
    ↑                                                                   │
strategies.py                                                           │
    ↑                                                                   │
backtest.py                                                             │
    ↑                                                                   │
charts.py                                                               │
    ↑                                                                   │
app.py ←── config.py + deepseek_api.py + data_loader.py                 │
      ←── strategies.py + backtest.py + charts.py                       │

各模块对外接口一览
┌──────────────────┬──────────────────────────────────────────────────────────────┐
│ 模块             │ 对外暴露的函数 / 常量                                          │
├──────────────────┼──────────────────────────────────────────────────────────────┤
│ config.py        │ SYSTEM_PROMPT                                                │
│ deepseek_api.py  │ call_deepseek(), extract_code(), validate_strategy_code()    │
│ data_loader.py   │ fetch_stock_data()                                           │
│ strategies.py    │ generate_right_signal(), generate_v_shape_signal()           │
│ backtest.py      │ run_backtest()                                               │
│ charts.py        │ plot_equity(), plot_kline_with_signals(), plot_drawdown()    │
└──────────────────┴──────────────────────────────────────────────────────────────┘