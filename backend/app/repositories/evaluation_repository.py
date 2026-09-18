"""SQLite persistence for evaluation cases, batches, and per-case results."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.config import settings


class EvaluationRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or settings.database_path

    def seed_cases(self, cases: Sequence[dict[str, Any]]) -> None:
        with self._connection() as connection:
            for position, case in enumerate(cases, start=1):
                builtin_key = f"baseline-{position}"
                exists = connection.execute(
                    "SELECT 1 FROM evaluation_case WHERE builtin_key = ?",
                    (builtin_key,),
                ).fetchone()
                if exists:
                    continue
                connection.execute(
                    """
                    INSERT INTO evaluation_case (
                        topic, expected_type, turns_json, expected_points_json,
                        expected_sources_json, should_show_compliance, origin,
                        status, version, builtin_key
                    ) VALUES (?, ?, ?, ?, ?, ?, 'BUILTIN', 'ACTIVE', 1, ?)
                    """,
                    (
                        case["topic"],
                        case["expected_type"],
                        json.dumps(case["turns"], ensure_ascii=False),
                        json.dumps(case["expected_points"], ensure_ascii=False),
                        json.dumps(case["expected_sources"], ensure_ascii=False),
                        int(case["should_show_compliance"]),
                        builtin_key,
                    ),
                )

    def list_cases(
        self,
        *,
        page: int,
        size: int,
        topic: str | None,
        expected_type: str | None,
        is_multi_turn: bool | None,
        origin: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions: list[str] = []
        parameters: list[Any] = []
        if topic:
            escaped = (
                topic.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            conditions.append("topic LIKE ? ESCAPE char(92)")
            parameters.append(f"%{escaped}%")
        if expected_type:
            conditions.append("expected_type = ?")
            parameters.append(expected_type)
        if is_multi_turn is not None:
            conditions.append(
                "json_array_length(turns_json) > 1"
                if is_multi_turn
                else "json_array_length(turns_json) = 1"
            )
        if origin:
            conditions.append("origin = ?")
            parameters.append(origin)
        if status:
            conditions.append("status = ?")
            parameters.append(status)
        elif not include_archived:
            conditions.append("status = 'ACTIVE'")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with self._connection() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM evaluation_case {where_clause}", parameters
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT * FROM evaluation_case
                {where_clause}
                ORDER BY id
                LIMIT ? OFFSET ?
                """,
                [*parameters, size, (page - 1) * size],
            ).fetchall()
            return [self._case_item(row) for row in rows], total

    def get_cases(
        self,
        case_ids: Sequence[int] | None = None,
        *,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        with self._connection() as connection:
            status_clause = "" if include_archived else " AND status = 'ACTIVE'"
            if case_ids is None:
                rows = connection.execute(
                    f"SELECT * FROM evaluation_case WHERE 1 = 1{status_clause} ORDER BY id"
                ).fetchall()
            elif not case_ids:
                return []
            else:
                placeholders = ",".join("?" for _ in case_ids)
                found = {
                    int(row["id"]): row
                    for row in connection.execute(
                        f"SELECT * FROM evaluation_case WHERE id IN ({placeholders}){status_clause}",
                        list(case_ids),
                    ).fetchall()
                }
                rows = [found[case_id] for case_id in case_ids if case_id in found]
            return [self._case_item(row) for row in rows]

    def get_case(
        self, case_id: int, *, include_archived: bool = False
    ) -> dict[str, Any] | None:
        cases = self.get_cases([case_id], include_archived=include_archived)
        return cases[0] if cases else None

    def create_case(self, case: dict[str, Any]) -> dict[str, Any]:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO evaluation_case (
                    topic, expected_type, turns_json, expected_points_json,
                    expected_sources_json, should_show_compliance, origin,
                    status, version
                ) VALUES (?, ?, ?, ?, ?, ?, 'CUSTOM', 'ACTIVE', 1)
                """,
                _case_values(case),
            )
            row = connection.execute(
                "SELECT * FROM evaluation_case WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            return self._case_item(row)

    def update_case(
        self, case_id: int, expected_version: int, case: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE evaluation_case
                SET topic = ?, expected_type = ?, turns_json = ?,
                    expected_points_json = ?, expected_sources_json = ?,
                    should_show_compliance = ?, version = version + 1,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'ACTIVE' AND version = ?
                """,
                (*_case_values(case), case_id, expected_version),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM evaluation_case WHERE id = ?", (case_id,)
            ).fetchone()
            return self._case_item(row)

    def archive_case(self, case_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE evaluation_case
                SET status = 'ARCHIVED', archived_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND origin = 'CUSTOM' AND status = 'ACTIVE'
                """,
                (case_id,),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM evaluation_case WHERE id = ?", (case_id,)
            ).fetchone()
            return self._case_item(row)

    def has_active_run(self, case_id: int) -> bool:
        with self._connection() as connection:
            return (
                connection.execute(
                    """
                    SELECT 1
                    FROM evaluation_run_case
                    JOIN evaluation_run ON evaluation_run.id = evaluation_run_case.run_id
                    WHERE evaluation_run_case.case_id = ?
                      AND evaluation_run.status IN ('PENDING', 'RUNNING')
                    LIMIT 1
                    """,
                    (case_id,),
                ).fetchone()
                is not None
            )

    def create_run(
        self,
        name: str,
        cases: Sequence[dict[str, Any]],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        case_ids = [int(case["id"]) for case in cases]
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO evaluation_run (name, case_count, progress_total, config_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    name,
                    len(case_ids),
                    len(case_ids),
                    json.dumps(config, ensure_ascii=False),
                ),
            )
            run_id = int(cursor.lastrowid)
            connection.executemany(
                """
                INSERT INTO evaluation_run_case (
                    run_id, case_id, position, case_version, case_snapshot_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        case_id,
                        position,
                        int(case.get("version", 1)),
                        json.dumps(_case_snapshot(case), ensure_ascii=False),
                    )
                    for position, (case_id, case) in enumerate(
                        zip(case_ids, cases, strict=True)
                    )
                ],
            )
            return dict(
                connection.execute(
                    "SELECT * FROM evaluation_run WHERE id = ?", (run_id,)
                ).fetchone()
            )

    def delete_run(self, run_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM evaluation_run WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            run = dict(row)
            if run["status"] not in {"COMPLETED", "FAILED"}:
                return run
            connection.execute("DELETE FROM evaluation_run WHERE id = ?", (run_id,))
            return run

    def run_case_ids(self, run_id: int) -> list[int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT case_id FROM evaluation_run_case WHERE run_id = ? ORDER BY position",
                (run_id,),
            ).fetchall()
            return [int(row["case_id"]) for row in rows]

    def run_cases(self, run_id: int) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT case_id, case_version, case_snapshot_json
                FROM evaluation_run_case
                WHERE run_id = ? ORDER BY position
                """,
                (run_id,),
            ).fetchall()
            cases: list[dict[str, Any]] = []
            for row in rows:
                snapshot = json.loads(row["case_snapshot_json"] or "{}")
                if not snapshot:
                    current = self.get_case(int(row["case_id"]), include_archived=True)
                    if current is None:
                        continue
                    snapshot = _case_snapshot(current)
                cases.append(
                    {
                        "id": int(row["case_id"]),
                        "version": int(row["case_version"] or 1),
                        **snapshot,
                    }
                )
            return cases

    def set_run_status(self, run_id: int, status: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE evaluation_run SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, run_id),
            )

    def add_result(self, run_id: int, result: dict[str, Any]) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_result (
                    run_id, case_id, status, answer, refused, correct, source_hit,
                    multi_turn_correct, compliance_hit, citations_json, latency_ms,
                    error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    result["case_id"],
                    result["status"],
                    result.get("answer"),
                    _db_bool(result.get("refused")),
                    _db_bool(result.get("correct")),
                    _db_bool(result.get("source_hit")),
                    _db_bool(result.get("multi_turn_correct")),
                    _db_bool(result.get("compliance_hit")),
                    json.dumps(result.get("citations", []), ensure_ascii=False),
                    result.get("latency_ms"),
                    result.get("error_message"),
                ),
            )
            connection.execute(
                "UPDATE evaluation_run SET progress_current = progress_current + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (run_id,),
            )

    def complete_run(self, run_id: int, metrics: dict[str, float | None]) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE evaluation_run SET status = 'COMPLETED', error_message = NULL,
                    accuracy = ?, reject_rate = ?, refusal_rate = ?, citation_hit_rate = ?,
                    multi_turn_pass_rate = ?, compliance_hit_rate = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    metrics["accuracy"],
                    metrics["reject_rate"],
                    metrics["refusal_rate"],
                    metrics["citation_hit_rate"],
                    metrics["multi_turn_pass_rate"],
                    metrics["compliance_hit_rate"],
                    run_id,
                ),
            )

    def fail_run(self, run_id: int, message: str) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE evaluation_run SET status = 'FAILED', error_message = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (message[:500], run_id),
            )

    def recover_interrupted_runs(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE evaluation_run
                SET status = 'FAILED', error_message = '服务重启导致任务中断',
                    updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('PENDING', 'RUNNING')
                """
            )

    def list_runs(
        self, *, page: int, size: int, status: str | None
    ) -> tuple[list[dict[str, Any]], int]:
        where_clause = "WHERE status = ?" if status else ""
        parameters: list[Any] = [status] if status else []
        with self._connection() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM evaluation_run {where_clause}", parameters
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT * FROM evaluation_run
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, size, (page - 1) * size],
            ).fetchall()
            return [self._run_summary(row) for row in rows], total

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM evaluation_run WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            results = connection.execute(
                """
                SELECT * FROM evaluation_result
                WHERE run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
            summary = self._run_summary(row)
            metrics = None
            if row["status"] == "COMPLETED":
                metrics = {
                    key: row[key]
                    for key in (
                        "accuracy",
                        "reject_rate",
                        "refusal_rate",
                        "citation_hit_rate",
                        "multi_turn_pass_rate",
                        "compliance_hit_rate",
                    )
                }
            return {
                **summary,
                "config": json.loads(row["config_json"]),
                "metrics": metrics,
                "results": [self._result_item(item) for item in results],
            }

    @staticmethod
    def _case_item(row: sqlite3.Row) -> dict[str, Any]:
        columns = set(row.keys())
        return {
            "id": int(row["id"]),
            "topic": row["topic"],
            "expected_type": row["expected_type"],
            "turns": json.loads(row["turns_json"]),
            "expected_points": json.loads(row["expected_points_json"]),
            "expected_sources": json.loads(row["expected_sources_json"]),
            "should_show_compliance": bool(row["should_show_compliance"]),
            "origin": row["origin"] if "origin" in columns else "BUILTIN",
            "status": row["status"] if "status" in columns else "ACTIVE",
            "version": int(row["version"] if "version" in columns else 1),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
            if "updated_at" in columns and row["updated_at"]
            else row["created_at"],
            "archived_at": row["archived_at"] if "archived_at" in columns else None,
        }

    @staticmethod
    def _run_summary(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": row["name"],
            "status": row["status"],
            "progress_current": int(row["progress_current"]),
            "progress_total": int(row["progress_total"]),
            "error_message": row["error_message"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _result_item(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "case_id": int(row["case_id"]),
            "status": row["status"],
            "answer": row["answer"],
            "refused": _python_bool(row["refused"]),
            "correct": _python_bool(row["correct"]),
            "source_hit": _python_bool(row["source_hit"]),
            "multi_turn_correct": _python_bool(row["multi_turn_correct"]),
            "compliance_hit": _python_bool(row["compliance_hit"]),
            "citations": json.loads(row["citations_json"]),
            "latency_ms": row["latency_ms"],
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


def _case_values(case: dict[str, Any]) -> tuple[Any, ...]:
    return (
        case["topic"],
        case["expected_type"],
        json.dumps(case["turns"], ensure_ascii=False),
        json.dumps(case["expected_points"], ensure_ascii=False),
        json.dumps(case["expected_sources"], ensure_ascii=False),
        int(case["should_show_compliance"]),
    )


def _case_snapshot(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "topic": case["topic"],
        "expected_type": case["expected_type"],
        "turns": case["turns"],
        "expected_points": case["expected_points"],
        "expected_sources": case["expected_sources"],
        "should_show_compliance": bool(case["should_show_compliance"]),
    }
