from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from gramshelf.config import AppConfig
from gramshelf.database import Database
from gramshelf.sync import SyncManager


@dataclass
class FakePost:
    shortcode: str
    owner_username: str
    caption: str
    date_utc: datetime
    typename: str = "GraphImage"
    is_video: bool = False


class FakeClient:
    posts: list[FakePost] = []
    fail_shortcode: str | None = None

    def __init__(self, username: str, session_path: Path, media_dir: Path):
        self.username = username
        self.media_dir = media_dir

    def connect(self) -> str:
        return self.username

    def iter_saved_posts(self):
        return iter(self.posts)

    def download_post(self, post: FakePost, shortcode: str):
        if shortcode == self.fail_shortcode:
            raise RuntimeError("simulated media error")
        target = self.media_dir / shortcode
        target.mkdir(parents=True, exist_ok=True)
        if post.typename == "GraphSidecar":
            first = target / f"{shortcode}_1.jpg"
            second = target / f"{shortcode}_2.mp4"
            first.write_bytes(b"image")
            second.write_bytes(b"video")
            return [
                {"position": 0, "kind": "image", "relative_path": f"{shortcode}/{first.name}"},
                {"position": 1, "kind": "video", "relative_path": f"{shortcode}/{second.name}"},
            ]
        path = target / f"{shortcode}.jpg"
        path.write_bytes(b"image")
        return [{"position": 0, "kind": "image", "relative_path": f"{shortcode}/{path.name}"}]

    def close(self) -> None:
        pass


def configured_manager(tmp_path: Path) -> tuple[Database, SyncManager, AppConfig]:
    config = AppConfig(tmp_path / "data", tmp_path / "media")
    config.prepare()
    config.session_path.write_bytes(b"fake session")
    database = Database(config.database_path)
    database.initialize()
    database.set_settings({"instagram_username": "archive_user", "stop_after_known": 2})
    return database, SyncManager(database, config, client_factory=FakeClient), config


def test_sync_downloads_carousels_and_avoids_duplicates(tmp_path: Path) -> None:
    database, manager, _ = configured_manager(tmp_path)
    FakeClient.fail_shortcode = None
    FakeClient.posts = [
        FakePost("CAROUSEL1", "alice", "two files", datetime(2025, 2, 1, tzinfo=UTC), "GraphSidecar"),
        FakePost("IMAGE2", "bob", "one file", datetime(2024, 1, 1, tzinfo=UTC)),
    ]

    started, first = manager.start("test")
    assert started
    manager.wait(3)
    first_run = database.get_sync_run(first["id"])
    assert first_run is not None
    assert first_run["status"] == "success"
    assert first_run["downloaded_count"] == 2
    assert database.count_items() == 2
    assert database.get_setting("archive_scan_complete") is True

    carousel, _ = database.list_items(media_type="carousel")
    detail = database.get_item(carousel[0]["id"])
    assert detail is not None
    assert [media["kind"] for media in detail["media"]] == ["image", "video"]

    started, second = manager.start("test")
    assert started
    manager.wait(3)
    second_run = database.get_sync_run(second["id"])
    assert second_run is not None
    assert second_run["downloaded_count"] == 0
    assert second_run["skipped_count"] == 2
    assert database.count_items() == 2


def test_sync_keeps_running_after_item_error(tmp_path: Path) -> None:
    database, manager, _ = configured_manager(tmp_path)
    FakeClient.fail_shortcode = "BROKEN1"
    FakeClient.posts = [
        FakePost("BROKEN1", "alice", "bad", datetime(2025, 2, 1, tzinfo=UTC)),
        FakePost("GOOD2", "bob", "good", datetime(2025, 1, 1, tzinfo=UTC)),
    ]

    started, run = manager.start("test")
    assert started
    manager.wait(3)
    result = database.get_sync_run(run["id"])
    assert result is not None
    assert result["status"] == "completed_with_errors"
    assert result["downloaded_count"] == 1
    assert result["error_count"] == 1
    assert result["errors"][0]["shortcode"] == "BROKEN1"
    assert database.get_setting("archive_scan_complete") is False
    FakeClient.fail_shortcode = None


def test_test_sync_downloads_at_most_three_items(tmp_path: Path) -> None:
    database, manager, _ = configured_manager(tmp_path)
    FakeClient.fail_shortcode = None
    FakeClient.posts = [
        FakePost(
            f"ITEM{index}",
            "alice",
            f"item {index}",
            datetime(2025, 1, index, tzinfo=UTC),
        )
        for index in range(1, 6)
    ]

    started, run = manager.start("test", max_downloads=3)
    assert started
    manager.wait(3)

    result = database.get_sync_run(run["id"])
    assert result is not None
    assert result["status"] == "success"
    assert result["downloaded_count"] == 3
    assert result["discovered_count"] == 3
    assert "test limit reached" in result["message"]
    assert database.count_items() == 3
    assert database.get_setting("archive_scan_complete") is False
