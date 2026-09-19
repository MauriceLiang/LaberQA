# LaborQA HTTPS Docker 部署与运维

本文档描述 mauriceliang.xyz 的 Docker Compose 部署方式。部署完成后，用户统一通过 https://mauriceliang.xyz 访问；Caddy 负责 TLS 终止、证书申请与续期，frontend Nginx 继续负责 Vue 静态资源、API 反向代理、SSE 和 SPA 路由回退。

## 1. 部署架构

~~~text
Internet
   │
   ├── :80  ───────────────┐
   └── :443 ──────────────┤
                           ▼
                    caddy:2-alpine
                 TLS / 自动续期 / 跳转
                           │
                           ▼
                       frontend:80
                      Nginx + Vue
                           │
                           ▼
                      backend:8000
                  FastAPI + RAG 服务
~~~

| 服务 | Compose 内端口 | 宿主机端口 | 作用 |
| --- | --- | --- | --- |
| caddy | 80、443 | 80、443 | HTTPS 入口、HTTP → HTTPS 重定向、反向代理 |
| frontend | 80 | 不直接暴露 | Vue 静态资源、/api/*、SSE、API 文档和 SPA fallback |
| backend | 8000 | 不暴露 | FastAPI、LangChain、SQLite、FAISS、文档解析和模型调用 |

公网只需要开放：

~~~text
22/TCP    SSH（按服务器安全策略限制来源）
80/TCP    HTTP-01 证书校验与 HTTP → HTTPS 跳转
443/TCP   HTTPS 正式访问
~~~

不要将 8000 或 5173 暴露到公网。

### 持久化内容

| 存储 | 内容 | 备份 / 保留策略 |
| --- | --- | --- |
| data/ | SQLite、生产 FAISS 索引和检索实验索引 | 业务备份 |
| uploads/ | 用户上传的 PDF、DOC、DOCX、MD、TXT 原文件 | 业务备份 |
| model-cache/ | HuggingFace / Sentence Transformers 模型缓存 | 可重新下载，可选备份 |
| backups/ | 运行数据备份包和恢复前快照 | 按运维策略保留 |
| caddy_data | 证书、ACME 状态和 Caddy 运行数据 | 必须保留，避免不必要的重新申请 |
| caddy_config | Caddy 配置状态 | 与 caddy_data 一起保留 |

caddy_data 和 caddy_config 是 Docker 命名卷，不包含在 deploy/backup.sh 的业务数据归档中。不要执行 docker compose down -v，否则会删除证书相关卷。

## 2. 服务器环境

服务器需要安装：

- Git
- Docker Engine
- Docker Compose v2
- 可从公网访问的固定服务器地址

检查版本：

~~~bash
git --version
docker --version
docker compose version
~~~

推荐将项目部署到 /opt/laborqa，并保证当前用户可以读写项目目录及 data/、uploads/、model-cache/、backups/。

## 3. 域名、DNS 与防火墙

当前 Caddy 配置文件为 Caddyfile，其中的站点地址是：

~~~caddy
mauriceliang.xyz {
    reverse_proxy frontend:80
}
~~~

如果更换域名，需要同时修改 deploy/Caddyfile 和 DNS 记录。Caddy 使用 ACME HTTP-01 方式申请证书，因此证书申请期间域名必须能够从公网访问宿主机的 80 端口。

检查 DNS：

~~~bash
dig +short A mauriceliang.xyz
dig +short AAAA mauriceliang.xyz
~~~

要求：

- A 记录必须指向当前服务器公网 IPv4。
- 只有服务器已正确配置公网 IPv6 时才保留 AAAA 记录；错误的 AAAA 记录可能导致部分客户端访问失败。
- 云安全组和系统防火墙必须允许 TCP 80、443。
- 宿主机不能有 Nginx、Apache、旧 Caddy 或其他服务占用 80、443。

检查端口：

~~~bash
sudo ss -lntp | grep -E ':80|:443'
~~~

如存在宿主机 Nginx 且确认没有其他用途，可以停止它：

~~~bash
sudo systemctl stop nginx
sudo systemctl disable nginx
~~~

## 4. 环境变量与密钥

首次部署复制模板：

~~~bash
cp deploy/.env.example deploy/.env
~~~

至少填写：

~~~dotenv
LLM_API_KEY=你的_API_Key
LLM_BASE_URL=https://你的服务地址/v1
LLM_MODEL=你的模型名称
~~~

容器部署模板默认使用：

~~~dotenv
DOC_PARSER_BACKEND=libreoffice
LOCAL_EMBEDDING_DEVICE=cpu
EMBEDDING_PROVIDER=local
LOCAL_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
~~~

如使用远程 Embedding，将 EMBEDDING_PROVIDER 改为 api，并完整填写 EMBEDDING_API_KEY、EMBEDDING_BASE_URL 和 EMBEDDING_API_MODEL。不要提交 deploy/.env 或任何真实密钥。

## 5. 实施前备份

已有运行实例时，先备份业务数据并记录当前版本：

~~~bash
cd /opt/laborqa
./deploy/backup.sh
git rev-parse HEAD
~~~

备份脚本会归档 data/ 和 uploads/。Caddy 证书由 Docker 命名卷持久化，不属于业务归档；升级、停止和恢复时都不要带 -v 删除命名卷。

## 6. 校验 Compose 和 Caddy 配置

在仓库根目录执行：

~~~bash
docker compose config
docker compose run --rm --no-deps caddy \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
~~~

重点确认：

- Compose 中存在 backend、frontend、caddy 三个服务。
- frontend 使用 expose: ["80"]，没有 80:80 宿主机端口映射。
- caddy 映射 80:80 和 443:443。
- deploy/Caddyfile 被只读挂载到 /etc/caddy/Caddyfile。
- caddy_data、caddy_config 两个命名卷存在于 Compose 配置中。

## 7. 构建与启动

首次部署或配置变更后执行：

~~~bash
mkdir -p data uploads model-cache backups
docker compose up -d --build
docker compose ps
~~~

预期状态：

~~~text
backend   healthy
frontend  running
caddy     running
~~~

frontend 会等待 backend 健康后启动；Caddy 通过 Compose 网络将请求转发到 frontend:80。

查看启动日志：

~~~bash
docker compose logs -f --tail=200 caddy
docker compose logs -f --tail=200 frontend
docker compose logs -f --tail=200 backend
~~~

Caddy 首次启动时应出现域名、证书或 ACME 相关日志。首次本地 Embedding 使用前，可以检查模型：

~~~bash
docker compose exec backend python -m app.scripts.verify_embedding
du -sh model-cache
~~~

## 8. HTTPS 与应用验收

### 8.1 HTTP 自动跳转

~~~bash
curl -I http://mauriceliang.xyz
~~~

预期返回 301 或 308，并包含：

~~~text
Location: https://mauriceliang.xyz/
~~~

### 8.2 HTTPS 证书

~~~bash
curl -I https://mauriceliang.xyz
curl -v https://mauriceliang.xyz
~~~

不得出现：

~~~text
certificate verify failed
connection refused
SSL error
~~~

### 8.3 API 健康检查

~~~bash
curl -fsS https://mauriceliang.xyz/api/health
~~~

应返回 FastAPI 健康状态。请求链为：

~~~text
HTTPS 443 → Caddy → frontend:80 → /api → backend:8000
~~~

API 文档：

- https://mauriceliang.xyz/docs
- https://mauriceliang.xyz/redoc
- https://mauriceliang.xyz/openapi.json

### 8.4 Vue 路由、SSE 和文件上传

浏览器统一访问：

~~~text
https://mauriceliang.xyz
~~~

依次验证：

1. 首页加载后，直接访问并刷新 /system、/documents、/evaluations 和 /retrieval-experiments，确认没有 404。
2. 进入 AI 问答页发送问题，确认回答逐步流式出现，而不是等待结束后一次性返回。
3. 检查来源面板、材料清单工具和知识缺口记录。
4. 上传 TXT、PDF、DOCX、DOC，确认上传、解析和知识库导入均正常。

现有 frontend/nginx.conf 中的以下配置必须保留，以保证 SSE 和 Vue Router 正常工作：

~~~nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 3600s;
try_files $uri $uri/ /index.html;
~~~

前端 API 继续使用同源路径：

~~~dotenv
VITE_API_BASE_URL=/api
~~~

不要改为 https://mauriceliang.xyz:8000/api 或 http://backend:8000。

## 9. 运维命令

~~~bash
# 启动 / 重建
docker compose up -d --build

# 查看状态和日志
docker compose ps
docker compose logs -f --tail=200 caddy
docker compose logs -f --tail=200 frontend
docker compose logs -f --tail=200 backend

# 停止和重启
docker compose stop
docker compose restart

# 删除容器和网络，但保留宿主机数据与命名卷
docker compose down
~~~

不要使用：

~~~bash
docker compose down -v
~~~

该命令会删除 caddy_data 和 caddy_config，可能导致证书状态丢失。证书丢失后 Caddy 可以重新申请，但会增加恢复时间并受 ACME 速率限制影响。

检查 Caddy 命名卷：

~~~bash
docker volume ls | grep caddy
~~~

应能看到项目对应的 caddy_data 和 caddy_config 卷。

## 10. 备份、恢复与升级

### 备份

~~~bash
./deploy/backup.sh
find backups -maxdepth 2 -type f
~~~

备份包位于 backups/<时间戳>/laborqa-runtime.tar.gz，包含 SQLite、FAISS 和上传文件；模型缓存和 Caddy 命名卷不进入该归档。

### 恢复

恢复会先停止服务，并在替换前创建快照：

~~~bash
./deploy/restore.sh backups/<时间戳>/laborqa-runtime.tar.gz
docker compose ps
curl -fsS https://mauriceliang.xyz/api/health
~~~

恢复操作会替换当前 data/ 和 uploads/，执行前确认备份路径正确；脚本不会使用 down -v，因此不会删除 Caddy 证书卷。

### 升级

每次升级先备份，再拉取代码、重建并启动：

~~~bash
./deploy/backup.sh
git pull origin main
docker compose up -d --build
docker compose ps
docker compose logs --tail=200 caddy
docker compose logs --tail=200 backend
~~~

升级后至少检查首页、HTTPS 证书、/api/health、资料上传和问答流式输出。

### 回滚

升级前记录稳定 commit。发生严重故障时切回已确认的稳定版本，然后重建服务：

~~~bash
git rev-parse HEAD
# 按团队发布流程切换到稳定 commit
docker compose up -d --build
docker compose ps
~~~

本次 HTTPS 接入不修改 SQLite、FAISS、上传文件和业务代码；如果故障涉及运行数据，再恢复对应业务备份。

## 11. 常见故障

### Caddy 无法启动

如果日志包含 bind: address already in use：

~~~bash
docker compose logs caddy
sudo ss -lntp | grep -E ':80|:443'
~~~

关闭占用 80/443 的宿主机服务后重新启动 Caddy。

### 证书申请失败

依次确认：

~~~bash
dig +short A mauriceliang.xyz
curl -I http://mauriceliang.xyz
docker compose logs --tail=200 caddy
~~~

并检查云安全组、防火墙、80/443 端口、错误 AAAA 记录和域名是否已经解析到当前服务器。

### HTTPS 正常但 API 失败

~~~bash
docker compose ps
docker compose logs --tail=200 frontend
docker compose logs --tail=200 backend
curl -fsS https://mauriceliang.xyz/api/health
docker compose exec frontend wget -qO- http://backend:8000/api/health
~~~

如果 Compose 内部请求正常而公网请求失败，重点检查 Caddy 到 frontend 的代理链；如果内部请求也失败，检查 frontend 到 backend 的网络和 backend 健康状态。

### SSE 回答一次性出现

确认 frontend/nginx.conf 仍包含 proxy_buffering off、proxy_cache off 和足够长的 proxy_read_timeout，然后重建 frontend：

~~~bash
docker compose build frontend
docker compose up -d frontend
~~~

### 上传文件超过限制

Nginx 默认限制为 25 MB，后端业务限制默认为 20 MB。调整时需要同步修改 deploy/.env 的 MAX_UPLOAD_SIZE_MB 和 frontend/nginx.conf 的 client_max_body_size，然后重建相关容器。

### 旧版 DOC 导入失败

~~~bash
docker compose exec backend which libreoffice
curl -fsS https://mauriceliang.xyz/api/health
~~~

确认 doc_converter 为 ready，并检查 backend 日志。

## 12. 最终验收清单

~~~text
[ ] DNS A 记录指向当前服务器
[ ] AAAA 记录正确或已删除
[ ] 80/TCP、443/TCP 已开放
[ ] 宿主机没有其他服务占用 80/443
[ ] frontend 不再绑定宿主机 80
[ ] Caddy 绑定 80 和 443
[ ] Caddyfile 域名正确
[ ] caddy_data、caddy_config 已持久化
[ ] docker compose config 通过
[ ] backend healthy
[ ] frontend running
[ ] caddy running
[ ] HTTP 自动跳转 HTTPS
[ ] HTTPS 证书有效
[ ] /api/health 正常
[ ] Vue 页面和路由刷新正常
[ ] SSE 流式回答正常
[ ] 文件上传和导入正常
[ ] Safari、Chrome、Edge 可访问
~~~

正式入口：

~~~text
https://mauriceliang.xyz
~~~

HTTP 入口 http://mauriceliang.xyz 只负责自动跳转到 HTTPS。
