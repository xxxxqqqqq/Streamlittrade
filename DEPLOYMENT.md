# Docker 部署

日常开发可以继续使用 Windows 本机 Python。Docker 只负责构建、验证和部署生产环境。

## 本地构建与启动

项目的 API Key 模板位于 `deepseekapi.env`。不要把真实密钥提交到 Git。

```powershell
docker compose --env-file deepseekapi.env up -d --build
```

默认使用清华 PyPI 镜像构建。如需改用官方源，可在命令前设置 `PIP_INDEX_URL=https://pypi.org/simple`。

启动后访问 <http://localhost:8501>，查看状态：

```powershell
docker compose ps
docker compose logs -f web
```

停止服务但保留数据：

```powershell
docker compose down
```

交易记录保存在 Docker volume `streamlittrade_app-data` 中。只有明确不再需要这些数据时，才使用 `docker compose down -v`。

## 阿里云服务器

服务器安装 Docker Engine 和 Compose 插件后，将代码拉取到服务器，在服务器单独创建 `deepseekapi.env`，然后运行同一条 `docker compose` 命令。生产环境建议在服务前配置 Nginx/Caddy、域名和 HTTPS，不要直接把 API Key 写入镜像。
