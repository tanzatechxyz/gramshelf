from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from gramshelf.instagram import InstagramSessionError, InstaloaderClient, validate_session


class FakeLoader:
    logged_in = "archive_user"
    closed = False
    options = {}

    def __init__(self, **options):
        type(self).options = options
        type(self).closed = False
        self.context = object()

    def load_session_from_file(self, username: str, filename: str) -> None:
        assert username
        assert Path(filename).is_file()

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
    module = SimpleNamespace(Instaloader=FakeLoader, Profile=FakeProfile)
    monkeypatch.setitem(sys.modules, "instaloader", module)
    FakeLoader.logged_in = "archive_user"
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
