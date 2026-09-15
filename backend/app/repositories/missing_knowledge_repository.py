"""SQLite persistence for knowledge gaps discovered by production refusals."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.config import settings


class MissingKnowledgeRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or settings.database_path

    def record(
        self, topic_key: str, sample_question: str, missing_area: str
    ) -> dict[str, Any]:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO missing_knowledge (topic_key, sample_question, missing_area)
                VALUES (?, ?, ?)
                ON CONFLICT(topic_key) DO UPDATE SET
                    count = missing_knowledge.count + 1,
                    last_seen_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (topic_key, sample_question, missing_area),
            )
            row = connection.execute(
                "SELECT * FROM missing_knowledge WHERE topic_key = ?", (topic_key,)
            ).fetchone()
            return dict(row)

    def list(
        self,
        *,
        page: int,
        size: int,
        status: str | None,
        keyword: str | None,
        sort: str,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)
        if keyword:
            escaped = (
                keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            conditions.append(
                "(topic_key LIKE ? ESCAPE char(92) "
                "OR sample_question LIKE ? ESCAPE char(92) "
                "OR missing_area LIKE ? ESCAPE char(92))"
            )
            pattern = f"%{escaped}%"
            parameters.extend((pattern, pattern, pattern))

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_clause = {
            "count_desc": "count DESC, last_seen_at DESC, id DESC",
            "last_seen_desc": "last_seen_at DESC, id DESC",
        }[sort]
        with self._connection() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM missing_knowledge {where_clause}", parameters
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT * FROM missing_knowledge
                {where_clause}
                ORDER BY {order_clause}
                LIMIT ? OFFSET ?
                """,
                [*parameters, size, (page - 1) * size],
            ).fetchall()
            return [dict(row) for row in rows], total

    def update(
        self, item_id: int, status: str, note: str | None
    ) -> dict[str, Any] | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE missing_knowledge
                SET status = ?, note = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, note, item_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM missing_knowledge WHERE id = ?", (item_id,)
            ).fetchone()
            return dict(row)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(str(self.database_path), timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()
