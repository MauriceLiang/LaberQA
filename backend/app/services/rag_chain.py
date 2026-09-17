"""LangChain orchestration for the application's evidence-first RAG flow."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableBranch, RunnableLambda

from app.core.config import Settings, settings
from app.schemas.contracts import AnswerStyle, ToolExecutionItem
from app.services.compliance import COMPLIANCE_NOTICE
from app.services.llm import (
    LlmClient,
    LlmRunnable,
    ModelUnavailableError,
    messages_to_dicts,
)
from app.services.missing_knowledge import MissingKnowledgeReason
from app.services.retrieval import LaborKnowledgeRetriever, RetrievalService

logger = logging.getLogger(__name__)
_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"

REFUSAL_TEXT = (
    "目前知识库中的资料不足以支持对这个问题作出可靠判断。请补充相关资料后再咨询。"
)
ANSWER_STYLE_INSTRUCTIONS = {
    "plain": "面向普通劳动者，少用专业术语，先给简明结论，再解释依据和可执行建议。",
    "legal": "使用严谨、客观的表达，明确说明证据支持的适用条件、事实前提与结论边界。",
}


class RagChain:
    """Shared LangChain retriever, prompt and model orchestration.

    The existing retrieval service remains responsible for the project's FAISS
    index, SQLite metadata and reranking rules. This class makes the production
    query path use LangChain's Retriever, Prompt and Runnable interfaces while
    preserving the application's API and persistence contracts.
    """

    def __init__(
        self,
        retrieval_service: RetrievalService,
        llm_client: LlmClient,
        config: Settings = settings,
    ) -> None:
        self.retriever = LaborKnowledgeRetriever(
            retrieval_service=retrieval_service,
            name="labor_knowledge_retriever",
        )
        self.llm_client = llm_client
        self.config = config
        self.answer_prompt = _answer_prompt()
        self.rewrite_prompt = _rewrite_prompt()
        self.evidence_prompt = _evidence_prompt()
        self._set_llm_client(llm_client)

    def _set_llm_client(self, client: LlmClient) -> None:
        self.llm_client = client
        self.rewrite_runnable = LlmRunnable(client)
        self.evidence_runnable = LlmRunnable(client, json_mode=True)
        self.answer_runnable = LlmRunnable(client)
        self.answer_chain = RunnableBranch(
            (lambda state: bool(state["refused"]), RunnableLambda(_refusal)),
            self.answer_prompt | self.answer_runnable,
        )

    def set_llm_client(self, client: LlmClient) -> None:
        """Keep all Runnable adapters bound to the current client instance."""

        self._set_llm_client(client)

    async def rewrite_question(
        self, history: list[dict[str, Any]], question: str
    ) -> str:
        if not history:
            return question
        context = [
            {"role": item["role"], "content": item["content"]} for item in history
        ]
        chain = self.rewrite_prompt | self.rewrite_runnable
        try:
            result = await chain.ainvoke(
                {
                    "context": json.dumps(
                        {"history": context, "current_question": question},
                        ensure_ascii=False,
                    )
                }
            )
            result = result.strip().strip('"“”')
            return result if result else question
        except Exception:
            logger.warning(
                "Question rewrite failed; using the original question", exc_info=True
            )
            return question

    async def retrieve(self, question: str) -> list[dict[str, Any]]:
        documents = await self.retriever.ainvoke(question)
        return [_evidence_from_document(document) for document in documents]

    async def judge_evidence(
        self,
        question: str,
        evidence: list[dict[str, Any]],
        *,
        strict: bool = False,
    ) -> tuple[bool, MissingKnowledgeReason | None]:
        if not evidence:
            return True, MissingKnowledgeReason.NO_RETRIEVAL_RESULT
        if (
            max(item["retrieval_score"] for item in evidence)
            < self.config.rag_score_threshold
        ):
            return True, MissingKnowledgeReason.LOW_RELEVANCE

        chain = self.evidence_prompt | self.evidence_runnable
        try:
            result = await chain.ainvoke(
                {
                    "payload": json.dumps(
                        {"question": question, "evidence": evidence},
                        ensure_ascii=False,
                    ),
                }
            )
            judgement = json.loads(result)
            if not isinstance(judgement.get("sufficient"), bool):
                return True, None
            if not judgement["sufficient"]:
                return True, MissingKnowledgeReason.INSUFFICIENT_EVIDENCE
            return False, None
        except ModelUnavailableError:
            if strict:
                raise
            logger.warning("Evidence judge failed; refusing the answer", exc_info=True)
            return True, None
        except Exception:
            logger.warning("Evidence judge failed; refusing the answer", exc_info=True)
            return True, None

    def answer_prompt_value(
        self,
        answer_style: AnswerStyle,
        question: str,
        rewritten_question: str,
        evidence: list[dict[str, Any]],
        compliance_required: bool,
        tool_execution: ToolExecutionItem | None,
    ) -> Any:
        compliance_instruction = (
            f"回答末尾必须逐字包含以下提示：{COMPLIANCE_NOTICE}"
            if compliance_required
            else "当前规则未要求固定提示；回答仍须遵守证据约束。"
        )
        return self.answer_prompt.invoke(
            {
                "answer_style": answer_style.value,
                "answer_style_instructions": ANSWER_STYLE_INSTRUCTIONS[
                    answer_style.value
                ],
                "compliance_required": str(compliance_required).lower(),
                "compliance_instruction": compliance_instruction,
                "tool_result": _tool_result(tool_execution),
                "question": question,
                "rewritten_question": rewritten_question,
                "context": _format_evidence(evidence),
            }
        )

    async def complete_answer(
        self,
        answer_style: AnswerStyle,
        question: str,
        rewritten_question: str,
        evidence: list[dict[str, Any]],
        compliance_required: bool,
        tool_execution: ToolExecutionItem | None,
        *,
        refused: bool = False,
    ) -> str:
        return (
            await self.answer_chain.ainvoke(
                _answer_input(
                    answer_style,
                    question,
                    rewritten_question,
                    evidence,
                    compliance_required,
                    tool_execution,
                    refused=refused,
                )
            )
        ).strip()

    async def stream_answer(
        self,
        answer_style: AnswerStyle,
        question: str,
        rewritten_question: str,
        evidence: list[dict[str, Any]],
        compliance_required: bool,
        tool_execution: ToolExecutionItem | None,
        *,
        refused: bool = False,
    ) -> AsyncIterator[str]:
        async for token in self.answer_chain.astream(
            _answer_input(
                answer_style,
                question,
                rewritten_question,
                evidence,
                compliance_required,
                tool_execution,
                refused=refused,
            )
        ):
            yield token

    def answer_messages(
        self,
        answer_style: AnswerStyle,
        question: str,
        rewritten_question: str,
        evidence: list[dict[str, Any]],
        compliance_required: bool,
        tool_execution: ToolExecutionItem | None,
    ) -> list[dict[str, str]]:
        """Return rendered messages for compatibility with diagnostics and tests."""

        return messages_to_dicts(
            self.answer_prompt_value(
                answer_style,
                question,
                rewritten_question,
                evidence,
                compliance_required,
                tool_execution,
            )
        )


def _evidence_from_document(document: Document) -> dict[str, Any]:
    metadata = document.metadata
    return {
        "chunk_id": int(metadata["chunk_id"]),
        "document_id": int(metadata["document_id"]),
        "file_name": str(metadata["file_name"]),
        "chunk_no": int(metadata["chunk_no"]),
        "content": document.page_content,
        "score": float(metadata["score"]),
        "retrieval_score": float(metadata["retrieval_score"]),
        "rerank_score": metadata.get("rerank_score"),
        "rank_no": int(metadata["rank_no"]),
    }


def _answer_prompt() -> ChatPromptTemplate:
    template = (_PROMPT_DIR / "answer_system.txt").read_text(encoding="utf-8")
    for name in (
        "answer_style",
        "answer_style_instructions",
        "compliance_required",
        "compliance_instruction",
        "tool_result",
        "question",
        "rewritten_question",
        "context",
    ):
        template = template.replace(f"{{{{{name}}}}}", f"{{{name}}}")
    return ChatPromptTemplate.from_messages(
        [
            ("system", template),
            ("human", "请根据上述约束与证据回答问题。"),
        ],
        template_format="f-string",
    )


def _rewrite_prompt() -> ChatPromptTemplate:
    template = _escape_fstring_literals(
        (_PROMPT_DIR / "question_rewrite.txt").read_text(encoding="utf-8")
    )
    return ChatPromptTemplate.from_messages(
        [
            ("system", template),
            ("human", "对话上下文与当前问题：\n{context}"),
        ],
        template_format="f-string",
    )


def _evidence_prompt() -> ChatPromptTemplate:
    template = _escape_fstring_literals(
        (_PROMPT_DIR / "evidence_judge.txt").read_text(encoding="utf-8")
    )
    return ChatPromptTemplate.from_messages(
        [
            ("system", template),
            ("human", "{payload}"),
        ],
        template_format="f-string",
    )


def _escape_fstring_literals(value: str) -> str:
    return value.replace("{", "{{").replace("}", "}}")


def _format_evidence(evidence: Sequence[Mapping[str, Any]]) -> str:
    return "\n\n".join(
        f"[Evidence {item['rank_no']}] {item['content']}" for item in evidence
    )


def _tool_result(tool_execution: ToolExecutionItem | None) -> str:
    if tool_execution is None:
        return "无"
    return json.dumps(tool_execution.output.model_dump(mode="json"), ensure_ascii=False)


def _answer_input(
    answer_style: AnswerStyle,
    question: str,
    rewritten_question: str,
    evidence: Sequence[Mapping[str, Any]],
    compliance_required: bool,
    tool_execution: ToolExecutionItem | None,
    *,
    refused: bool,
) -> dict[str, Any]:
    return {
        "refused": refused,
        "answer_style": answer_style.value,
        "answer_style_instructions": ANSWER_STYLE_INSTRUCTIONS[answer_style.value],
        "compliance_required": str(compliance_required).lower(),
        "compliance_instruction": (
            f"回答末尾必须逐字包含以下提示：{COMPLIANCE_NOTICE}"
            if compliance_required
            else "当前规则未要求固定提示；回答仍须遵守证据约束。"
        ),
        "tool_result": _tool_result(tool_execution),
        "question": question,
        "rewritten_question": rewritten_question,
        "context": _format_evidence(evidence),
    }


def _refusal(_state: Mapping[str, Any]) -> str:
    return REFUSAL_TEXT
