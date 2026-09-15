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


def database_is_ready() -> bool:
    try:
        with closing(
            sqlite3.connect(str(settings.database_path), timeout=2)
        ) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            return connection.execute("SELECT 1").fetchone() == (1,)
    except (OSError, sqlite3.Error, ValueError):
        return False
