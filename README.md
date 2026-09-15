# 劳动权益咨询问答台

Phase 8 在 Phase 7 的问答与知识缺口功能基础上，加入固定 60 条问答评测集、异步评测批次、五项指标和逐题结果页面。检索策略实验仍属于后续阶段。

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

前端默认运行于 <http://127.0.0.1:5173>，首页为 AI 咨询；系统状态和资料管理可从顶部导航进入。

## API 与验收

FastAPI 的 `/openapi.json` 是 REST 契约源。启动后端后，在前端目录生成机器维护的 REST 类型：

```sh
cd frontend
npm run generate:api-types
```

SSE 事件类型手工维护在 `frontend/src/types/sse.ts`。已实现文档上传与管理、会话和流式问答、材料清单、缺失知识管理，以及 Phase 8 的 60 条评测。评测用例按 30 条库内单轮、10 条库内多轮、20 条库外/证据不足初始化；新环境需先导入名为 `法条文件.docx` 的项目法规汇编，使期望来源和引用命中检查对应。评测通过 `/api/evaluations/runs` 返回 HTTP 202 在后台执行，前端每 2 秒刷新批次进度。检索策略实验仍保留 HTTP 501 契约响应。

在后端目录运行验收与静态检查：

```sh
cd backend
.venv/bin/python -m pytest -q
.venv/bin/ruff check app tests
.venv/bin/ruff format --check app tests
```

验收通过后，测试使用进程内 FastAPI TestClient，不会持续占用 HTTP 端口。手动启动的 API 服务可用 `Ctrl+C` 关闭。
