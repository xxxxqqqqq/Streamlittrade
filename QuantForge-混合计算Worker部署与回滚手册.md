# QuantForge 混合计算 Worker 部署与回滚手册

## 1. 发布原则

采用两阶段发布，任何时刻都保留旧的 `quant-backtests` 队列：

1. **兼容发布**：先发布数据库新增字段、低内存算法和新版 Worker，但保持 `QUANT_QUEUE_MODE=legacy`。此时行为与旧版一致。
2. **路由切换**：笔记本 Worker 连通并通过烟测后，API 改为 `split`；云 Worker 只消费 `quant-light`，笔记本只消费 `quant-heavy`。

切换失败只需恢复 `legacy` 配置并启动云 Worker，不需要删除数据库字段或成功产物。

## 2. 组件与文件

| 文件 | 用途 |
|---|---|
| `compose.platform.yaml` | 云端完整平台及兼容的旧队列默认值 |
| `compose.worker-gateway.yaml` | 将 PostgreSQL、Redis、MinIO 仅绑定到云服务器 `127.0.0.1` |
| `compose.worker.yaml` | 可移植的独立计算 Worker |
| `compose.worker.ssh.yaml` | 热点/Wi-Fi 场景的容器内 SSH 隧道 |
| `.env.worker.example` | 本地配置模板，真实文件不进入 Git |
| `scripts/compute_worker.ps1` | 构建、启动、停止、查看状态和日志 |

SSH 隧道由笔记本主动连接云服务器。云端 5432、6379、9000 不对公网开放；隧道容器也不向笔记本局域网发布端口。

## 3. 云端兼容发布

在发布前记录当前 Git 提交和镜像 ID，并创建数据库备份：

```bash
cd /opt/quantforge
git rev-parse HEAD
docker compose -f compose.platform.yaml -f compose.production.yaml images
mkdir -p /opt/quantforge-backups
docker compose -f compose.platform.yaml -f compose.production.yaml exec -T postgres \
  pg_dump -U quant -d quant -Fc > /opt/quantforge-backups/before-hybrid-YYYYMMDD-HHMM.dump
```

先保持以下配置：

```dotenv
QUANT_QUEUE_MODE=legacy
QUANT_CLOUD_WORKER_QUEUES=quant-backtests
```

构建镜像、执行迁移并重启服务。迁移 `20260825_0020` 只增加可空字段和索引，旧代码可以继续使用该数据库。

## 4. 开启回环网关

云端使用三份 Compose 文件：

```bash
docker compose \
  -f compose.platform.yaml \
  -f compose.production.yaml \
  -f compose.worker-gateway.yaml \
  up -d postgres redis minio
```

用 `ss -lnt` 验证 15432、16379、19000 只监听 `127.0.0.1`。不得把这些端口加入阿里云公网安全组。

## 5. 笔记本验证

复制模板为 `.env.worker`，填入 Worker 专用凭据。SSH 模式的服务地址固定使用 Compose 内部名称：

```dotenv
WORKER_TRANSPORT=ssh
QUANT_DATABASE_URL=postgresql+psycopg://...@secure-tunnel:15432/quant
QUANT_REDIS_URL=redis://...@secure-tunnel:16379/0
QUANT_OBJECT_STORAGE_ENDPOINT=http://secure-tunnel:19000
QUANT_WORKER_QUEUES=quant-heavy
QUANT_WORKER_NAME=laptop-worker-01
```

启动和检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\compute_worker.ps1 validate-config
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\compute_worker.ps1 build
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\compute_worker.ps1 start
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\compute_worker.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\compute_worker.ps1 logs
```

依次验证 1～3、12、36、87 因子。任务详情必须显示 `quant-heavy` 和 `laptop-worker-01`；第二次相同输入应命中缓存，恢复任务应出现 `resumed_partitions > 0`。

## 6. 切换生产路由

确认笔记本在线后：

```dotenv
QUANT_QUEUE_MODE=split
QUANT_CLOUD_WORKER_QUEUES=quant-light,quant-backtests
```

过渡期云 Worker 同时监听旧队列，直到旧的 `quant-backtests` 已排空。之后可改为仅监听 `quant-light`。笔记本始终只监听 `quant-heavy`，避免云端 1 GiB Worker 抢走宽表任务。

## 7. 快速回滚

### 只回滚路由（优先）

1. 停止笔记本 Worker：`powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\compute_worker.ps1 stop`。
2. 云端设置 `QUANT_QUEUE_MODE=legacy`、`QUANT_CLOUD_WORKER_QUEUES=quant-backtests`。
3. 重启 API 和云 Worker。
4. 未开始任务继续留在旧队列；已中断任务明确失败后可重试，检查点保留。

### 回滚应用代码

1. 执行上面的路由回滚。
2. 云端切回发布前记录的 Git 提交并重新构建 API、Worker、前端。
3. 保留 `20260825_0020` 的新增可空字段；旧代码不会受影响，也避免破坏任务审计数据。
4. 只有确认必须还原数据库时才执行 Alembic downgrade；执行前再创建一次备份。

### 数据库灾难恢复

仅当迁移造成不可兼容损坏时使用发布前的 `pg_dump -Fc`。恢复会覆盖发布后的业务数据，因此不能作为普通路由回滚手段。

## 8. 迁移到台式机

停止笔记本领取新任务，等待当前任务完成；在台式机复制相同 Git 提交、`.env.worker` 模板和 Worker 镜像，把名称改为 `desktop-worker-01`。先完成 1～3 与 12 因子烟测，再停止笔记本。输入缓存无需迁移；如迁移检查点，则输入哈希、因子定义哈希和代码版本必须完全一致。
