from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import ensure_storage, get_settings


MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class ClosingConnection(sqlite3.Connection):
    """A sqlite connection whose context manager also closes the file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect() -> sqlite3.Connection:
    settings = get_settings()
    ensure_storage(settings)
    connection = sqlite3.connect(
        settings.database_path,
        timeout=30,
        isolation_level=None,
        check_same_thread=False,
        factory=ClosingConnection,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


@contextmanager
def transaction(immediate: bool = False) -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        applied = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if migration.name in applied:
                continue
            if migration.name == "004_quota_optimizer.sql":
                job_count = connection.execute(
                    "SELECT COUNT(*) FROM jobs"
                ).fetchone()[0]
                if job_count:
                    settings = get_settings()
                    backup_dir = settings.storage_dir / "backups"
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    backup_path = backup_dir / "thaiforge-pre-quota-optimizer.db"
                    if not backup_path.exists():
                        destination = sqlite3.connect(backup_path)
                        try:
                            connection.backup(destination)
                        finally:
                            destination.close()
            if migration.name == "005_glossary_rules.sql":
                job_count = connection.execute(
                    "SELECT COUNT(*) FROM jobs"
                ).fetchone()[0]
                if job_count:
                    settings = get_settings()
                    backup_dir = settings.storage_dir / "backups"
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    backup_path = backup_dir / "thaiforge-pre-glossary-rules.db"
                    if not backup_path.exists():
                        destination = sqlite3.connect(backup_path)
                        try:
                            connection.backup(destination)
                        finally:
                            destination.close()
            connection.executescript(migration.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (migration.name, utc_now()),
            )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None
