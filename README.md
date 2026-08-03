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

## 核心架构说明

行情、回测和策略解析的可复用实现已迁移到 `quant_core/`。根目录的
`backtest.py`、`data_loader.py` 保留为旧调用兼容层和 Streamlit 适配层。
FastAPI、异步 Worker 或命令行程序应直接依赖 `quant_core`。

回测成交口径、T+1、整手、费用和测试方法详见 [REFACTORING.md](REFACTORING.md)。
量化模型网站的目标架构与分阶段路线详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 量化研究平台（FastAPI + Vue 3）

当前仓库同时保留原 Streamlit 应用，并新增了可独立演进的平台架构。启动完整平台：

```powershell
docker compose -f compose.platform.yaml up -d --build
```

启动后访问：

- Vue 研究工作台：`http://localhost:5173`
- FastAPI / Swagger：`http://localhost:8000/docs`
- MinIO 管理界面：`http://localhost:9001`

本地开发登录账号：`admin@quant.local`，密码：`quant-dev-admin`。访问令牌仅保存在浏览器当前会话中，关闭标签页后需要重新登录。生产部署必须设置 `QUANT_JWT_SECRET`、`QUANT_BOOTSTRAP_ADMIN_EMAIL` 和 `QUANT_BOOTSTRAP_ADMIN_PASSWORD`，禁止继续使用本地默认值。

当前已贯通两条异步链路：可信回测，以及“数据集构建 → 时间切分 → 模型训练 → 指标保存 → 模型登记”。
数据集以 Parquet 保存，模型以 joblib 保存，业务状态与指标保存在 PostgreSQL。

Vue 工作台已经可以完成第一条可交互研究链路：点击右上角“新建研究”，依次创建数据集、等待异步特征任务、配置训练实验，最后查看样本外指标与模型产物地址。也可以从“数据集”“训练实验”和“模型仓库”页面分别进入对应步骤。

任务中心使用认证 WebSocket 实时接收状态，连接失败时自动退回定时轮询。排队或运行中的任务可以取消，失败或已取消任务可以按原始参数重试；登录、取消、重试和模型晋级都会写入审计日志。模型只能按 `candidate → validated → production` 顺序晋级，同一算法只保留一个生产版本。

“模拟交易”页面提供完全隔离的虚拟账户和交易账本。它不连接券商，不会产生真实订单；当前价格输入仅代表手工或历史回放快照。模拟盘执行 A 股整手、T+1、资金、单笔金额、单票仓位、费用、账户冻结、订单与成交审计。费用参数是平台的保守模拟默认值，不代表任何具体券商报价。管理员还可以在“运行监控”页面查看任务、模型、模拟账户、基础设施状态和活动告警。

停止服务但保留数据：

```powershell
docker compose -f compose.platform.yaml stop
```

运行自动化测试：

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s backend/tests -v
```
