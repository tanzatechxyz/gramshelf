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
    download_hook = None
    resolved_authors: dict[str, str] = {}

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
            if type(self).download_hook:
                type(self).download_hook()
            return [
                {"position": 0, "kind": "image", "relative_path": f"{shortcode}/{first.name}"},
                {"position": 1, "kind": "video", "relative_path": f"{shortcode}/{second.name}"},
            ]
        path = target / f"{shortcode}.jpg"
        path.write_bytes(b"image")
        if type(self).download_hook:
            type(self).download_hook()
        return [{"position": 0, "kind": "image", "relative_path": f"{shortcode}/{path.name}"}]

    def resolve_author(self, post):
        node = getattr(post, "_node", {})
        owner = node.get("owner", {}) if isinstance(node, dict) else {}
        owner_id = str(owner.get("id", "")) if isinstance(owner, dict) else ""
        if owner_id in self.resolved_authors:
            return self.resolved_authors[owner_id]
        return post.owner_username

    def close(self) -> None:
        pass


def configured_manager(tmp_path: Path) -> tuple[Database, SyncManager, AppConfig]:
    FakeClient.download_hook = None
    FakeClient.resolved_authors = {}
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
    assert database.get_setting("archive_scan_complete") is True
    FakeClient.fail_shortcode = None


def test_completed_scan_with_item_errors_still_enables_known_item_cutoff(
    tmp_path: Path,
) -> None:
    database, manager, _ = configured_manager(tmp_path)
    database.set_settings({"stop_after_known": 3})
    FakeClient.fail_shortcode = "BROKEN4"
    FakeClient.posts = [
        FakePost(
            f"KNOWN{index}",
            "alice",
            f"known {index}",
            datetime(2025, 2, index, tzinfo=UTC),
        )
        for index in range(1, 4)
    ] + [
        FakePost("BROKEN4", "bob", "bad", datetime(2025, 1, 1, tzinfo=UTC))
    ]

    started, first = manager.start("manual")
    assert started
    manager.wait(3)
    first_run = database.get_sync_run(first["id"])
    assert first_run is not None
    assert first_run["status"] == "completed_with_errors"
    assert first_run["discovered_count"] == 4
    assert database.get_setting("archive_scan_complete") is True

    started, second = manager.start("schedule")
    assert started
    manager.wait(3)
    second_run = database.get_sync_run(second["id"])
    assert second_run is not None
    assert second_run["status"] == "success"
    assert second_run["discovered_count"] == 3
    assert second_run["skipped_count"] == 3
    assert second_run["error_count"] == 0
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


class MetadataFailingPost:
    shortcode = "FALLBACK1"
    typename = "GraphImage"
    is_video = False
    date_utc = datetime(2025, 3, 4, tzinfo=UTC)

    def __init__(self):
        self._node = {
            "shortcode": self.shortcode,
            "__typename": self.typename,
            "is_video": False,
            "taken_at_timestamp": int(self.date_utc.timestamp()),
            "owner": {"id": "42"},
            "edge_media_to_caption": {
                "edges": [{"node": {"text": "Caption from cached Saved metadata"}}]
            },
        }

    @property
    def owner_username(self):
        raise RuntimeError("Fetching Post metadata failed.")


def test_sync_archives_item_when_optional_author_metadata_fails(tmp_path: Path) -> None:
    database, manager, _ = configured_manager(tmp_path)
    FakeClient.fail_shortcode = None
    FakeClient.posts = [MetadataFailingPost()]

    started, run = manager.start("test")
    assert started
    manager.wait(3)

    result = database.get_sync_run(run["id"])
    assert result is not None
    assert result["status"] == "success"
    assert result["downloaded_count"] == 1
    item = database.list_items()[0][0]
    assert item["author"] == "unknown"
    assert item["caption"] == "Caption from cached Saved metadata"
    assert item["published_at"].startswith("2025-03-04")


def test_running_sync_can_be_stopped_after_current_item(tmp_path: Path) -> None:
    database, manager, _ = configured_manager(tmp_path)
    FakeClient.fail_shortcode = None
    FakeClient.posts = [
        FakePost(
            f"STOP{index}",
            "alice",
            f"item {index}",
            datetime(2025, 2, index, tzinfo=UTC),
        )
        for index in range(1, 5)
    ]
    stop_results = []
    FakeClient.download_hook = lambda: stop_results.append(manager.stop())

    started, run = manager.start("web")
    assert started
    manager.wait(3)

    result = database.get_sync_run(run["id"])
    assert result is not None
    assert stop_results[0][0] is True
    assert stop_results[0][1]["stopping"] is True
    assert result["status"] == "cancelled"
    assert result["downloaded_count"] == 1
    assert "stopped by administrator" in result["message"]
    assert database.count_items() == 1
    assert manager.status()["stopping"] is False
    assert manager.stop()[0] is False
    FakeClient.download_hook = None


def test_author_repair_updates_existing_unknown_items(tmp_path: Path) -> None:
    database, manager, _ = configured_manager(tmp_path)
    post = MetadataFailingPost()
    FakeClient.posts = [post]
    FakeClient.resolved_authors = {"42": "actual_owner"}
    database.insert_item(
        {
            "shortcode": post.shortcode,
            "instagram_url": f"https://www.instagram.com/p/{post.shortcode}/",
            "author": "unknown",
            "caption": "existing",
            "published_at": "2025-03-04T00:00:00+00:00",
            "downloaded_at": "2025-03-05T00:00:00+00:00",
            "media_type": "image",
            "cover_path": f"{post.shortcode}/{post.shortcode}.jpg",
        },
        [
            {
                "position": 0,
                "kind": "image",
                "relative_path": f"{post.shortcode}/{post.shortcode}.jpg",
            }
        ],
    )

    started, run = manager.start_author_repair()
    assert started
    manager.wait(3)

    result = database.get_sync_run(run["id"])
    assert result is not None
    assert result["status"] == "success"
    assert result["downloaded_count"] == 1
    assert database.get_item_by_shortcode(post.shortcode)["author"] == "actual_owner"
    assert database.count_unknown_authors() == 0
