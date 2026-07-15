from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from gramshelf.config import AppConfig
from gramshelf.database import Database
from gramshelf.sync import SyncManager


def write_post_metadata(
    path: Path,
    shortcode: str,
    username: str,
    *,
    typename: str = "GraphImage",
    caption: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "node": {
                    "id": "1234",
                    "shortcode": shortcode,
                    "__typename": typename,
                    "is_video": typename == "GraphVideo",
                    "date": int(datetime(2024, 5, 6, 7, 8, tzinfo=UTC).timestamp()),
                    "owner": {"id": "42", "username": username},
                    "edge_media_to_caption": {
                        "edges": [{"node": {"text": caption}}] if caption else []
                    },
                },
                "instaloader": {"version": "4.15.2", "node_type": "Post"},
            }
        ),
        encoding="utf-8",
    )


def test_legacy_import_copies_media_deduplicates_and_enriches(tmp_path: Path) -> None:
    import_dir = tmp_path / "legacy"
    config = AppConfig(
        data_dir=tmp_path / "data",
        media_dir=tmp_path / "media",
        import_dir=import_dir,
    )
    config.prepare()
    database = Database(config.database_path)
    database.initialize()

    alice = import_dir / "alice"
    new_base = "2024-05-06_07-08-00_UTC_LEGACY1"
    new_json = alice / f"{new_base}.json"
    write_post_metadata(new_json, "LEGACY1", "alice", typename="GraphVideo")
    (alice / f"{new_base}.txt").write_text("Caption from legacy text", encoding="utf-8")
    (alice / f"{new_base}.png").write_bytes(b"thumbnail")
    (alice / f"{new_base}.mp4").write_bytes(b"video")

    existing_media = config.media_dir / "EXIST1" / "EXIST1.jpg"
    existing_media.parent.mkdir(parents=True)
    existing_media.write_bytes(b"existing")
    database.insert_item(
        {
            "shortcode": "EXIST1",
            "instagram_url": "https://www.instagram.com/p/EXIST1/",
            "author": "unknown",
            "caption": "",
            "published_at": "2024-01-01T00:00:00+00:00",
            "downloaded_at": "2024-01-02T00:00:00+00:00",
            "media_type": "image",
            "cover_path": "EXIST1/EXIST1.jpg",
        },
        [{"position": 0, "kind": "image", "relative_path": "EXIST1/EXIST1.jpg"}],
    )
    bob = import_dir / "bob"
    existing_base = "2024-01-01_00-00-00_UTC_EXIST1"
    write_post_metadata(
        bob / f"{existing_base}.json",
        "EXIST1",
        "bob",
        caption="Recovered caption",
    )

    manager = SyncManager(database, config)
    started, run = manager.start_import()
    assert started
    manager.wait(5)

    result = database.get_sync_run(run["id"])
    assert result is not None
    assert result["status"] == "success"
    assert result["discovered_count"] == 2
    assert result["downloaded_count"] == 2
    assert "Imported 1, updated 1" in result["message"]

    imported = database.get_item_by_shortcode("LEGACY1")
    assert imported is not None
    assert imported["author"] == "alice"
    assert imported["caption"] == "Caption from legacy text"
    assert imported["media_type"] == "video"
    assert imported["published_at"].startswith("2024-05-06T07:08:00")
    detail = database.get_item(imported["id"])
    assert detail is not None
    assert [entry["kind"] for entry in detail["media"]] == ["image", "video"]
    assert all((config.media_dir / entry["relative_path"]).is_file() for entry in detail["media"])
    assert new_json.is_file()
    assert (alice / f"{new_base}.mp4").is_file()

    enriched = database.get_item_by_shortcode("EXIST1")
    assert enriched["author"] == "bob"
    assert enriched["caption"] == "Recovered caption"
    assert list((config.media_dir / "EXIST1").iterdir()) == [existing_media]

    started, second = manager.start_import()
    assert started
    manager.wait(5)
    repeated = database.get_sync_run(second["id"])
    assert repeated["downloaded_count"] == 0
    assert repeated["skipped_count"] == 2
    assert database.count_items() == 2
