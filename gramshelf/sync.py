from __future__ import annotations

import re
import sqlite3
import threading
from datetime import UTC
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig
from .database import Database, utc_now
from .instagram import InstaloaderClient


ClientFactory = Callable[[str, Path, Path], Any]
SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _published_at(post: Any) -> str:
    value = post.date_utc
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat(timespec="seconds")


def _media_type(post: Any) -> str:
    typename = str(getattr(post, "typename", ""))
    if typename == "GraphSidecar":
        return "carousel"
    if typename == "GraphVideo" or bool(getattr(post, "is_video", False)):
        return "video"
    return "image"


class SyncManager:
    def __init__(
        self,
        database: Database,
        config: AppConfig,
        client_factory: ClientFactory = InstaloaderClient,
    ):
        self.database = database
        self.config = config
        self.client_factory = client_factory
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(
        self, trigger: str, max_downloads: int | None = None
    ) -> tuple[bool, dict[str, Any]]:
        if max_downloads is not None and max_downloads < 1:
            raise ValueError("max_downloads must be at least one")
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                current = self.database.current_sync_run() or {"status": "running"}
                return False, current
            current = self.database.current_sync_run()
            if current is not None:
                return False, current
            run_id = self.database.create_sync_run(trigger)
            self._thread = threading.Thread(
                target=self._execute,
                args=(run_id, max_downloads),
                name=f"gramshelf-sync-{run_id}",
                daemon=True,
            )
            self._thread.start()
        return True, self.database.get_sync_run(run_id) or {"id": run_id, "status": "queued"}

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def status(self) -> dict[str, Any]:
        current = self.database.current_sync_run()
        if current is not None:
            current["running"] = True
            return current
        latest = self.database.list_sync_runs(limit=1)
        if latest:
            result = latest[0]
            result["running"] = False
            return result
        return {"running": False, "status": "never_run"}

    def _execute(self, run_id: int, max_downloads: int | None = None) -> None:
        started_at = utc_now()
        self.database.update_sync_run(run_id, status="running", started_at=started_at)
        counts = {"discovered_count": 0, "downloaded_count": 0, "skipped_count": 0, "error_count": 0}
        username = str(self.database.get_setting("instagram_username", "")).strip()
        if not username or not self.config.session_path.is_file():
            self._fail(run_id, counts, "Instagram session is not configured")
            return

        stop_after_known = max(1, int(self.database.get_setting("stop_after_known", 3)))
        can_stop_at_known = bool(self.database.get_setting("archive_scan_complete", False))
        known_streak = 0
        stopped_at_download_limit = False
        client = self.client_factory(username, self.config.session_path, self.config.media_dir)
        try:
            client.connect()
            posts = client.iter_saved_posts()
            for post in posts:
                counts["discovered_count"] += 1
                shortcode = str(getattr(post, "shortcode", ""))
                if not SHORTCODE_RE.fullmatch(shortcode):
                    counts["error_count"] += 1
                    self.database.add_sync_error(run_id, "Saved item had an invalid shortcode")
                    self._update_progress(run_id, counts)
                    continue
                if self.database.item_exists(shortcode):
                    counts["skipped_count"] += 1
                    known_streak += 1
                    self._update_progress(run_id, counts)
                    if can_stop_at_known and known_streak >= stop_after_known:
                        break
                    continue

                known_streak = 0
                try:
                    downloaded_at = utc_now()
                    media_files = client.download_post(post, shortcode)
                    cover = next(
                        (entry["relative_path"] for entry in media_files if entry["kind"] == "image"),
                        media_files[0]["relative_path"],
                    )
                    item = {
                        "shortcode": shortcode,
                        "instagram_url": f"https://www.instagram.com/p/{shortcode}/",
                        "author": str(getattr(post, "owner_username", "unknown")),
                        "caption": str(getattr(post, "caption", "") or ""),
                        "published_at": _published_at(post),
                        "downloaded_at": downloaded_at,
                        "media_type": _media_type(post),
                        "cover_path": cover,
                    }
                    self.database.insert_item(item, media_files)
                    counts["downloaded_count"] += 1
                except sqlite3.IntegrityError:
                    counts["skipped_count"] += 1
                except Exception as exc:
                    counts["error_count"] += 1
                    self.database.add_sync_error(run_id, str(exc), shortcode)
                self._update_progress(run_id, counts)
                if max_downloads is not None and counts["downloaded_count"] >= max_downloads:
                    stopped_at_download_limit = True
                    break
        except Exception as exc:
            self.database.add_sync_error(run_id, str(exc))
            counts["error_count"] += 1
            self._fail(run_id, counts, str(exc))
            return
        finally:
            try:
                client.close()
            except Exception:
                pass

        status = "completed_with_errors" if counts["error_count"] else "success"
        limit_message = " (test limit reached)" if stopped_at_download_limit else ""
        message = (
            f"Downloaded {counts['downloaded_count']}, skipped {counts['skipped_count']}, "
            f"errors {counts['error_count']}{limit_message}"
        )
        archive_scan_complete = not bool(counts["error_count"])
        if stopped_at_download_limit:
            archive_scan_complete = can_stop_at_known and archive_scan_complete
        completed_at = utc_now()
        self.database.update_sync_run(
            run_id,
            status=status,
            completed_at=completed_at,
            message=message,
            **counts,
        )
        self.database.set_settings(
            {
                "last_sync_at": completed_at,
                "last_sync_status": status,
                "last_sync_error": None if not counts["error_count"] else message,
                "archive_scan_complete": archive_scan_complete,
            }
        )

    def _update_progress(self, run_id: int, counts: dict[str, int]) -> None:
        self.database.update_sync_run(run_id, **counts)

    def _fail(self, run_id: int, counts: dict[str, int], message: str) -> None:
        completed_at = utc_now()
        self.database.update_sync_run(
            run_id,
            status="error",
            completed_at=completed_at,
            message=message[:4000],
            **counts,
        )
        self.database.set_settings(
            {
                "last_sync_at": completed_at,
                "last_sync_status": "error",
                "last_sync_error": message[:4000],
                "archive_scan_complete": False,
            }
        )
