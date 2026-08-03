# 量化模型网站演进架构

## 最终数据流

```text
Vue 3 + TypeScript
        │ REST / WebSocket
        ▼
FastAPI API ─────────────── PostgreSQL（用户、策略、任务、实验、模型元数据）
        │
        ├── Redis（缓存、任务队列、短期进度）
        │        │
        │        ▼
        │   Python Worker（特征、训练、验证、回测、预测）
        │        │
        └────────┴───────── OSS/MinIO（Parquet、模型文件、图表和报告）
```

WebSocket 只传递进度和状态事件，不传输大型行情或模型文件。大文件由API生成
受控下载地址，从OSS/MinIO读取。生产环境还应在最外层增加Nginx或Caddy。

## 已贯通的正式研究主链路

```text
DataSource
  → Raw DataVersion
  → Standardized DataVersion（质量门禁）
  → FeatureSnapshot（特征定义版本 + 数据哈希）
  → Dataset（同源行情生成未来收益标签）
  → Experiment（Purged Walk-Forward）
  → ModelVersion + OOS Predictions
  → 绑定同一 DataVersion 的可信回测
```

正式数据集不再重新下载行情。它通过 `feature_snapshot_id` 读取不可变特征，
并从该快照的父 `data_version_id` 计算标签。模型登记同时保存样本外预测
Parquet 及其 SHA256。正式回测通过 `data_version_id` 读取同一标准化行情，
从而能够审计训练与回测是否使用同一份数据资产。

## 第三阶段：模型工程与策略版本（已完成）

研究链路已经从单一基线扩展为可运行的模型工程闭环：

```text
Strategy v1/v2/... ───────────────→ BacktestRun
                                           ↑
DataVersion → FeatureSnapshot → Dataset → Experiment
                                           │
                       HGB / RF / Logistic Regression
                                           ↓
                 ModelVersion + 特征重要性 + OOS预测
                         │                 │
                   审批 / 归档 / 回滚       ↓
                         └────→ Production Model
                                      │
                                      ↓
FeatureSnapshot ─────────────→ PredictionRun → Parquet
```

- 策略以项目内 `slug + version` 形成不可变版本链，回测保存 `strategy_id`
  与执行参数快照。
- 三种平台审核算法共用 Purged Walk-Forward 规则和经济指标，实验页可以横向比较。
- 模型登记保存 permutation importance、模型哈希和样本外预测哈希。
- 批量推理只接受已登记模型和已就绪特征快照，并把预测结果登记到项目级任务表。
- 每种算法在每个项目中只有一个生产模型；管理员可以审批、归档和回滚，所有变更写入审计日志。

## 生产模型运行治理扩展（已完成）

生产模型不再依赖研究员手工反复点击。平台新增了持久化运行闭环：

```text
PredictionSchedule
  └─ Scheduler（行锁抢占，支持多 API 副本）
       └─ Job + Outbox → Worker → PredictionRun

ModelVersion + Baseline FeatureSnapshot + Current FeatureSnapshot
  └─ DriftRun → Feature PSI / Mean Shift / Score PSI
       ├─ none
       ├─ warning → AlertEvent
       └─ critical → AlertEvent
                         └─ acknowledged → resolved + AuditLog
```

- 预测计划保存运行间隔、启停状态、上次任务和下次运行时间，重启后不会丢失。
- 调度器使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 抢占到期计划，多副本部署时不会重复派发。
- 自动预测在每次执行时动态解析当前生产模型，因此模型回滚后无需修改计划。
- 漂移 Worker 比较模型训练基线和当前不可变特征快照，计算各特征 PSI、
  标准化均值偏移、缺失率变化以及预测概率 PSI。
- PSI `0.10` 触发 warning、`0.25` 触发 critical；告警持久化并记录确认人、
  处理时间和审计事件。
- 运行总览、计划、漂移检查和告警均按当前项目隔离。

## 原定第四阶段：前端产品化（已完成）

Vue 工作台已经从流程演示扩展为可管理的多用户研究产品：

- 侧栏默认只展示数据、特征、训练、模型、预测、策略、回测和任务等核心研究入口；
- 项目成员、用户、审计与生产监控统一收进默认折叠的“平台治理”分组，通知与搜索保留在顶部快捷入口；
- 模型回滚、任务取消和重试保持为资源详情中的上下文操作，不再占用一级导航。

- 管理员可以创建用户、调整全局角色、启用或停用账号；
- 项目管理支持创建项目、列出成员、添加成员、调整项目角色和移除成员；
- 审计日志提供服务端分页以及动作、资源和关键词筛选；
- 数据版本和特征快照拥有独立详情页，展示质量报告、统计画像、内容哈希和完整血缘；
- 实验与模型分别提供横向比较，模型比较同时展示样本外指标和重要特征；
- 顶部搜索会查询当前项目的策略、数据集、实验、模型、回测、数据版本和特征快照；
- 顶部通知按钮连接生产告警，通知中心支持状态筛选和管理员处置；
- 通用列表具备关键词、状态、每页条数与翻页控制；
- Axios 错误经统一格式化后进入全局 Toast，页面仍可保留局部错误上下文；
- Vitest 覆盖通用分页和错误格式化，Playwright 覆盖登录、搜索、通知、管理页面和数据详情。

## 分阶段实施

1. **平台地基（本次已完成）**：FastAPI应用工厂、版本化路由、统一配置、
   PostgreSQL/Redis客户端、健康检查、后端容器和本地基础设施。
2. **数据库与首条任务链路（已完成基础版）**：Alembic迁移、任务与回测表、
   API创建任务、Worker消费、PostgreSQL状态以及MinIO回测产物。
3. **完整领域模型**：继续建立用户、策略版本、数据集、实验、模型和产物索引，
   并加入任务重试、取消、超时恢复和WebSocket进度推送。
4. **量化核心服务化**：把数据集构建、回测和因子分析封装成服务，禁止API执行
   CPU密集计算和不可信自定义代码。
5. **第一个训练闭环**：多股票面板数据、特征、标签、时间切分、LightGBM基线、
   样本外回测、模型登记和可复现配置。
6. **Vue 3前端**：任务中心、策略、数据集、训练实验、回测报告和模型仓库。
7. **生产化**：认证授权、限流、审计、隔离执行、监控告警、RDS/Redis/OSS和HTTPS。

## 回测核心后续增强

### 模型预测到组合回测闭环（已完成）

正式模型研究现在可以直接使用训练阶段保存的 Purged Walk-Forward 样本外预测构建组合：

```text
ModelVersion
  → immutable OOS prediction Parquet
  → probability threshold
  → cross-sectional Top-N
  → periodic equal-weight rebalance
  → next-trading-day open execution
  → T+1 / lot / fee / limit / suspension / capacity constraints
  → portfolio metrics + trades + equity + model/data lineage
```

- 回测自动解析模型训练数据集对应的特征快照和标准化数据版本，前端不能替换成无关行情；
- 只使用训练时各 Walk-Forward 测试折生成的 OOS 概率，最终全量拟合模型不会重新预测训练历史；
- 组合构建保存 Top-N、最低概率、调仓频率、等权规则和每次入选标的；
- 报告保存模型、预测产物和数据版本哈希，且仍沿用可信成交约束账本。

当前回测已经修正下一交易日成交、T+1、整手和费用，但模型网站上线前仍需：

- 交易日历、停牌、ST及涨跌停成交约束；
- 成交量容量、冲击成本和部分成交；
- 未复权价格、复权因子、分红送转的统一账本；
- 多股票共享现金、组合级订单和再平衡；
- 基准指数、行业与风格暴露；
- 特征预热窗口以及 Purged/Embargo 时间验证；
- 固定随机种子、数据版本、代码版本和可复现回测快照。

这些功能应随数据集与训练闭环逐步加入，不需要阻塞平台地基建设。

## 当前第一阶段的启动方式

启动平台基础设施：

```powershell
docker compose -f compose.platform.yaml up -d --build
```

启动后可访问：

- FastAPI文档：`http://localhost:8000/docs`
- API存活检查：`http://localhost:8000/health/live`
- API依赖就绪检查：`http://localhost:8000/health/ready`
- MinIO控制台：`http://localhost:9001`
- Vue量化研究工作台：`http://localhost:5173`

停止容器但保留数据库和对象存储数据：

```powershell
docker compose -f compose.platform.yaml stop
```

仅在明确需要清空本地平台数据时，才可以执行带 `-v` 的删除命令。

不使用Docker时，也可以在项目根目录直接启动API：

```powershell
python -m uvicorn backend.app.main:app --reload --port 8000
```

## 第一条异步回测API

提交一个不依赖外部行情网络的演示任务：

```http
POST /api/v1/backtests
Content-Type: application/json

{
  "data_source": "demo",
  "symbol": "DEMO",
  "strategy_name": "right_trend",
  "strategy_parameters": {
    "ma_short": 5,
    "ma_mid": 20,
    "ma_long": 60,
    "vol_ratio": 1.2
  },
  "start_date": "2020-01-01",
  "end_date": "2024-12-31",
  "initial_cash": 100000
}
```

接口返回 `job_id` 和 `backtest_id`。随后分别查询：

```text
GET /api/v1/jobs/{job_id}
GET /api/v1/backtests/{backtest_id}
```

任务完成后，小型指标保存在PostgreSQL，交易明细和每日净值保存到
`s3://quant-artifacts/backtests/{backtest_id}/result.json`。

平台容器运行时，可用一条命令重复验证整条链路：

```powershell
python scripts/smoke_backtest.py
```
