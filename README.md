# 劳动权益咨询问答台

Phase 4 已完成后端文档知识库、会话与核心 RAG 问答链路：支持文档导入与 FAISS 检索、会话隔离、最近三轮上下文、问题重写、证据门控、SSE 回答和来源持久化。聊天前端、Tool/合规扩展、评测和检索实验仍按后续阶段逐步实现。

## 环境要求

- Python 3.11
- Node.js 20.19+（当前项目也可使用较新的 LTS）
- 本地 Embedding 模型 `BAAI/bge-small-zh-v1.5`

## 后端

首次启动前，在仓库根目录复制配置样例：

```sh
cp .env.example .env
```

依赖安装：

```sh
python3.11 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
```

安装测试与代码检查依赖：

```sh
cd backend
.venv/bin/python -m pip install -r requirements-dev.txt
```

下载并验证本地 Embedding 模型（首次运行需要网络）：

```sh
cd backend
.venv/bin/python -m app.scripts.verify_embedding
```

`.pdf`、`.docx`、`.txt` 可直接导入；旧版 `.doc` 需要本机安装 LibreOffice。默认上传上限为 20 MB，默认分块大小/重叠分别为 600/100 字符。备用 API Provider 使用 OpenAI-compatible Embeddings 请求：`POST {EMBEDDING_BASE_URL}/embeddings`，请求体包含 `model` 与 `input`；配置 Provider、模型、归一化方式或分块参数变化后，不兼容的 FAISS 索引会被标记并拒绝检索。

在线回答需要在仓库根目录 `.env` 中配置 OpenAI-compatible Chat Completions 的 `LLM_API_KEY`、`LLM_BASE_URL`（例如以 `/v1` 结尾）和 `LLM_MODEL`。RAG 默认检索 5 个片段，低于 `RAG_SCORE_THRESHOLD=0.35` 时拒答。可通过 `RERANK_ENABLED=true` 启用本地 `BAAI/bge-reranker-base` 重排；模型未缓存在 Hugging Face 本地缓存或重排失败时会告警并回退向量检索顺序。没有可用 LLM 时，问题改写退回原问题、证据判断失败则安全拒答；若回答生成阶段的模型请求失败，SSE 会发送 `error` 事件。

启动 API：

```sh
cd backend
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查地址：<http://127.0.0.1:8000/api/health>

## 前端

```sh
cd frontend
cp .env.example .env
npm install
npm run dev
```

前端默认运行于 <http://127.0.0.1:5173>，启动后会调用后端 `/api/health` 显示服务状态。

## API 与验收

FastAPI 的 `/openapi.json` 是 REST 契约源。启动后端后，在前端目录生成机器维护的 REST 类型：

```sh
cd frontend
npm run generate:api-types
```

SSE 事件类型手工维护在 `frontend/src/types/sse.ts`。已实现文档上传、列表、详情、Chunk 分页与重导入，以及会话创建、消息历史和 `/api/chat/stream`。上传接口返回 HTTP 202，后台处理状态可从文档详情查询；聊天接口使用 `token → sources → done` 或终止 `error` 事件。Tool、合规提示、评测、缺失知识和检索实验仍暂时保留 HTTP 501 契约响应。

在后端目录运行验收与静态检查：

```sh
cd backend
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests
.venv/bin/ruff format --check app tests
```

验收通过后，测试使用进程内 FastAPI TestClient，不会持续占用 HTTP 端口。手动启动的 API 服务可用 `Ctrl+C` 关闭。
