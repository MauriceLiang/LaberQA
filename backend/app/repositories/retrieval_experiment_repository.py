"""SQLite persistence for retrieval experiments and per-case results."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.config import settings


class RetrievalExperimentRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or settings.database_path

    def create_experiment(
        self,
        name: str,
        case_count: int,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        configs = snapshot.get("strategy_snapshots") or snapshot.get("configs", [])
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO retrieval_experiment (
                    name, case_count, progress_total, config_json
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    name,
                    case_count,
                    case_count * len(configs),
                    json.dumps(snapshot, ensure_ascii=False),
                ),
            )
            row = connection.execute(
                "SELECT * FROM retrieval_experiment WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            return self._summary(row)

    def set_running(self, experiment_id: int) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE retrieval_experiment
                SET status = 'RUNNING', updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (experiment_id,),
            )

    def add_result(self, experiment_id: int, result: dict[str, Any]) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO retrieval_experiment_result (
                    experiment_id, config_index, case_id, status,
                    retrieved_sources_json, source_hit, correct, refused,
                    retrieval_ms, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    result["config_index"],
                    result["case_id"],
                    result["status"],
                    json.dumps(result["retrieved_sources"], ensure_ascii=False),
                    _db_bool(result.get("source_hit")),
                    _db_bool(result.get("correct")),
                    _db_bool(result.get("refused")),
                    result.get("retrieval_ms"),
                    result.get("error_message"),
                ),
            )
            connection.execute(
                """
                UPDATE retrieval_experiment
                SET progress_current = progress_current + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (experiment_id,),
            )

    def complete_experiment(
        self,
        experiment_id: int,
        best_config_index: int | None,
        metrics: dict[str, float | None] | None,
    ) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE retrieval_experiment
                SET status = 'COMPLETED', error_message = NULL,
                    best_config_index = ?, accuracy = ?, reject_rate = ?,
                    citation_hit_rate = ?, avg_retrieval_ms = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    best_config_index,
                    metrics["accuracy"] if metrics else None,
                    metrics["reject_rate"] if metrics else None,
                    metrics["citation_hit_rate"] if metrics else None,
                    metrics["avg_retrieval_ms"] if metrics else None,
                    experiment_id,
                ),
            )

    def fail_experiment(self, experiment_id: int, message: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE retrieval_experiment
                SET status = 'FAILED', error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (message[:500], experiment_id),
            )

    def recover_interrupted_experiments(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE retrieval_experiment
                SET status = 'FAILED', error_message = '服务重启导致任务中断',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('PENDING', 'RUNNING')
                """
            )

    def list_experiments(
        self,
        *,
        page: int,
        size: int,
        status: str | None,
        include_archived: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if status:
            conditions.append("status = ?")
            parameters.append(status)
        if not include_archived:
            conditions.append("archived_at IS NULL")
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connection() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM retrieval_experiment {where_clause}",
                    parameters,
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT * FROM retrieval_experiment
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, size, (page - 1) * size],
            ).fetchall()
            return [self._summary(row) for row in rows], total

    def archive_experiment(self, experiment_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE retrieval_experiment
                SET archived_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status IN ('COMPLETED', 'FAILED')
                  AND archived_at IS NULL
                """,
                (experiment_id,),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM retrieval_experiment WHERE id = ?", (experiment_id,)
            ).fetchone()
            return self._summary(row) if row is not None else None

    def restore_experiment(self, experiment_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE retrieval_experiment
                SET archived_at = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND archived_at IS NOT NULL
                """,
                (experiment_id,),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM retrieval_experiment WHERE id = ?", (experiment_id,)
            ).fetchone()
            return self._summary(row) if row is not None else None

    def get_experiment(self, experiment_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM retrieval_experiment WHERE id = ?", (experiment_id,)
            ).fetchone()
            if row is None:
                return None
            results = connection.execute(
                """
                SELECT * FROM retrieval_experiment_result
                WHERE experiment_id = ? ORDER BY id
                """,
                (experiment_id,),
            ).fetchall()
            return {
                **self._summary(row),
                "snapshot": json.loads(row["config_json"]),
                "best_config_index": row["best_config_index"],
                "results": [self._result(item) for item in results],
            }

    def delete_experiment(self, experiment_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM retrieval_experiment WHERE id = ?", (experiment_id,)
            )
            return cursor.rowcount > 0

    @staticmethod
    def _summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "status": row["status"],
            "progress_current": int(row["progress_current"]),
            "progress_total": int(row["progress_total"]),
            "error_message": row["error_message"],
            "archived_at": row["archived_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _result(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "config_index": int(row["config_index"]),
            "case_id": int(row["case_id"]),
            "status": row["status"],
            "retrieved_sources": json.loads(row["retrieved_sources_json"]),
            "source_hit": _python_bool(row["source_hit"]),
            "correct": _python_bool(row["correct"]),
            "refused": _python_bool(row["refused"]),
            "retrieval_ms": row["retrieval_ms"],
            "error_message": row["error_message"],
        }

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


def _db_bool(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _python_bool(value: int | None) -> bool | None:
    return None if value is None else bool(value)
