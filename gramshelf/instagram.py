from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable


USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")


class InstagramSessionError(RuntimeError):
    """Raised when an imported Instagram session cannot be used."""


class InstaloaderClient:
    """Thin adapter around Instaloader so synchronization remains easy to test."""

    def __init__(self, username: str, session_path: Path, media_dir: Path):
        if not USERNAME_RE.fullmatch(username):
            raise InstagramSessionError("Instagram username is not valid")
        self.username = username
        self.session_path = session_path
        self.media_dir = media_dir
        self.loader: Any | None = None
        self.logged_in_username: str | None = None

    def _build_loader(self) -> Any:
        import instaloader

        return instaloader.Instaloader(
            quiet=True,
            dirname_pattern=str(self.media_dir / "{target}"),
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

    def connect(self) -> str:
        if not self.session_path.is_file():
            raise InstagramSessionError("No Instagram session has been imported")
        try:
            self.loader = self._build_loader()
            self.loader.load_session_from_file(self.username, str(self.session_path))
            logged_in = self.loader.test_login()
        except Exception as exc:
            self.close()
            raise InstagramSessionError(f"Instagram session could not be loaded: {exc}") from exc
        if not logged_in:
            self.close()
            raise InstagramSessionError("Instagram rejected the imported session")
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
