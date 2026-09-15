"""SQLite persistence for sessions and their chat messages."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings


class SessionNotFoundError(LookupError):
    """Raised when a write references a session that does not exist."""


class SessionRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or settings.database_path

    def create_session(self, title: str | None = None) -> dict[str, Any]:
        session_id = str(uuid4())
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO session (id, title) VALUES (?, ?)",
                (session_id, title),
            )
            row = connection.execute(
                "SELECT * FROM session WHERE id = ?", (session_id,)
            ).fetchone()
            return dict(row)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM session WHERE id = ?", (session_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM message
                WHERE session_id = ?
                ORDER BY created_at, id
                """,
                (session_id,),
            ).fetchall()
            return self._load_messages(connection, rows)

    def get_recent_context(
        self, session_id: str, turns: int = 3
    ) -> list[dict[str, Any]]:
        if turns < 0:
            raise ValueError("turns must not be negative")
        if turns == 0:
            return []

        with self._connection() as connection:
            rows = connection.execute(
                """
                WITH ordered_messages AS (
                    SELECT
                        id,
                        role,
                        created_at,
                        LAG(id) OVER (ORDER BY created_at, id) AS previous_id,
                        LAG(role) OVER (ORDER BY created_at, id) AS previous_role
                    FROM message
                    WHERE session_id = ?
                ), recent_turns AS (
                    SELECT previous_id AS user_id, id AS assistant_id
                    FROM ordered_messages
                    WHERE role = 'assistant' AND previous_role = 'user'
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                )
                SELECT * FROM message
                WHERE id IN (
                    SELECT user_id FROM recent_turns
                    UNION ALL
                    SELECT assistant_id FROM recent_turns
                )
                ORDER BY created_at, id
                """,
                (session_id, turns),
            ).fetchall()
            return self._load_messages(connection, rows)

    def create_user_message(self, session_id: str, question: str) -> dict[str, Any]:
        with self._connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM session WHERE id = ?", (session_id,)
                ).fetchone()
                is None
            ):
                raise SessionNotFoundError(session_id)
            cursor = connection.execute(
                """
                INSERT INTO message (session_id, role, content, rewritten_question)
                VALUES (?, 'user', ?, ?)
                """,
                (session_id, question, question),
            )
            connection.execute(
                "UPDATE session SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )
            row = connection.execute(
                "SELECT * FROM message WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return self._load_messages(connection, [row])[0]

    def set_rewritten_question(self, message_id: int, text: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE message SET rewritten_question = ?
                WHERE id = ? AND role = 'user'
                """,
                (text, message_id),
            )
            return cursor.rowcount == 1

    def persist_assistant(
        self,
        session_id: str,
        content: str,
        answer_style: str,
        refused: bool,
        citations: Sequence[Mapping[str, Any]],
        tool_executions: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        with self._connection() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM session WHERE id = ?", (session_id,)
                ).fetchone()
                is None
            ):
                raise SessionNotFoundError(session_id)

            cursor = connection.execute(
                """
                INSERT INTO message (session_id, role, content, answer_style, refused)
                VALUES (?, 'assistant', ?, ?, ?)
                """,
                (session_id, content, answer_style, int(refused)),
            )
            message_id = int(cursor.lastrowid)

            for citation in citations:
                connection.execute(
                    """
                    INSERT INTO citation (
                        message_id, chunk_id, score, retrieval_score,
                        rerank_score, rank_no
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        citation["chunk_id"],
                        citation["score"],
                        citation["retrieval_score"],
                        citation.get("rerank_score"),
                        citation["rank_no"],
                    ),
                )

            for execution in tool_executions:
                connection.execute(
                    """
                    INSERT INTO tool_execution (
                        message_id, tool_name, input_json, output_json
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        execution["tool_name"],
                        json.dumps(execution["input"], ensure_ascii=False),
                        json.dumps(execution["output"], ensure_ascii=False),
                    ),
                )

            connection.execute(
                "UPDATE session SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )
            row = connection.execute(
                "SELECT * FROM message WHERE id = ?", (message_id,)
            ).fetchone()
            return self._load_messages(connection, [row])[0]

    @staticmethod
    def _load_messages(
        connection: sqlite3.Connection, rows: Sequence[sqlite3.Row]
    ) -> list[dict[str, Any]]:
        messages = [
            {
                "id": int(row["id"]),
                "session_id": row["session_id"],
                "role": row["role"],
                "content": row["content"],
                "rewritten_question": row["rewritten_question"],
                "answer_style": row["answer_style"],
                "refused": bool(row["refused"]) if row["refused"] is not None else None,
                "created_at": row["created_at"],
                "citations": [],
                "tool_executions": [],
            }
            for row in rows
        ]
        if not messages:
            return messages

        by_id = {message["id"]: message for message in messages}
        placeholders = ", ".join("?" for _ in by_id)
        message_ids = list(by_id)
        citation_rows = connection.execute(
            f"""
            SELECT
                c.message_id, c.chunk_id, ch.document_id, d.file_name,
                ch.chunk_no, ch.content, c.score, c.retrieval_score,
                c.rerank_score, c.rank_no
            FROM citation AS c
            JOIN chunk AS ch ON ch.id = c.chunk_id
            JOIN document AS d ON d.id = ch.document_id
            WHERE c.message_id IN ({placeholders})
            ORDER BY c.message_id, c.rank_no, c.id
            """,
            message_ids,
        ).fetchall()
        for row in citation_rows:
            by_id[int(row["message_id"])]["citations"].append(
                {
                    "chunk_id": int(row["chunk_id"]),
                    "document_id": int(row["document_id"]),
                    "file_name": row["file_name"],
                    "chunk_no": int(row["chunk_no"]),
                    "content": row["content"],
                    "score": float(row["score"]),
                    "retrieval_score": float(row["retrieval_score"]),
                    "rerank_score": (
                        float(row["rerank_score"])
                        if row["rerank_score"] is not None
                        else None
                    ),
                    "rank_no": int(row["rank_no"]),
                }
            )

        execution_rows = connection.execute(
            f"""
            SELECT message_id, tool_name, input_json, output_json
            FROM tool_execution
            WHERE message_id IN ({placeholders})
            ORDER BY message_id, created_at, id
            """,
            message_ids,
        ).fetchall()
        for row in execution_rows:
            by_id[int(row["message_id"])]["tool_executions"].append(
                {
                    "tool_name": row["tool_name"],
                    "input": json.loads(row["input_json"]),
                    "output": json.loads(row["output_json"]),
                }
            )
        return messages

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.database_path), timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()
