"""Session and message operations for chat workflows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.error_codes import ErrorCode
from app.core.errors import AppError
from app.repositories.session_repository import (
    SessionNotFoundError,
    SessionRepository,
)
from app.schemas.contracts import (
    AnswerStyle,
    CitationItem,
    MessageItem,
    SessionItem,
    ToolExecutionItem,
)


class SessionService:
    def __init__(
        self,
        *,
        repository: SessionRepository | None = None,
        database_path: Path | None = None,
    ) -> None:
        self.repository = repository or SessionRepository(database_path)

    def create_session(self, title: str | None = None) -> dict[str, Any]:
        return self._session_item(self.repository.create_session(title))

    def get_session(self, session_id: UUID | str) -> dict[str, Any] | None:
        row = self.repository.get_session(str(session_id))
        return self._session_item(row) if row is not None else None

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        return [self._session_item(row) for row in self.repository.list_sessions(limit)]

    def list_messages(self, session_id: UUID | str) -> list[dict[str, Any]]:
        normalized_id = str(session_id)
        self._require_session(normalized_id)
        return [
            self._message_item(row)
            for row in self.repository.list_messages(normalized_id)
        ]

    def get_recent_context(
        self, session_id: UUID | str, turns: int = 3
    ) -> list[dict[str, Any]]:
        normalized_id = str(session_id)
        self._require_session(normalized_id)
        return [
            self._message_item(row)
            for row in self.repository.get_recent_context(normalized_id, turns)
        ]

    def create_user_message(
        self, session_id: UUID | str, question: str
    ) -> dict[str, Any]:
        try:
            row = self.repository.create_user_message(str(session_id), question)
        except SessionNotFoundError as exc:
            raise self._session_not_found() from exc
        return self._message_item(row)

    def set_rewritten_question(self, message_id: int, text: str) -> None:
        if not self.repository.set_rewritten_question(message_id, text):
            raise ValueError("user message not found")

    def persist_assistant(
        self,
        session_id: UUID | str,
        content: str,
        answer_style: AnswerStyle | str,
        refused: bool,
        citations: Sequence[Mapping[str, Any] | CitationItem],
        tool_executions: Sequence[Mapping[str, Any] | ToolExecutionItem] = (),
    ) -> dict[str, Any]:
        citation_items = [
            CitationItem.model_validate(self._mapping(citation))
            for citation in citations
        ]
        execution_items = [
            ToolExecutionItem.model_validate(self._mapping(execution))
            for execution in tool_executions
        ]
        try:
            row = self.repository.persist_assistant(
                str(session_id),
                content,
                AnswerStyle(answer_style).value,
                refused,
                [
                    {
                        "chunk_id": citation.chunk_id,
                        "score": citation.score,
                        "retrieval_score": citation.retrieval_score,
                        "rerank_score": citation.rerank_score,
                        "rank_no": citation.rank_no,
                    }
                    for citation in citation_items
                ],
                [execution.model_dump(mode="json") for execution in execution_items],
            )
        except SessionNotFoundError as exc:
            raise self._session_not_found() from exc
        return self._message_item(row)

    def _require_session(self, session_id: str) -> None:
        if self.repository.get_session(session_id) is None:
            raise self._session_not_found()

    @staticmethod
    def _session_not_found() -> AppError:
        return AppError(ErrorCode.SESSION_NOT_FOUND, "会话不存在", http_status=404)

    @staticmethod
    def _session_item(row: Mapping[str, Any]) -> dict[str, Any]:
        return SessionItem.model_validate(row).model_dump(mode="json")

    @staticmethod
    def _message_item(row: Mapping[str, Any]) -> dict[str, Any]:
        return MessageItem.model_validate(row).model_dump(mode="json")

    @staticmethod
    def _mapping(value: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return dict(value)
