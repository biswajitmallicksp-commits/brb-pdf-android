"""Local SQLite storage (never synced anywhere).

Phase 1 stores recent files and simple settings. Later phases add tables
for favourites, tags, analysis history, OCR settings and bank formats.
Schema changes are applied through the MIGRATIONS list, so an old
database is upgraded automatically and never deleted.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

from app import config

log = logging.getLogger("pdfworkbench.db")

MIGRATIONS: list[str] = [
    # version 1
    """
    CREATE TABLE IF NOT EXISTS recent_files (
        path       TEXT PRIMARY KEY,
        opened_at  REAL NOT NULL,
        last_page  INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT
    );
    """,
]


class AppDatabase:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or config.DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    # ------------------------------------------------------------------ schema
    def _migrate(self) -> None:
        with self._lock:
            cur = self._conn.execute("PRAGMA user_version")
            version = cur.fetchone()[0]
            for index, script in enumerate(MIGRATIONS, start=1):
                if index > version:
                    log.info("Applying database migration %d", index)
                    self._conn.executescript(script)
                    self._conn.execute(f"PRAGMA user_version = {index}")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------ recent files
    def add_recent(self, path: str, last_page: int = 0) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO recent_files(path, opened_at, last_page) VALUES(?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET opened_at=excluded.opened_at, "
                "last_page=excluded.last_page",
                (str(path), time.time(), int(last_page)),
            )
            # keep the table small
            self._conn.execute(
                "DELETE FROM recent_files WHERE path NOT IN "
                "(SELECT path FROM recent_files ORDER BY opened_at DESC LIMIT ?)",
                (config.MAX_RECENT_FILES * 4,),
            )
            self._conn.commit()

    def set_last_page(self, path: str, page: int) -> None:
        with self._lock:
            self._conn.execute("UPDATE recent_files SET last_page=? WHERE path=?", (int(page), str(path)))
            self._conn.commit()

    def last_page(self, path: str) -> int:
        with self._lock:
            row = self._conn.execute("SELECT last_page FROM recent_files WHERE path=?", (str(path),)).fetchone()
        return int(row[0]) if row else 0

    def recent_files(self, limit: int = config.MAX_RECENT_FILES) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT path FROM recent_files ORDER BY opened_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [r[0] for r in rows]

    def remove_recent(self, path: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM recent_files WHERE path=?", (str(path),))
            self._conn.commit()

    def clear_recent(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM recent_files")
            self._conn.commit()

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
            self._conn.commit()
