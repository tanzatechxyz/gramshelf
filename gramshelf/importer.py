from __future__ import annotations

import re
import shutil
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .config import AppConfig
from .database import Database
from .post_metadata import (
    cached_author,
    caption,
    is_unknown_author,
    media_type,
    published_at,
    shortcode,
)


MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v"}
SHORTCODE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
GENERIC_FOLDERS = {"archive", "downloads", "import", "instagram", "saved"}


class LegacyArchiveImporter:
    """Copy an existing Instaloader archive into GramShelf's media and database."""

    def __init__(self, database: Database, config: AppConfig):
        self.database = database
        self.config = config

    def run(
        self,
        run_id: int,
        cancel_event: threading.Event,
        progress: Callable[[dict[str, int]], None],
    ) -> dict[str, Any]:
        import instaloader

        root = self.config.import_dir.resolve()
        if not root.is_dir():
            raise RuntimeError(
                f"Legacy import folder {self.config.import_dir} is not mounted or is not a directory"
            )
        loader = instaloader.Instaloader(quiet=True)
        counts = {
            "discovered_count": 0,
            "downloaded_count": 0,
            "skipped_count": 0,
            "error_count": 0,
        }
        added_count = 0
        updated_count = 0
        cancelled = False
        try:
            metadata_files = sorted(
                [*root.rglob("*.json"), *root.rglob("*.json.xz")],
                key=lambda path: path.as_posix().casefold(),
            )
            for metadata_path in metadata_files:
                if cancel_event.is_set():
                    cancelled = True
                    break
                counts["discovered_count"] += 1
                item_shortcode: str | None = None
                try:
                    resolved_path = metadata_path.resolve()
                    if not resolved_path.is_relative_to(root) or not resolved_path.is_file():
                        raise RuntimeError("metadata path points outside the import folder")
                    post = instaloader.load_structure_from_file(
                        loader.context, str(resolved_path)
                    )
                    item_shortcode = shortcode(post)
                    if post.__class__.__name__ != "Post" or not SHORTCODE_RE.fullmatch(
                        item_shortcode
                    ):
                        raise RuntimeError("file does not contain valid Instaloader Post metadata")
                    outcome = self._import_one(root, metadata_path, post, item_shortcode)
                    if outcome == "added":
                        added_count += 1
                        counts["downloaded_count"] += 1
                    elif outcome == "updated":
                        updated_count += 1
                        counts["downloaded_count"] += 1
                    else:
                        counts["skipped_count"] += 1
                except Exception as exc:
                    counts["error_count"] += 1
                    try:
                        relative_name = metadata_path.relative_to(root).as_posix()
                    except ValueError:
                        relative_name = metadata_path.name
                    self.database.add_sync_error(
                        run_id,
                        f"{relative_name}: {exc}",
                        item_shortcode,
                    )
                progress(counts)
                if cancel_event.is_set():
                    cancelled = True
                    break
        finally:
            try:
                loader.close()
            except Exception:
                pass
        return {
            "counts": counts,
            "added_count": added_count,
            "updated_count": updated_count,
            "cancelled": cancelled,
        }

    def _import_one(
        self, root: Path, metadata_path: Path, post: Any, item_shortcode: str
    ) -> str:
        imported_author = self._author(post, root, metadata_path)
        imported_caption = caption(post) or self._caption_text(metadata_path)
        existing = self.database.get_item_by_shortcode(item_shortcode)
        if existing is not None:
            updates: dict[str, Any] = {}
            if is_unknown_author(existing.get("author")) and not is_unknown_author(
                imported_author
            ):
                updates["author"] = imported_author
            if not str(existing.get("caption") or "").strip() and imported_caption:
                updates["caption"] = imported_caption
            if updates:
                self.database.update_item_metadata(item_shortcode, **updates)
                return "updated"
            return "skipped"

        sources = self._media_sources(root, metadata_path)
        if not sources:
            raise RuntimeError("no matching image or video files were found")
        downloaded_at = datetime.fromtimestamp(
            max(path.stat().st_mtime for path in sources), tz=UTC
        ).isoformat(timespec="seconds")
        target_dir = self.config.media_dir / item_shortcode
        target_dir.mkdir(parents=True, exist_ok=True)
        copied_paths: list[Path] = []
        media_files: list[dict[str, Any]] = []
        try:
            for position, source in enumerate(sources):
                destination = target_dir / source.name
                if not destination.exists():
                    shutil.copy2(source, destination)
                    copied_paths.append(destination)
                kind = "video" if source.suffix.lower() in VIDEO_EXTENSIONS else "image"
                media_files.append(
                    {
                        "position": position,
                        "kind": kind,
                        "relative_path": destination.relative_to(
                            self.config.media_dir
                        ).as_posix(),
                    }
                )
            cover = next(
                (
                    media["relative_path"]
                    for media in media_files
                    if media["kind"] == "image"
                ),
                media_files[0]["relative_path"],
            )
            self.database.insert_item(
                {
                    "shortcode": item_shortcode,
                    "instagram_url": f"https://www.instagram.com/p/{item_shortcode}/",
                    "author": imported_author,
                    "caption": imported_caption,
                    "published_at": published_at(post, downloaded_at),
                    "downloaded_at": downloaded_at,
                    "media_type": media_type(post),
                    "cover_path": cover,
                },
                media_files,
            )
        except Exception:
            for copied_path in copied_paths:
                copied_path.unlink(missing_ok=True)
            try:
                target_dir.rmdir()
            except OSError:
                pass
            raise
        return "added"

    @staticmethod
    def _metadata_base(metadata_path: Path) -> str:
        name = metadata_path.name
        if name.endswith(".json.xz"):
            return name[: -len(".json.xz")]
        return name[: -len(".json")]

    def _media_sources(self, root: Path, metadata_path: Path) -> list[Path]:
        base = self._metadata_base(metadata_path)
        sources: list[Path] = []
        for path in metadata_path.parent.iterdir():
            if not path.is_file() or path.suffix.lower() not in MEDIA_EXTENSIONS:
                continue
            if path.stem != base and not path.stem.startswith(f"{base}_"):
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise RuntimeError("media path points outside the import folder")
            sources.append(resolved)
        return sorted(sources, key=self._natural_media_key)

    @staticmethod
    def _natural_media_key(path: Path) -> tuple[Any, ...]:
        stem_parts = tuple(
            (0, int(part)) if part.isdigit() else (1, part.casefold())
            for part in re.split(r"(\d+)", path.stem)
            if part
        )
        kind_order = 1 if path.suffix.lower() in VIDEO_EXTENSIONS else 0
        return stem_parts, kind_order, path.suffix.casefold()

    def _author(self, post: Any, root: Path, metadata_path: Path) -> str:
        value = cached_author(post)
        if not is_unknown_author(value):
            return value
        if metadata_path.parent != root:
            candidate = metadata_path.parent.name.strip().lstrip("@")
            if (
                USERNAME_RE.fullmatch(candidate)
                and candidate.casefold() not in GENERIC_FOLDERS
            ):
                return candidate
        return "unknown"

    def _caption_text(self, metadata_path: Path) -> str:
        text_path = metadata_path.with_name(f"{self._metadata_base(metadata_path)}.txt")
        if not text_path.is_file():
            return ""
        resolved = text_path.resolve()
        root = self.config.import_dir.resolve()
        if not resolved.is_relative_to(root):
            raise RuntimeError("caption path points outside the import folder")
        with resolved.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(100_000).strip()
