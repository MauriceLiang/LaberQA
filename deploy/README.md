# LaborQA Docker 部署与运维

## 1. 部署架构

部署使用两个容器：`frontend` 运行 Nginx，提供 Vue 静态资源并将 `/api/*`、SSE、API 文档请求反向代理到 `backend`；`backend` 运行 FastAPI、LangChain、FAISS、SQLite、文档解析和模型调用。宿主机只暴露前端 `80` 端口，后端 `8000` 仅在 Compose 内部网络可访问。

运行数据通过宿主机目录持久化：

| 目录 | 内容 |
| --- | --- |
| `data/` | SQLite 数据库、生产 FAISS 索引和检索实验索引 |
| `uploads/` | 用户上传的 PDF、DOC、DOCX、MD、TXT 原文件 |
| `model-cache/` | HuggingFace / Sentence Transformers 模型缓存 |
| `backups/` | 备份包和恢复前快照 |

## 2. 服务器环境

服务器需要安装：

- Git
- Docker Engine
- Docker Compose v2

检查版本：

```bash
git --version
docker --version
docker compose version
```

推荐将项目部署到 `/opt/laborqa`，并保证当前用户可以读写项目目录及 `data/`、`uploads/`、`model-cache/`、`backups/`。

## 3. 环境变量

首次部署复制模板：

```bash
cp deploy/.env.example deploy/.env
```

至少填写：

```dotenv
LLM_API_KEY=你的_API_Key
LLM_BASE_URL=https://你的服务地址/v1
LLM_MODEL=你的模型名称
```

容器环境固定使用 `DOC_PARSER_BACKEND=libreoffice` 和 `LOCAL_EMBEDDING_DEVICE=cpu`。默认使用本地 `BAAI/bge-small-zh-v1.5` Embedding；如使用远程 Embedding，将 `EMBEDDING_PROVIDER` 改为 `api` 并填写对应的 API 配置。不要把 `deploy/.env` 或任何真实密钥提交到 Git。

## 4. 第一次构建

在仓库根目录执行：

```bash
mkdir -p data uploads model-cache backups
docker compose config
docker compose build
```

需要强制验证完整构建链时执行：

```bash
docker compose build --no-cache
```

后端镜像会安装 FAISS、Sentence Transformers、LibreOffice 和中文字体；前端镜像先执行 `npm ci`、TypeScript 检查和 Vite 构建，再使用 Nginx 提供 `dist/`。

## 5. 第一次启动

```bash
docker compose up -d
docker compose ps
```

后端达到 `healthy` 后前端才会启动。浏览器访问：

```text
http://服务器IP/
```

## 6. 模型初始化

默认本地 Embedding 模型会在首次需要时准备并缓存到 `model-cache/`。也可以主动检查：

```bash
docker compose exec backend python -m app.scripts.verify_embedding
du -sh model-cache
```

重启或重建容器不会删除该目录，因此已下载模型可以复用。

## 7. 健康检查

宿主机检查：

```bash
curl http://127.0.0.1/api/health
```

应返回 HTTP 200。响应中的 `service`、`database`、`doc_converter`、Embedding 和向量索引状态会按实际准备情况返回。检查旧版 DOC 解析器：

```bash
docker compose exec backend which libreoffice
```

API 文档地址：

- <http://服务器IP/docs>
- <http://服务器IP/redoc>
- <http://服务器IP/openapi.json>

## 8. 查看日志

```bash
docker compose logs -f --tail=200
docker compose logs -f --tail=200 backend
docker compose logs -f --tail=200 frontend
```

Compose 已配置 JSON 日志轮转，每个容器最多保留 5 个 20 MB 文件。

## 9. 服务启动、停止和重启

```bash
docker compose up -d       # 启动
docker compose stop         # 停止但保留容器和数据
docker compose restart      # 重启
docker compose down         # 删除容器和网络，保留宿主机数据
```

不要使用 `docker compose down -v`，否则可能删除命名卷；本项目运行数据应保留在宿主机目录。

## 10. 数据目录

```text
data/app.db
data/faiss/production/
data/faiss/experiments/
uploads/
model-cache/
backups/
```

`data/` 和 `uploads/` 是业务数据，`model-cache/` 是可重新下载的模型缓存。容器删除和重建不会删除这些目录。

## 11. 备份

备份脚本会先停止后端，保证 SQLite 和 FAISS 在一致状态下打包 `data/` 与 `uploads/`，完成后自动启动后端：

```bash
./deploy/backup.sh
find backups -maxdepth 2 -type f
```

备份包位于 `backups/<时间戳>/laborqa-runtime.tar.gz`。模型缓存不进入备份，可在新服务器重新下载。

## 12. 恢复

恢复会先停止并删除当前 `data/`、`uploads/`，然后在删除前生成快照：

```bash
./deploy/restore.sh backups/<时间戳>/laborqa-runtime.tar.gz
```

恢复后检查：

```bash
docker compose ps
curl http://127.0.0.1/api/health
```

恢复操作会替换当前运行数据，执行前应确认备份文件路径正确。

## 13. 升级

每次升级先备份，再拉取代码、构建并启动：

```bash
./deploy/backup.sh
git pull origin main
docker compose build
docker compose up -d
docker compose ps
docker compose logs --tail=200 backend
```

升级后检查首页、`/api/health`、文档上传和问答流式输出。

## 14. 回滚

升级前记录当前版本：

```bash
git rev-parse HEAD
```

发生严重故障时切回稳定提交并重建：

```bash
git checkout <上一个稳定 commit>
docker compose build
docker compose up -d
```

如果故障涉及数据库或索引状态，再执行对应备份的恢复脚本。

## 15. 常见错误

### `frontend` 无法启动

查看 `backend` 是否为 `healthy`：

```bash
docker compose ps
docker compose logs --tail=200 backend
```

### 页面请求到了 `127.0.0.1:8000`

确认前端镜像使用了 `VITE_API_BASE_URL=/api`，并重新构建：

```bash
docker compose build frontend
docker compose up -d frontend
```

### SSE 回答一次性出现

确认 `frontend/nginx.conf` 中存在 `proxy_buffering off`、`proxy_cache off` 和足够长的 `proxy_read_timeout`，然后重建前端容器。

### 上传文件超过限制

Nginx 限制为 25 MB，后端业务限制默认为 20 MB。调整业务限制时需要同步修改 `deploy/.env` 和 Nginx 配置。

### 本地 Embedding 不可用

检查模型缓存和容器日志：

```bash
du -sh model-cache
docker compose exec backend python -m app.scripts.verify_embedding
docker compose logs --tail=200 backend
```

### 旧版 DOC 不可用

确认容器内存在 LibreOffice，并检查 `/api/health` 的 `doc_converter`：

```bash
docker compose exec backend which libreoffice
curl http://127.0.0.1/api/health
```
