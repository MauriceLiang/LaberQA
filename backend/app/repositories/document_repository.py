import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import settings


class DocumentRepository:
    """SQLite persistence for uploaded documents and their text chunks."""

    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or settings.database_path

    def create_document(
        self,
        *,
        file_name: str,
        file_type: str,
        file_path: str,
        status: str = "PROCESSING",
    ) -> dict[str, Any]:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO document (file_name, file_type, file_path, status)
                VALUES (?, ?, ?, ?)
                """,
                (file_name, file_type, file_path, status),
            )
            row = connection.execute(
                "SELECT * FROM document WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return dict(row)

    def get_document(self, document_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM document WHERE id = ?", (document_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def list_documents(
        self,
        *,
        page: int = 1,
        size: int = 20,
        status: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        if page < 1 or size < 1:
            raise ValueError("page and size must be positive")

        conditions: list[str] = []
        parameters: list[Any] = []
        if status is not None:
            conditions.append("status = ?")
            parameters.append(status)
        if keyword:
            conditions.append("file_name LIKE ? ESCAPE '\\'")
            escaped_keyword = (
                keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            parameters.append(f"%{escaped_keyword}%")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with self._connection() as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM document {where}", parameters
            ).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM document {where} "
                "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                [*parameters, size, (page - 1) * size],
            ).fetchall()
            return [dict(row) for row in rows], int(total)

    def update_document(
        self,
        document_id: int,
        *,
        status: str | None = None,
        error_message: str | None = None,
        chunk_count: int | None = None,
    ) -> dict[str, Any] | None:
        assignments = ["error_message = ?", "updated_at = CURRENT_TIMESTAMP"]
        values: list[Any] = [error_message]
        if status is not None:
            assignments.append("status = ?")
            values.append(status)
        if chunk_count is not None:
            assignments.append("chunk_count = ?")
            values.append(chunk_count)
        values.append(document_id)

        with self._connection() as connection:
            connection.execute(
                f"UPDATE document SET {', '.join(assignments)} WHERE id = ?", values
            )
            row = connection.execute(
                "SELECT * FROM document WHERE id = ?", (document_id,)
            ).fetchone()
            return dict(row) if row is not None else None

    def insert_chunks(
        self,
        document_id: int,
        chunks: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        inserted: list[dict[str, Any]] = []
        with self._connection() as connection:
            for chunk in chunks:
                cursor = connection.execute(
                    """
                    INSERT INTO chunk (document_id, chunk_no, content, vector_key)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        document_id,
                        int(chunk["chunk_no"]),
                        str(chunk["content"]),
                        f"pending-{uuid4()}",
                    ),
                )
                chunk_id = int(cursor.lastrowid)
                vector_key = f"chunk:{chunk_id}"
                connection.execute(
                    "UPDATE chunk SET vector_key = ? WHERE id = ?",
                    (vector_key, chunk_id),
                )
                row = connection.execute(
                    "SELECT * FROM chunk WHERE id = ?", (chunk_id,)
                ).fetchone()
                inserted.append(dict(row))
        return inserted

    def delete_chunks(self, document_id: int) -> list[int]:
        with self._connection() as connection:
            ids = [
                int(row[0])
                for row in connection.execute(
                    "SELECT id FROM chunk WHERE document_id = ? ORDER BY id",
                    (document_id,),
                ).fetchall()
            ]
            connection.execute(
                "DELETE FROM chunk WHERE document_id = ?", (document_id,)
            )
            return ids

    def list_chunks(
        self, document_id: int, *, page: int = 1, size: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        if page < 1 or size < 1:
            raise ValueError("page and size must be positive")
        with self._connection() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM chunk WHERE document_id = ?",
                    (document_id,),
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT * FROM chunk WHERE document_id = ?
                ORDER BY chunk_no, id LIMIT ? OFFSET ?
                """,
                (document_id, size, (page - 1) * size),
            ).fetchall()
            return [dict(row) for row in rows], total

    def list_success_chunks(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.*, d.file_name, d.file_type
                FROM chunk AS c
                JOIN document AS d ON d.id = c.document_id
                WHERE d.status = 'SUCCESS'
                ORDER BY c.document_id, c.chunk_no, c.id
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def list_success_documents(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT id, file_name, file_type, file_path
                FROM document
                WHERE status = 'SUCCESS'
                ORDER BY id
                """
            ).fetchall()
            return [dict(row) for row in rows]

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
