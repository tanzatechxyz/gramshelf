from __future__ import annotations

import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


class InstagramSessionError(RuntimeError):
    """Raised when an Instagram session cannot be created or used."""


def _build_loader(media_dir: Path) -> Any:
    import instaloader

    return instaloader.Instaloader(
        quiet=True,
        dirname_pattern=str(media_dir / "{target}"),
        filename_pattern="{shortcode}",
        download_pictures=True,
        download_videos=True,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        post_metadata_txt_pattern="",
        storyitem_metadata_txt_pattern="",
        sanitize_paths=True,
    )


def _normalized_username(username: str) -> str:
    value = username.strip().lstrip("@")
    if not USERNAME_RE.fullmatch(value):
        raise InstagramSessionError("Instagram username is not valid")
    return value


def _close_loader(loader: Any) -> None:
    try:
        loader.close()
    except Exception:
        pass


@dataclass
class _PendingLogin:
    username: str
    loader: Any
    expires_at: float


class SessionLoginManager:
    """Create an Instaloader session without retaining the Instagram password."""

    def __init__(
        self,
        session_path: Path,
        media_dir: Path,
        pending_ttl_seconds: int = 600,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.session_path = session_path
        self.media_dir = media_dir
        self.pending_ttl_seconds = pending_ttl_seconds
        self.clock = clock
        self._lock = threading.RLock()
        self._pending: _PendingLogin | None = None

    def pending_username(self) -> str | None:
        with self._lock:
            self._expire_locked()
            return self._pending.username if self._pending else None

    def start(self, username: str, password: str) -> dict[str, Any]:
        username = _normalized_username(username)
        if not password:
            raise InstagramSessionError("Instagram password is required")

        import instaloader

        with self._lock:
            self._cancel_locked()
            loader = _build_loader(self.media_dir)
            try:
                loader.login(username, password)
            except instaloader.TwoFactorAuthRequiredException:
                self._pending = _PendingLogin(
                    username=username,
                    loader=loader,
                    expires_at=self.clock() + self.pending_ttl_seconds,
                )
                return {"username": username, "two_factor_required": True}
            except Exception as exc:
                _close_loader(loader)
                raise InstagramSessionError(f"Instagram login failed: {exc}") from exc

            validated = self._save_loader(loader, username)
            return {"username": validated, "two_factor_required": False}

    def complete_two_factor(self, code: str) -> str:
        code = code.strip()
        if not code or len(code) > 32:
            raise InstagramSessionError("A valid Instagram verification code is required")

        with self._lock:
            self._expire_locked()
            if self._pending is None:
                raise InstagramSessionError("No Instagram two-factor login is pending")
            pending = self._pending
            try:
                pending.loader.two_factor_login(code)
            except Exception as exc:
                pending.expires_at = self.clock() + self.pending_ttl_seconds
                raise InstagramSessionError(f"Instagram verification failed: {exc}") from exc

            self._pending = None
            return self._save_loader(pending.loader, pending.username)

    def cancel(self) -> None:
        with self._lock:
            self._cancel_locked()

    def _save_loader(self, loader: Any, username: str) -> str:
        temporary: Path | None = None
        try:
            logged_in = loader.test_login()
            if not logged_in:
                raise InstagramSessionError("Instagram rejected the new session")
            if str(logged_in).casefold() != username.casefold():
                raise InstagramSessionError(
                    f"Instagram logged in as @{logged_in}, not @{username}"
                )
            self.session_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.session_path.parent,
                prefix=".instagram-session-login-",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
            loader.save_session_to_file(str(temporary))
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.session_path)
            temporary = None
            return str(logged_in)
        except InstagramSessionError:
            raise
        except Exception as exc:
            raise InstagramSessionError(f"Instagram session could not be saved: {exc}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            _close_loader(loader)

    def _expire_locked(self) -> None:
        if self._pending is not None and self.clock() >= self._pending.expires_at:
            self._cancel_locked()

    def _cancel_locked(self) -> None:
        if self._pending is not None:
            _close_loader(self._pending.loader)
            self._pending = None


class InstaloaderClient:
    """Thin adapter around Instaloader so synchronization remains easy to test."""

    def __init__(self, username: str, session_path: Path, media_dir: Path):
        self.username = _normalized_username(username)
        self.session_path = session_path
        self.media_dir = media_dir
        self.loader: Any | None = None
        self.logged_in_username: str | None = None

    def _build_loader(self) -> Any:
        return _build_loader(self.media_dir)

    def connect(self) -> str:
        if not self.session_path.is_file():
            raise InstagramSessionError("No Instagram session has been configured")
        try:
            self.loader = self._build_loader()
            self.loader.load_session_from_file(self.username, str(self.session_path))
            logged_in = self.loader.test_login()
        except Exception as exc:
            self.close()
            raise InstagramSessionError(f"Instagram session could not be loaded: {exc}") from exc
        if not logged_in:
            self.close()
            raise InstagramSessionError("Instagram rejected the saved session")
        if logged_in.casefold() != self.username.casefold():
            self.close()
            raise InstagramSessionError(
                f"Session belongs to @{logged_in}, not @{self.username}"
            )
        self.logged_in_username = str(logged_in)
        return self.logged_in_username

    def iter_saved_posts(self) -> Iterable[Any]:
        if self.loader is None or self.logged_in_username is None:
            self.connect()
        from instaloader import Profile

        profile = Profile.from_username(self.loader.context, self.logged_in_username)
        return profile.get_saved_posts()

    def download_post(self, post: Any, shortcode: str) -> list[dict[str, Any]]:
        if self.loader is None:
            raise RuntimeError("Instagram client is not connected")
        target_dir = self.media_dir / shortcode
        target_dir.mkdir(parents=True, exist_ok=True)
        self.loader.download_post(post, target=shortcode)

        allowed_images = {".jpg", ".jpeg", ".png", ".webp"}
        allowed_videos = {".mp4", ".mov", ".m4v"}
        paths = sorted(
            path
            for path in target_dir.iterdir()
            if path.is_file() and path.suffix.lower() in allowed_images | allowed_videos
        )
        media: list[dict[str, Any]] = []
        for position, path in enumerate(paths):
            kind = "video" if path.suffix.lower() in allowed_videos else "image"
            media.append(
                {
                    "position": position,
                    "kind": kind,
                    "relative_path": path.relative_to(self.media_dir).as_posix(),
                }
            )
        if not media:
            raise RuntimeError("Instaloader completed without producing an image or video")
        return media

    def close(self) -> None:
        if self.loader is not None:
            try:
                self.loader.close()
            finally:
                self.loader = None

    def __enter__(self) -> "InstaloaderClient":
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


def validate_session(username: str, session_path: Path, media_dir: Path) -> str:
    client = InstaloaderClient(username, session_path, media_dir)
    try:
        return client.connect()
    finally:
        client.close()
