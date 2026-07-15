from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig
from .database import Database, utc_now
from .instagram import InstaloaderClient
from .post_metadata import (
    author as _author,
    caption as _caption,
    is_unknown_author,
    media_type as _media_type,
    published_at as _published_at,
    shortcode as _shortcode,
)


ClientFactory = Callable[[str, Path, Path], Any]
SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _resolved_author(client: Any, post: Any) -> str:
    try:
        resolver = getattr(client, "resolve_author", None)
        value = resolver(post) if callable(resolver) else _author(post)
    except Exception:
        value = _author(post)
    normalized = str(value or "").strip().lstrip("@")
    return normalized if normalized else "unknown"


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
        self._cancel_event = threading.Event()

    def start(
        self, trigger: str, max_downloads: int | None = None
    ) -> tuple[bool, dict[str, Any]]:
        if max_downloads is not None and max_downloads < 1:
            raise ValueError("max_downloads must be at least one")
        return self._start(trigger, self._execute, max_downloads)

    def start_import(self) -> tuple[bool, dict[str, Any]]:
        if not self.config.import_dir.is_dir():
            raise ValueError(
                f"Legacy import folder {self.config.import_dir} is not mounted or is not a directory"
            )
        return self._start("legacy-import", self._execute_import)

    def start_author_repair(self) -> tuple[bool, dict[str, Any]]:
        return self._start("author-repair", self._execute_author_repair)

    def _start(
        self, trigger: str, target: Callable[..., None], *args: Any
    ) -> tuple[bool, dict[str, Any]]:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                current = self.database.current_sync_run() or {"status": "running"}
                return False, current
            current = self.database.current_sync_run()
            if current is not None:
                return False, current
            self._cancel_event.clear()
            run_id = self.database.create_sync_run(trigger)
            self._thread = threading.Thread(
                target=target,
                args=(run_id, *args),
                name=f"gramshelf-job-{run_id}",
                daemon=True,
            )
            self._thread.start()
        return True, self.database.get_sync_run(run_id) or {"id": run_id, "status": "queued"}

    def wait(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def stop(self) -> tuple[bool, dict[str, Any] | None]:
        with self._lock:
            current = self.database.current_sync_run()
            if (
                current is None
                or self._thread is None
                or not self._thread.is_alive()
            ):
                return False, current
            self._cancel_event.set()
            self.database.update_sync_run(
                current["id"], message="Stop requested; finishing the current item"
            )
            updated = self.database.get_sync_run(current["id"])
            if updated is not None:
                updated["running"] = True
                updated["stopping"] = True
            return True, updated

    def status(self) -> dict[str, Any]:
        current = self.database.current_sync_run()
        if current is not None:
            current["running"] = True
            current["stopping"] = self._cancel_event.is_set()
            return current
        latest = self.database.list_sync_runs(limit=1)
        if latest:
            result = latest[0]
            result["running"] = False
            result["stopping"] = False
            return result
        return {"running": False, "stopping": False, "status": "never_run"}

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
        repaired_count = 0
        stopped_at_download_limit = False
        cancelled = False
        client = self.client_factory(username, self.config.session_path, self.config.media_dir)
        try:
            client.connect()
            posts = iter(client.iter_saved_posts())
            while True:
                if self._cancel_event.is_set():
                    cancelled = True
                    break
                try:
                    post = next(posts)
                except StopIteration:
                    break
                counts["discovered_count"] += 1
                shortcode = _shortcode(post)
                if not SHORTCODE_RE.fullmatch(shortcode):
                    counts["error_count"] += 1
                    self.database.add_sync_error(run_id, "Saved item had an invalid shortcode")
                    self._update_progress(run_id, counts)
                    continue
                existing = self.database.get_item_by_shortcode(shortcode)
                if existing is not None:
                    counts["skipped_count"] += 1
                    repaired = False
                    if is_unknown_author(existing.get("author")):
                        resolved = _resolved_author(client, post)
                        if not is_unknown_author(resolved):
                            self.database.update_item_metadata(shortcode, author=resolved)
                            repaired_count += 1
                            repaired = True
                    known_streak = 0 if repaired else known_streak + 1
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
                        "author": _resolved_author(client, post),
                        "caption": _caption(post),
                        "published_at": _published_at(post, downloaded_at),
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
                if self._cancel_event.is_set():
                    cancelled = True
                    break
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

        if cancelled:
            status = "cancelled"
        elif counts["error_count"]:
            status = "completed_with_errors"
        else:
            status = "success"
        limit_message = " (test limit reached)" if stopped_at_download_limit else ""
        cancel_message = " (stopped by administrator)" if cancelled else ""
        repair_message = f", repaired {repaired_count} author(s)" if repaired_count else ""
        message = (
            f"Downloaded {counts['downloaded_count']}, skipped {counts['skipped_count']}, "
            f"errors {counts['error_count']}{repair_message}{limit_message}{cancel_message}"
        )
        # Per-item failures do not make the Saved-feed traversal incomplete.
        # Once a traversal reaches its boundary, later runs may safely stop at
        # the configured streak of already-known items.
        archive_scan_complete = True
        if stopped_at_download_limit or cancelled:
            archive_scan_complete = can_stop_at_known
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

    def _execute_import(self, run_id: int) -> None:
        from .importer import LegacyArchiveImporter

        started_at = utc_now()
        self.database.update_sync_run(run_id, status="running", started_at=started_at)
        counts = {
            "discovered_count": 0,
            "downloaded_count": 0,
            "skipped_count": 0,
            "error_count": 0,
        }
        try:
            result = LegacyArchiveImporter(self.database, self.config).run(
                run_id,
                self._cancel_event,
                lambda current: self._update_progress(run_id, current),
            )
            counts = result["counts"]
        except Exception as exc:
            counts["error_count"] += 1
            self.database.add_sync_error(run_id, str(exc))
            self._fail_job(run_id, counts, str(exc))
            return
        cancelled = bool(result["cancelled"])
        status = (
            "cancelled"
            if cancelled
            else "completed_with_errors"
            if counts["error_count"]
            else "success"
        )
        cancel_message = " (stopped by administrator)" if cancelled else ""
        message = (
            f"Imported {result['added_count']}, updated {result['updated_count']}, "
            f"duplicates {counts['skipped_count']}, errors {counts['error_count']}"
            f"{cancel_message}"
        )
        self.database.update_sync_run(
            run_id,
            status=status,
            completed_at=utc_now(),
            message=message,
            **counts,
        )

    def _execute_author_repair(self, run_id: int) -> None:
        started_at = utc_now()
        self.database.update_sync_run(run_id, status="running", started_at=started_at)
        counts = {
            "discovered_count": 0,
            "downloaded_count": 0,
            "skipped_count": 0,
            "error_count": 0,
        }
        username = str(self.database.get_setting("instagram_username", "")).strip()
        if not username or not self.config.session_path.is_file():
            self._fail_job(run_id, counts, "Instagram session is not configured")
            return
        client = self.client_factory(username, self.config.session_path, self.config.media_dir)
        cancelled = False
        try:
            client.connect()
            for post in client.iter_saved_posts():
                if self._cancel_event.is_set():
                    cancelled = True
                    break
                counts["discovered_count"] += 1
                item_shortcode = _shortcode(post)
                if not SHORTCODE_RE.fullmatch(item_shortcode):
                    counts["error_count"] += 1
                    self.database.add_sync_error(
                        run_id, "Saved item had an invalid shortcode"
                    )
                else:
                    existing = self.database.get_item_by_shortcode(item_shortcode)
                    if existing is None or not is_unknown_author(existing.get("author")):
                        counts["skipped_count"] += 1
                    else:
                        resolved = _resolved_author(client, post)
                        if is_unknown_author(resolved):
                            counts["error_count"] += 1
                            self.database.add_sync_error(
                                run_id,
                                "The post owner's username could not be resolved",
                                item_shortcode,
                            )
                        else:
                            self.database.update_item_metadata(
                                item_shortcode, author=resolved
                            )
                            counts["downloaded_count"] += 1
                self._update_progress(run_id, counts)
                if self._cancel_event.is_set():
                    cancelled = True
                    break
        except Exception as exc:
            counts["error_count"] += 1
            self.database.add_sync_error(run_id, str(exc))
            self._fail_job(run_id, counts, str(exc))
            return
        finally:
            try:
                client.close()
            except Exception:
                pass
        status = (
            "cancelled"
            if cancelled
            else "completed_with_errors"
            if counts["error_count"]
            else "success"
        )
        cancel_message = " (stopped by administrator)" if cancelled else ""
        message = (
            f"Updated {counts['downloaded_count']} author(s), "
            f"skipped {counts['skipped_count']}, errors {counts['error_count']}"
            f"{cancel_message}"
        )
        self.database.update_sync_run(
            run_id,
            status=status,
            completed_at=utc_now(),
            message=message,
            **counts,
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

    def _fail_job(self, run_id: int, counts: dict[str, int], message: str) -> None:
        self.database.update_sync_run(
            run_id,
            status="error",
            completed_at=utc_now(),
            message=message[:4000],
            **counts,
        )
