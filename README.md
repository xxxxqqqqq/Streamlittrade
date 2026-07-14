```text
本项目为简单的量化策略回测网站，目的为寻找最好的量化策略，早日退休

项目启动命令：streamlit run app.py 

主文件结构图
app.py
├── 0. 导入依赖
│   ├── streamlit, pandas, numpy, plotly
│   ├── baostock, requests, re, os
│   └── streamlit_ace（可选）
│
├── 1. 配置与常量
│   ├── load_dotenv（加载 .env）
│   ├── DEEPSEEK_API_KEY（由用户输入，不写死）
│   └── SYSTEM_PROMPT（DeepSeek 系统指令，固定）
│
├── 2. DeepSeek API 工具函数
│   ├── call_deepseek()              # 调用 API 生成代码
│   ├── extract_code()               # 提取纯 Python 代码（去除 markdown）
│   └── validate_strategy_code()     # 验证代码语法和函数规范
│
├── 3. 数据获取（Baostock）
│   └── fetch_stock_data()           # 获取日线数据（@st.cache_data 内存缓存）
│
├── 4. 内置策略信号生成
│   ├── generate_right_signal()      # 右侧趋势策略（均线+MACD+RSI+KDJ+量能）
│   └── generate_v_shape_signal()    # V型反转策略（急跌+企稳+放量反弹）
│
├── 5. 回测引擎
│   ├── get_entry_reason()           # 生成买入原因描述
│   ├── run_backtest()               # 核心回测引擎（T+1、止损/止盈/移动止损）
│   └── calculate_metrics()          # 计算绩效指标（收益率/回撤/夏普/胜率等）
│
├── 6. 可视化函数
│   ├── plot_equity()                # 净值曲线（平滑）
│   ├── plot_kline_with_signals()    # K线图 + 买卖点 + 成交量副图
│   └── plot_drawdown()              # 最大回撤曲线
│
└── 7. Streamlit 界面（主入口）
    ├── st.set_page_config()          # 页面配置
    ├── 会话状态初始化                # deepseek_api_key, messages, generated_code, custom_strategy_code
    ├── st.title() / st.markdown()    # 页面标题
    │
    ├── 侧边栏 (st.sidebar)
    │   ├── 🔑 API Key 设置
    │   │   ├── 输入框（type="password"）
    │   │   ├── 保存/重置按钮
    │   │   └── 存储到 st.session_state.deepseek_api_key
    │   │
    │   ├── ⚙️ 参数设置
    │   │   ├── 股票代码（text_input）
    │   │   ├── 开始/结束日期（date_input）
    │   │   └── 策略选择（selectbox）
    │   │       ├── 右侧趋势策略
    │   │       ├── V型反转策略
    │   │       ├── 自定义策略
    │   │       └── 🤖 AI 生成策略
    │   │
    │   ├── 📊 策略参数（根据策略动态显示）
    │   │   ├── 右侧趋势策略：均线滑块、放量倍数
    │   │   ├── V型反转策略：回看天数、跌幅阈值、反弹幅度、放量倍数
    │   │   ├── 自定义策略：代码编辑器（st_ace / st.text_area）
    │   │   └── AI 生成策略：
    │   │       ├── 聊天界面（chat_message + chat_input）
    │   │       ├── 调用 DeepSeek → 生成代码
    │   │       ├── 代码展示（st.code）
    │   │       ├── 代码编辑（st.text_area）
    │   │       └── 保存/重新生成按钮
    │   │
    │   └── 💼 交易参数（始终显示）
    │       ├── 初始资金（number_input）
    │       ├── 止损比例（slider）
    │       ├── 止盈比例（slider）
    │       ├── 移动止损（slider）
    │       ├── 单次建仓比例（slider）
    │       └── 🚀 运行回测按钮（run_btn）
    │
    └── 主界面（if run_btn）
        ├── 数据获取（fetch_stock_data）
        ├── 信号生成（根据策略类型调用对应函数）
        │   ├── 右侧趋势策略 → generate_right_signal()
        │   ├── V型反转策略 → generate_v_shape_signal()
        │   ├── 自定义策略 → exec(user_code)
        │   └── AI 生成策略 → exec(custom_strategy_code)
        ├── 回测执行（run_backtest）
        ├── 绩效指标展示（8 个 metric 卡片）
        │   ├── 总收益率、年化收益率
        │   ├── 最大回撤、夏普比率
        │   ├── 总交易次数、胜率
        │   └── 盈亏比、平均持仓(天)
        ├── 可视化图表
        │   ├── 净值曲线（plot_equity）
        │   ├── K线图 + 成交量（plot_kline_with_signals）
        │   └── 最大回撤曲线（plot_drawdown）
        ├── 交易明细（st.expander + st.dataframe）
        └── 详细绩效指标（st.expander + st.dataframe）
```