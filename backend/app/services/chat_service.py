"""Session-aware RAG orchestration and Server-Sent Events serialization."""

from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any
from uuid import UUID

from fastapi import Request

from app.core.config import Settings, settings
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.contracts import (
    AnswerStyle,
    ChatRequest,
    MaterialChecklistInput,
    MissingKnowledgeQuery,
    MissingKnowledgeUpdate,
    ToolExecutionItem,
)
from app.services.compliance import COMPLIANCE_NOTICE, ComplianceRuleService
from app.services.embedding import EmbeddingUnavailableError
from app.services.llm import LlmClient, ModelUnavailableError
from app.services.material_checklist import MaterialChecklistTool, ToolDecisionService
from app.services.missing_knowledge import (
    ExecutionMode,
    MissingKnowledgeReason,
    MissingKnowledgeService,
)
from app.services.rag_chain import (
    ANSWER_STYLE_INSTRUCTIONS,
    REFUSAL_TEXT,
    RagChain,
)
from app.services.retrieval import RetrievalService
from app.services.vector_store import (
    VectorStoreNotInitialized,
    VectorStorePersistenceError,
    VectorStoreSignatureMismatch,
)

logger = logging.getLogger(__name__)
_REFUSAL = REFUSAL_TEXT
_ANSWER_STYLE_INSTRUCTIONS = ANSWER_STYLE_INSTRUCTIONS


class ChatService:
    def __init__(
        self,
        session_service: Any,
        retrieval_service: RetrievalService,
        config: Settings = settings,
        *,
        llm_client: LlmClient | None = None,
        missing_knowledge_service: MissingKnowledgeService | None = None,
    ) -> None:
        self.session_service = session_service
        self.retrieval_service = retrieval_service
        self.config = config
        self.llm_client = llm_client or LlmClient(config)
        self.rag_chain = RagChain(retrieval_service, self.llm_client, config)
        self.tool_decision_service = ToolDecisionService()
        self.material_checklist_tool = MaterialChecklistTool()
        self.compliance_rule_service = ComplianceRuleService()
        self.missing_knowledge_service = missing_knowledge_service or (
            MissingKnowledgeService(database_path=config.database_path)
        )

    def create_session(self, title: str | None) -> dict[str, Any]:
        return self.session_service.create_session(title)

    def get_session(self, session_id: UUID) -> dict[str, Any] | None:
        return self.session_service.get_session(session_id)

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.session_service.list_sessions(limit)

    def list_messages(self, session_id: UUID) -> list[dict[str, Any]]:
        return self.session_service.list_messages(session_id)

    def execute_material_checklist(
        self, payload: MaterialChecklistInput
    ) -> ToolExecutionItem:
        return self.material_checklist_tool.execute(payload)

    def list_missing_knowledge(
        self, query: MissingKnowledgeQuery
    ) -> tuple[list[dict[str, Any]], int]:
        return self.missing_knowledge_service.list(query)

    def update_missing_knowledge(
        self, item_id: int, payload: MissingKnowledgeUpdate
    ) -> dict[str, Any]:
        return self.missing_knowledge_service.update(item_id, payload)

    async def stream_chat(
        self,
        payload: ChatRequest,
        request: Request,
        *,
        execution_mode: ExecutionMode = ExecutionMode.PRODUCTION,
    ):
        if execution_mode != ExecutionMode.PRODUCTION:
            raise ValueError("stream_chat only supports PRODUCTION mode")
        session_id = payload.session_id
        question = payload.question
        try:
            history = self.session_service.get_recent_context(session_id, turns=3)
            user_message = self.session_service.create_user_message(
                session_id, question
            )
        except AppError as exc:
            yield _sse("error", {"code": int(exc.code), "message": exc.message})
            return
        except Exception:
            logger.exception("Could not read the session or save the user message")
            yield _sse(
                "error",
                {"code": int(ErrorCode.INTERNAL_ERROR), "message": "会话消息保存失败"},
            )
            return

        rewritten_question = await self._rewrite_question(history, question)
        try:
            self.session_service.set_rewritten_question(
                int(user_message["id"]), rewritten_question
            )
        except Exception:
            logger.exception("Could not persist the rewritten question")
            yield _sse(
                "error",
                {"code": int(ErrorCode.INTERNAL_ERROR), "message": "问题处理失败"},
            )
            return

        try:
            evidence = await self._retrieve_evidence(rewritten_question)
        except EmbeddingUnavailableError:
            yield _sse(
                "error",
                {
                    "code": int(ErrorCode.EMBEDDING_UNAVAILABLE),
                    "message": "向量服务暂不可用",
                },
            )
            return
        except VectorStoreNotInitialized:
            yield _sse(
                "error",
                {
                    "code": int(ErrorCode.KNOWLEDGE_BASE_NOT_READY),
                    "message": "知识库尚未就绪",
                },
            )
            return
        except VectorStoreSignatureMismatch:
            yield _sse(
                "error",
                {
                    "code": int(ErrorCode.INDEX_EMBEDDING_MISMATCH),
                    "message": "向量索引与当前 Embedding 配置不兼容，请重建索引",
                },
            )
            return
        except VectorStorePersistenceError:
            yield _sse(
                "error",
                {
                    "code": int(ErrorCode.KNOWLEDGE_BASE_NOT_READY),
                    "message": "知识库索引不可用",
                },
            )
            return
        except Exception:
            logger.exception("RAG retrieval failed")
            yield _sse(
                "error",
                {"code": int(ErrorCode.INTERNAL_ERROR), "message": "检索服务内部错误"},
            )
            return

        refused, refusal_reason = await self._judge_evidence(
            rewritten_question, evidence
        )
        if await request.is_disconnected():
            return

        record_missing_knowledge = (
            refused
            and refusal_reason is not None
            and execution_mode == ExecutionMode.PRODUCTION
        )

        compliance_required = self.compliance_rule_service.requires_notice(
            question, rewritten_question
        )
        answer_parts: list[str] = []
        tool_executions: list[ToolExecutionItem] = []
        if refused:
            if record_missing_knowledge and refusal_reason is not None:
                try:
                    self.missing_knowledge_service.record_refusal(
                        rewritten_question, refusal_reason
                    )
                except Exception:
                    logger.exception(
                        "Failed to record a production evidence-gate refusal",
                    )
        else:
            tool_input = self.tool_decision_service.decide(question, rewritten_question)
            if tool_input is not None:
                try:
                    execution = self.material_checklist_tool.execute(tool_input)
                except Exception:
                    logger.exception("Material checklist tool execution failed")
                    yield _sse(
                        "error",
                        {
                            "code": int(ErrorCode.INTERNAL_ERROR),
                            "message": "材料清单生成失败",
                        },
                    )
                    return
                if await request.is_disconnected():
                    return
                tool_executions.append(execution)
                yield _sse("tool", execution.model_dump(mode="json"))

        try:
            async for token in self.rag_chain.stream_answer(
                payload.answer_style,
                question,
                rewritten_question,
                evidence,
                compliance_required,
                tool_executions[0] if tool_executions else None,
                refused=refused,
            ):
                if await request.is_disconnected():
                    return
                answer_parts.append(token)
                yield _sse("token", {"content": token})
        except ModelUnavailableError:
            yield _sse(
                "error",
                {
                    "code": int(ErrorCode.MODEL_UNAVAILABLE),
                    "message": "模型服务暂不可用",
                },
            )
            return
        except Exception:
            logger.exception("LLM response stream failed")
            yield _sse(
                "error",
                {
                    "code": int(ErrorCode.MODEL_UNAVAILABLE),
                    "message": "模型服务暂不可用",
                },
            )
            return

        if not answer_parts:
            yield _sse(
                "error",
                {
                    "code": int(ErrorCode.MODEL_UNAVAILABLE),
                    "message": "模型未返回回答内容",
                },
            )
            return

        completed_answer = "".join(answer_parts)
        compliance_required = compliance_required or (
            self.compliance_rule_service.requires_notice(
                question, rewritten_question, completed_answer
            )
        )
        if compliance_required and COMPLIANCE_NOTICE not in completed_answer:
            notice = f"\n\n{COMPLIANCE_NOTICE}"
            answer_parts.append(notice)
            yield _sse("token", {"content": notice})
        if await request.is_disconnected():
            return

        yield _sse("sources", {"items": [] if refused else evidence})
        if await request.is_disconnected():
            return

        try:
            assistant_message = self.session_service.persist_assistant(
                session_id=session_id,
                content="".join(answer_parts),
                answer_style=payload.answer_style.value,
                refused=refused,
                citations=[] if refused else evidence,
                tool_executions=tool_executions,
            )
        except Exception:
            logger.exception("Could not persist completed assistant response")
            yield _sse(
                "error",
                {"code": int(ErrorCode.INTERNAL_ERROR), "message": "回答保存失败"},
            )
            return

        yield _sse(
            "done",
            {
                "message_id": int(assistant_message["id"]),
                "answer_style": payload.answer_style.value,
                "refused": refused,
            },
        )

    async def answer_once(
        self,
        question: str,
        history: list[dict[str, Any]],
        answer_style: AnswerStyle,
        *,
        mode: ExecutionMode,
    ) -> dict[str, Any]:
        """Run the production RAG decision path without persisting chat state."""
        if mode not in (ExecutionMode.EVALUATION, ExecutionMode.EXPERIMENT):
            raise ValueError("answer_once only supports non-production modes")

        rewritten_question = await self._rewrite_question(history, question)
        retrieval_started = perf_counter()
        evidence = await self._retrieve_evidence(rewritten_question)
        retrieval_ms = round((perf_counter() - retrieval_started) * 1000)
        refused, _ = await self._judge_evidence(
            rewritten_question, evidence, strict=True
        )
        tool_execution = (
            self.tool_decision_service.decide(question, rewritten_question)
            if not refused
            else None
        )
        tool_result = (
            self.material_checklist_tool.execute(tool_execution)
            if tool_execution is not None
            else None
        )
        compliance_required = self.compliance_rule_service.requires_notice(
            question, rewritten_question
        )
        answer = await self.rag_chain.complete_answer(
            answer_style,
            question,
            rewritten_question,
            evidence,
            compliance_required,
            tool_result,
            refused=refused,
        )
        if not answer:
            raise ModelUnavailableError("模型未返回回答内容")
        compliance_required = (
            compliance_required
            or self.compliance_rule_service.requires_notice(
                question, rewritten_question, answer
            )
        )
        if compliance_required and COMPLIANCE_NOTICE not in answer:
            answer = f"{answer}\n\n{COMPLIANCE_NOTICE}"
        return {
            "answer": answer,
            "refused": refused,
            "citations": [] if refused else evidence,
            "rewritten_question": rewritten_question,
            "retrieval_ms": retrieval_ms,
            "compliance_shown": COMPLIANCE_NOTICE in answer,
        }

    async def _rewrite_question(
        self, history: list[dict[str, Any]], question: str
    ) -> str:
        self._sync_rag_chain()
        return await self.rag_chain.rewrite_question(history, question)

    async def _retrieve_evidence(self, question: str) -> list[dict[str, Any]]:
        self._sync_rag_chain()
        return await self.rag_chain.retrieve(question)

    async def _judge_evidence(
        self,
        question: str,
        evidence: list[dict[str, Any]],
        *,
        strict: bool = False,
    ) -> tuple[bool, MissingKnowledgeReason | None]:
        self._sync_rag_chain()
        return await self.rag_chain.judge_evidence(question, evidence, strict=strict)

    def _answer_messages(
        self,
        answer_style: AnswerStyle,
        question: str,
        rewritten_question: str,
        evidence: list[dict[str, Any]],
        compliance_required: bool,
        tool_execution: ToolExecutionItem | None,
    ) -> list[dict[str, str]]:
        self._sync_rag_chain()
        return self.rag_chain.answer_messages(
            answer_style,
            question,
            rewritten_question,
            evidence,
            compliance_required,
            tool_execution,
        )

    def _sync_rag_chain(self) -> None:
        # Tests and callers may replace llm_client after construction; keep the
        # LangChain adapter bound to the current client.
        self.rag_chain.set_llm_client(self.llm_client)


def _sse(event: str, data: dict[str, Any]) -> str:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {encoded}\n\n"
