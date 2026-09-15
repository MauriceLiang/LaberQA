# 劳动权益咨询问答台

Phase 0 初始化：FastAPI 后端与 Vue 3 前端骨架。

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

下载并验证本地 Embedding 模型（首次运行需要网络）：

```sh
cd backend
.venv/bin/python -m app.scripts.verify_embedding
```

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

## Phase 1 接口契约

FastAPI 的 `/openapi.json` 是 REST 契约源。启动后端后，在前端目录生成机器维护的 REST 类型：

```sh
cd frontend
npm run generate:api-types
```

SSE 事件类型手工维护在 `frontend/src/types/sse.ts`。Phase 1 的业务路由只发布请求/响应契约，尚未实现的业务操作会返回 HTTP 501；后续阶段逐步接入真实服务。

Phase 1 已冻结 Embedding 配置与 `EmbeddingSignature`/`IndexMeta` 数据结构。Provider 切换和 FAISS 元数据兼容校验按开发流程拆解安排在 Phase 2（BE-DOC-08～11）；在该阶段完成前，设置 `EMBEDDING_PROVIDER=api` 时向量编码会明确报错，不会回退到本地模型。
