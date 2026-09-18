import json
import sqlite3
from contextlib import closing
from pathlib import Path

from app.core.config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def initialize_database() -> None:
    database_path = settings.database_path
    if database_path != Path(":memory:"):
        database_path.parent.mkdir(parents=True, exist_ok=True)

    with (
        closing(sqlite3.connect(str(database_path), timeout=5)) as connection,
        connection,
    ):
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate_evaluation_schema(connection)


def _migrate_evaluation_schema(connection: sqlite3.Connection) -> None:
    """Upgrade evaluation tables without requiring a separate migration runner."""

    case_columns = _table_columns(connection, "evaluation_case")
    case_additions = {
        "origin": "VARCHAR(20) NOT NULL DEFAULT 'BUILTIN'",
        "status": "VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "builtin_key": "VARCHAR(100)",
        "created_by": "VARCHAR(100)",
        # SQLite does not allow CURRENT_TIMESTAMP as an ALTER TABLE default.
        "updated_at": "TEXT",
        "archived_at": "TEXT",
    }
    for column, definition in case_additions.items():
        if column not in case_columns:
            connection.execute(
                f"ALTER TABLE evaluation_case ADD COLUMN {column} {definition}"
            )

    connection.execute(
        """
        UPDATE evaluation_case
        SET origin = COALESCE(origin, 'BUILTIN'),
            status = COALESCE(status, 'ACTIVE'),
            version = COALESCE(version, 1),
            updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP),
            builtin_key = CASE
                WHEN COALESCE(origin, 'BUILTIN') = 'BUILTIN'
                    THEN COALESCE(builtin_key, 'baseline-' || id)
                ELSE builtin_key
            END
        """
    )

    run_case_columns = _table_columns(connection, "evaluation_run_case")
    run_case_additions = {
        "case_version": "INTEGER NOT NULL DEFAULT 1",
        "case_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
    }
    for column, definition in run_case_additions.items():
        if column not in run_case_columns:
            connection.execute(
                f"ALTER TABLE evaluation_run_case ADD COLUMN {column} {definition}"
            )

    rows = connection.execute(
        """
        SELECT run_case.run_id, run_case.case_id, evaluation_case.version,
               evaluation_case.topic, evaluation_case.expected_type,
               evaluation_case.turns_json, evaluation_case.expected_points_json,
               evaluation_case.expected_sources_json,
               evaluation_case.should_show_compliance
        FROM evaluation_run_case AS run_case
        JOIN evaluation_case ON evaluation_case.id = run_case.case_id
        WHERE run_case.case_snapshot_json IS NULL
           OR run_case.case_snapshot_json = '{}'
        """
    ).fetchall()
    for row in rows:
        snapshot = {
            "topic": row[3],
            "expected_type": row[4],
            "turns": json.loads(row[5]),
            "expected_points": json.loads(row[6]),
            "expected_sources": json.loads(row[7]),
            "should_show_compliance": bool(row[8]),
        }
        connection.execute(
            """
            UPDATE evaluation_run_case
            SET case_version = COALESCE(case_version, ?),
                case_snapshot_json = ?
            WHERE run_id = ? AND case_id = ?
            """,
            (int(row[2] or 1), json.dumps(snapshot, ensure_ascii=False), row[0], row[1]),
        )

    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_evaluation_case_status_origin "
        "ON evaluation_case(status, origin, id)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluation_case_builtin_key "
        "ON evaluation_case(builtin_key) WHERE builtin_key IS NOT NULL"
    )


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def database_is_ready() -> bool:
    try:
        with closing(
            sqlite3.connect(str(settings.database_path), timeout=2)
        ) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            return connection.execute("SELECT 1").fetchone() == (1,)
    except (OSError, sqlite3.Error, ValueError):
        return False
