from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from gramshelf.instagram import (
    InstagramSessionError,
    InstaloaderClient,
    SessionLoginManager,
    validate_session,
)


class FakeTwoFactorRequired(Exception):
    pass


class FakeBadCredentials(Exception):
    pass


class FakeLoader:
    logged_in = "archive_user"
    closed = False
    options = {}
    require_two_factor = False
    password_seen: str | None = None

    def __init__(self, **options):
        type(self).options = options
        type(self).closed = False
        self.context = object()

    def load_session_from_file(self, username: str, filename: str) -> None:
        assert username
        assert Path(filename).is_file()

    def login(self, username: str, password: str) -> None:
        type(self).logged_in = username
        type(self).password_seen = password
        if self.require_two_factor:
            raise FakeTwoFactorRequired()

    def two_factor_login(self, code: str) -> None:
        if code != "123456":
            raise FakeBadCredentials("invalid code")

    def save_session_to_file(self, filename: str) -> None:
        Path(filename).write_bytes(b"saved-instaloader-session")

    def test_login(self) -> str | None:
        return self.logged_in

    def download_post(self, post, target: str) -> bool:
        directory = Path(self.options["dirname_pattern"].replace("{target}", target))
        (directory / f"{post.shortcode}_1.jpg").write_bytes(b"image")
        (directory / f"{post.shortcode}_2.mp4").write_bytes(b"video")
        (directory / "ignored.txt").write_text("ignored")
        return True

    def close(self) -> None:
        type(self).closed = True


class FakeProfile:
    @classmethod
    def from_username(cls, context, username: str):
        return cls()

    def get_saved_posts(self):
        return [SimpleNamespace(shortcode="ABC")]


@pytest.fixture
def fake_instaloader(monkeypatch):
    module = SimpleNamespace(
        Instaloader=FakeLoader,
        Profile=FakeProfile,
        TwoFactorAuthRequiredException=FakeTwoFactorRequired,
        BadCredentialsException=FakeBadCredentials,
    )
    monkeypatch.setitem(sys.modules, "instaloader", module)
    FakeLoader.logged_in = "archive_user"
    FakeLoader.require_two_factor = False
    FakeLoader.password_seen = None
    return module


def test_client_validates_lists_and_downloads_all_media(tmp_path: Path, fake_instaloader) -> None:
    session = tmp_path / "session"
    session.write_bytes(b"session")
    media = tmp_path / "media"
    media.mkdir()
    client = InstaloaderClient("archive_user", session, media)

    assert client.connect() == "archive_user"
    assert list(client.iter_saved_posts())[0].shortcode == "ABC"
    files = client.download_post(SimpleNamespace(shortcode="ABC"), "ABC")
    assert [entry["kind"] for entry in files] == ["image", "video"]
    assert FakeLoader.options["download_video_thumbnails"] is False
    assert FakeLoader.options["save_metadata"] is False
    client.close()
    assert FakeLoader.closed


def test_session_rejects_wrong_account_and_bad_username(tmp_path: Path, fake_instaloader) -> None:
    session = tmp_path / "session"
    session.write_bytes(b"session")
    media = tmp_path / "media"
    media.mkdir()
    FakeLoader.logged_in = "someone_else"

    with pytest.raises(InstagramSessionError, match="belongs to"):
        validate_session("archive_user", session, media)
    with pytest.raises(InstagramSessionError, match="not valid"):
        InstaloaderClient("not an instagram name", session, media)


def test_session_can_be_created_from_credentials(tmp_path: Path, fake_instaloader) -> None:
    media = tmp_path / "media"
    media.mkdir()
    session = tmp_path / "session"
    manager = SessionLoginManager(session, media)

    result = manager.start("@archive_user", "one-time-password")

    assert result == {"username": "archive_user", "two_factor_required": False}
    assert session.read_bytes() == b"saved-instaloader-session"
    assert b"one-time-password" not in session.read_bytes()
    assert session.stat().st_mode & 0o777 == 0o600
    assert FakeLoader.password_seen == "one-time-password"
    assert FakeLoader.closed


def test_session_creation_supports_two_factor(tmp_path: Path, fake_instaloader) -> None:
    media = tmp_path / "media"
    media.mkdir()
    session = tmp_path / "session"
    manager = SessionLoginManager(session, media)
    FakeLoader.require_two_factor = True

    result = manager.start("archive_user", "one-time-password")
    assert result["two_factor_required"] is True
    assert manager.pending_username() == "archive_user"
    assert not session.exists()

    with pytest.raises(InstagramSessionError, match="verification failed"):
        manager.complete_two_factor("wrong")
    assert manager.pending_username() == "archive_user"

    assert manager.complete_two_factor("123456") == "archive_user"
    assert manager.pending_username() is None
    assert session.read_bytes() == b"saved-instaloader-session"
