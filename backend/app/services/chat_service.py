"""Session-aware RAG orchestration and Server-Sent Events serialization."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Request

from app.core.config import Settings, settings
from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.schemas.contracts import ChatRequest
from app.services.embedding import EmbeddingUnavailableError
from app.services.llm import LlmClient, ModelUnavailableError
from app.services.retrieval import RetrievalService
from app.services.vector_store import (
    VectorStoreNotInitialized,
    VectorStorePersistenceError,
    VectorStoreSignatureMismatch,
)

logger = logging.getLogger(__name__)
_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
_REFUSAL = (
    "目前知识库中的资料不足以支持对这个问题作出可靠判断。请补充相关资料后再咨询。"
)


class ChatService:
    def __init__(
        self,
        session_service: Any,
        retrieval_service: RetrievalService,
        config: Settings = settings,
        *,
        llm_client: LlmClient | None = None,
    ) -> None:
        self.session_service = session_service
        self.retrieval_service = retrieval_service
        self.config = config
        self.llm_client = llm_client or LlmClient(config)

    def create_session(self, title: str | None) -> dict[str, Any]:
        return self.session_service.create_session(title)

    def get_session(self, session_id: UUID) -> dict[str, Any] | None:
        return self.session_service.get_session(session_id)

    def list_messages(self, session_id: UUID) -> list[dict[str, Any]]:
        return self.session_service.list_messages(session_id)

    async def stream_chat(self, payload: ChatRequest, request: Request):
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
            evidence = self.retrieval_service.retrieve(rewritten_question)
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

        refused = await self._should_refuse(rewritten_question, evidence)
        if await request.is_disconnected():
            return

        answer_parts: list[str] = []
        if refused:
            answer_parts.append(_REFUSAL)
            yield _sse("token", {"content": _REFUSAL})
        else:
            messages = self._answer_messages(
                payload, question, rewritten_question, evidence
            )
            try:
                async for token in self.llm_client.stream(messages):
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
                tool_executions=[],
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

    async def _rewrite_question(
        self, history: list[dict[str, Any]], question: str
    ) -> str:
        if not history:
            return question
        system_prompt = (_PROMPT_DIR / "question_rewrite.txt").read_text(
            encoding="utf-8"
        )
        context = [
            {"role": item["role"], "content": item["content"]} for item in history
        ]
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {"history": context, "current_question": question},
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            result = (await self.llm_client.complete(messages)).strip().strip('"“”')
            return result if result else question
        except Exception:
            logger.warning(
                "Question rewrite failed; using the original question", exc_info=True
            )
            return question

    async def _should_refuse(
        self, question: str, evidence: list[dict[str, Any]]
    ) -> bool:
        if (
            not evidence
            or max(item["retrieval_score"] for item in evidence)
            < self.config.rag_score_threshold
        ):
            return True

        prompt = (_PROMPT_DIR / "evidence_judge.txt").read_text(encoding="utf-8")
        try:
            result = await self.llm_client.complete(
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"question": question, "evidence": evidence},
                            ensure_ascii=False,
                        ),
                    },
                ],
                json_mode=True,
            )
            judgement = json.loads(result)
            return (
                not isinstance(judgement.get("sufficient"), bool)
                or not judgement["sufficient"]
            )
        except Exception:
            logger.warning("Evidence judge failed; refusing the answer", exc_info=True)
            return True

    @staticmethod
    def _answer_messages(
        payload: ChatRequest,
        question: str,
        rewritten_question: str,
        evidence: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        template = (_PROMPT_DIR / "answer_system.txt").read_text(encoding="utf-8")
        replacements = {
            "{{answer_style}}": payload.answer_style.value,
            "{{compliance_required}}": "false",
            "{{tool_result}}": "无",
            "{{question}}": question,
            "{{rewritten_question}}": rewritten_question,
            "{{context}}": "\n\n".join(
                f"[Evidence {item['rank_no']}] {item['content']}" for item in evidence
            ),
        }
        for placeholder, value in replacements.items():
            template = template.replace(placeholder, value)
        return [
            {"role": "system", "content": template},
            {"role": "user", "content": "请根据上述约束与证据回答问题。"},
        ]


def _sse(event: str, data: dict[str, Any]) -> str:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {encoded}\n\n"
