from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator


DEFAULT_SETTINGS: dict[str, Any] = {
    "sync_enabled": True,
    "sync_interval_minutes": 720,
    "stop_after_known": 3,
    "instagram_username": "",
    "session_last_validated_at": None,
    "session_last_error": None,
    "last_sync_at": None,
    "last_sync_status": None,
    "last_sync_error": None,
    "archive_scan_complete": False,
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shortcode TEXT NOT NULL UNIQUE,
                    instagram_url TEXT NOT NULL,
                    author TEXT NOT NULL,
                    caption TEXT NOT NULL DEFAULT '',
                    published_at TEXT NOT NULL,
                    downloaded_at TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    cover_path TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    relative_path TEXT NOT NULL UNIQUE,
                    UNIQUE(item_id, position)
                );

                CREATE TABLE IF NOT EXISTS sync_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    discovered_count INTEGER NOT NULL DEFAULT 0,
                    downloaded_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    message TEXT
                );

                CREATE TABLE IF NOT EXISTS sync_errors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
                    shortcode TEXT,
                    occurred_at TEXT NOT NULL,
                    message TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_items_published_at ON items(published_at DESC);
                CREATE INDEX IF NOT EXISTS idx_items_author ON items(author);
                CREATE INDEX IF NOT EXISTS idx_items_media_type ON items(media_type);
                CREATE INDEX IF NOT EXISTS idx_sync_runs_started_at ON sync_runs(started_at DESC);
                """
            )
            for key, value in DEFAULT_SETTINGS.items():
                connection.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def get_settings(self, keys: list[str] | None = None) -> dict[str, Any]:
        with self.connect() as connection:
            if keys:
                placeholders = ",".join("?" for _ in keys)
                rows = connection.execute(
                    f"SELECT key, value FROM settings WHERE key IN ({placeholders})", keys
                ).fetchall()
            else:
                rows = connection.execute("SELECT key, value FROM settings").fetchall()
        values: dict[str, Any] = {}
        for row in rows:
            try:
                values[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                values[row["key"]] = None
        return values

    def set_settings(self, values: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.executemany(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(key, json.dumps(value)) for key, value in values.items()],
            )

    def is_setup(self) -> bool:
        return bool(self.get_setting("admin_password_hash"))

    def configure_admin(self, username: str, password_hash: str, api_token: str) -> None:
        if self.is_setup():
            raise RuntimeError("Initial setup has already been completed")
        self.set_settings(
            {
                "admin_username": username,
                "admin_password_hash": password_hash,
                "api_token": api_token,
            }
        )

    def item_exists(self, shortcode: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM items WHERE shortcode = ?", (shortcode,)
            ).fetchone()
        return row is not None

    def insert_item(self, item: dict[str, Any], media_files: list[dict[str, Any]]) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO items(
                    shortcode, instagram_url, author, caption, published_at,
                    downloaded_at, media_type, cover_path, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["shortcode"],
                    item["instagram_url"],
                    item["author"],
                    item.get("caption", ""),
                    item["published_at"],
                    item["downloaded_at"],
                    item["media_type"],
                    item.get("cover_path"),
                    utc_now(),
                ),
            )
            item_id = int(cursor.lastrowid)
            connection.executemany(
                "INSERT INTO media(item_id, position, kind, relative_path) VALUES (?, ?, ?, ?)",
                [
                    (item_id, media["position"], media["kind"], media["relative_path"])
                    for media in media_files
                ],
            )
        return item_id

    def list_items(
        self,
        *,
        query: str = "",
        author: str = "",
        media_type: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 30,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        where: list[str] = []
        parameters: list[Any] = []
        if query:
            where.append("(LOWER(i.caption) LIKE ? OR LOWER(i.author) LIKE ? OR LOWER(i.shortcode) LIKE ?)")
            needle = f"%{query.lower()}%"
            parameters.extend([needle, needle, needle])
        if author:
            where.append("LOWER(i.author) = ?")
            parameters.append(author.lower())
        if media_type:
            where.append("i.media_type = ?")
            parameters.append(media_type)
        if date_from:
            where.append("i.published_at >= ?")
            parameters.append(f"{date_from}T00:00:00+00:00")
        if date_to:
            where.append("i.published_at <= ?")
            parameters.append(f"{date_to}T23:59:59+00:00")
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as connection:
            total = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM items i {where_sql}", parameters
                ).fetchone()[0]
            )
            rows = connection.execute(
                f"""
                SELECT i.*, COUNT(m.id) AS media_count
                FROM items i
                LEFT JOIN media m ON m.item_id = i.id
                {where_sql}
                GROUP BY i.id
                ORDER BY i.published_at DESC, i.id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
        return [dict(row) for row in rows], total

    def get_item(self, item_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if row is None:
                return None
            media_rows = connection.execute(
                "SELECT id, position, kind, relative_path FROM media "
                "WHERE item_id = ? ORDER BY position",
                (item_id,),
            ).fetchall()
        item = dict(row)
        item["media"] = [dict(media) for media in media_rows]
        return item

    def count_items(self) -> int:
        with self.connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM items").fetchone()[0])

    def list_authors(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT author FROM items ORDER BY LOWER(author)"
            ).fetchall()
        return [str(row["author"]) for row in rows]

    def create_sync_run(self, trigger: str) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO sync_runs(trigger, status) VALUES (?, 'queued')", (trigger,)
            )
        return int(cursor.lastrowid)

    def update_sync_run(self, run_id: int, **values: Any) -> None:
        allowed = {
            "status",
            "started_at",
            "completed_at",
            "discovered_count",
            "downloaded_count",
            "skipped_count",
            "error_count",
            "message",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        if not updates:
            return
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE sync_runs SET {assignments} WHERE id = ?",
                [*updates.values(), run_id],
            )

    def add_sync_error(self, run_id: int, message: str, shortcode: str | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO sync_errors(run_id, shortcode, occurred_at, message) VALUES (?, ?, ?, ?)",
                (run_id, shortcode, utc_now(), message[:4000]),
            )

    def get_sync_run(self, run_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM sync_runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            errors = connection.execute(
                "SELECT id, shortcode, occurred_at, message FROM sync_errors "
                "WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        result = dict(row)
        result["errors"] = [dict(error) for error in errors]
        return result

    def current_sync_run(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sync_runs WHERE status IN ('queued', 'running') "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def list_sync_runs(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sync_runs ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_abandoned_runs(self) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sync_runs
                SET status = 'error', completed_at = ?,
                    message = 'Application stopped before this synchronization completed',
                    error_count = error_count + 1
                WHERE status IN ('queued', 'running')
                """,
                (now,),
            )

    def recent_errors(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT e.id, e.run_id, e.shortcode, e.occurred_at, e.message
                FROM sync_errors e
                ORDER BY e.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
