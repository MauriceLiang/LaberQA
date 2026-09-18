"""SQLite persistence for editable retrieval strategies."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.config import settings


class RetrievalStrategyRepository:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or settings.database_path

    def seed_builtins(self, strategies: list[dict[str, Any]]) -> None:
        """Insert the baseline strategies once without overwriting user edits."""

        with self._connection() as connection:
            for strategy in strategies:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO retrieval_strategy (
                        name, description, builtin_key, config_json, is_builtin, version
                    ) VALUES (?, ?, ?, ?, 1, 1)
                    """,
                    (
                        strategy["name"],
                        strategy.get("description", ""),
                        strategy["builtin_key"],
                        json.dumps(strategy["config"], ensure_ascii=False),
                    ),
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO retrieval_strategy_version (
                        strategy_id, version, name, description, config_json
                    )
                    SELECT id, version, name, description, config_json
                    FROM retrieval_strategy WHERE builtin_key = ?
                    """,
                    (strategy["builtin_key"],),
                )

    def list_strategies(
        self, *, include_archived: bool = False
    ) -> list[dict[str, Any]]:
        with self._connection() as connection:
            archived_filter = "" if include_archived else "WHERE archived_at IS NULL"
            rows = connection.execute(
                f"""
                SELECT * FROM retrieval_strategy
                {archived_filter}
                ORDER BY is_builtin DESC, updated_at DESC, id ASC
                """
            ).fetchall()
            return [self._item(row) for row in rows]

    def get_strategy(self, strategy_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM retrieval_strategy WHERE id = ?", (strategy_id,)
            ).fetchone()
            return self._item(row) if row is not None else None

    def create_strategy(
        self,
        name: str,
        description: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO retrieval_strategy (
                    name, description, config_json, is_builtin, version, is_active
                ) VALUES (?, ?, ?, 0, 1, 1)
                """,
                (name, description, json.dumps(config, ensure_ascii=False)),
            )
            connection.execute(
                """
                INSERT INTO retrieval_strategy_version (
                    strategy_id, version, name, description, config_json
                ) VALUES (?, 1, ?, ?, ?)
                """,
                (
                    cursor.lastrowid,
                    name,
                    description,
                    json.dumps(config, ensure_ascii=False),
                ),
            )
            row = connection.execute(
                "SELECT * FROM retrieval_strategy WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            assert row is not None
            return self._item(row)

    def update_strategy(
        self,
        strategy_id: int,
        name: str,
        description: str,
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._connection() as connection:
            current = connection.execute(
                "SELECT * FROM retrieval_strategy WHERE id = ? AND is_builtin = 0",
                (strategy_id,),
            ).fetchone()
            if current is None:
                return None
            next_version = int(current["version"]) + 1
            config_json = json.dumps(config, ensure_ascii=False)
            connection.execute(
                """
                UPDATE retrieval_strategy
                SET name = ?, description = ?, config_json = ?,
                    version = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    name,
                    description,
                    config_json,
                    next_version,
                    strategy_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO retrieval_strategy_version (
                    strategy_id, version, name, description, config_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (strategy_id, next_version, name, description, config_json),
            )
            row = connection.execute(
                "SELECT * FROM retrieval_strategy WHERE id = ?", (strategy_id,)
            ).fetchone()
            return self._item(row) if row is not None else None

    def list_versions(self, strategy_id: int) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM retrieval_strategy_version
                WHERE strategy_id = ?
                ORDER BY version DESC
                """,
                (strategy_id,),
            ).fetchall()
            return [self._version_item(row) for row in rows]

    def restore_version(self, strategy_id: int, version: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            current = connection.execute(
                "SELECT * FROM retrieval_strategy WHERE id = ? AND is_builtin = 0",
                (strategy_id,),
            ).fetchone()
            target = connection.execute(
                """
                SELECT * FROM retrieval_strategy_version
                WHERE strategy_id = ? AND version = ?
                """,
                (strategy_id, version),
            ).fetchone()
            if current is None or target is None:
                return None
            next_version = int(current["version"]) + 1
            connection.execute(
                """
                UPDATE retrieval_strategy
                SET name = ?, description = ?, config_json = ?, version = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    target["name"],
                    target["description"],
                    target["config_json"],
                    next_version,
                    strategy_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO retrieval_strategy_version (
                    strategy_id, version, name, description, config_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    strategy_id,
                    next_version,
                    target["name"],
                    target["description"],
                    target["config_json"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM retrieval_strategy WHERE id = ?", (strategy_id,)
            ).fetchone()
            return self._item(row) if row is not None else None

    def set_active(self, strategy_id: int, active: bool) -> dict[str, Any] | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE retrieval_strategy
                SET is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND is_builtin = 0 AND archived_at IS NULL
                """,
                (int(active), strategy_id),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM retrieval_strategy WHERE id = ?", (strategy_id,)
            ).fetchone()
            return self._item(row) if row is not None else None

    def archive_strategy(self, strategy_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE retrieval_strategy
                SET is_active = 0, archived_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND is_builtin = 0 AND archived_at IS NULL
                """,
                (strategy_id,),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM retrieval_strategy WHERE id = ?", (strategy_id,)
            ).fetchone()
            return self._item(row) if row is not None else None

    def restore_strategy(self, strategy_id: int) -> dict[str, Any] | None:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE retrieval_strategy
                SET is_active = 1, archived_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ? AND is_builtin = 0 AND archived_at IS NOT NULL
                """,
                (strategy_id,),
            )
            if cursor.rowcount == 0:
                return None
            row = connection.execute(
                "SELECT * FROM retrieval_strategy WHERE id = ?", (strategy_id,)
            ).fetchone()
            return self._item(row) if row is not None else None

    def delete_strategy(self, strategy_id: int) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "DELETE FROM retrieval_strategy WHERE id = ? AND is_builtin = 0",
                (strategy_id,),
            )
            return cursor.rowcount > 0

    @staticmethod
    def _item(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "name": str(row["name"]),
            "description": str(row["description"] or ""),
            "builtin_key": row["builtin_key"],
            "config": json.loads(row["config_json"]),
            "is_builtin": bool(row["is_builtin"]),
            "version": int(row["version"]),
            "is_active": bool(row["is_active"]),
            "archived_at": row["archived_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @staticmethod
    def _version_item(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "strategy_id": int(row["strategy_id"]),
            "version": int(row["version"]),
            "name": str(row["name"]),
            "description": str(row["description"] or ""),
            "config": json.loads(row["config_json"]),
            "created_at": row["created_at"],
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
