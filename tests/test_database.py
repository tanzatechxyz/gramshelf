from __future__ import annotations

from pathlib import Path

from gramshelf.database import Database


def add_item(
    database: Database,
    shortcode: str,
    author: str,
    published_at: str,
    media_type: str = "image",
    downloaded_at: str = "2026-07-15T12:00:00+00:00",
) -> int:
    relative = f"{shortcode}/{shortcode}.jpg"
    return database.insert_item(
        {
            "shortcode": shortcode,
            "instagram_url": f"https://www.instagram.com/p/{shortcode}/",
            "author": author,
            "caption": f"Caption for {shortcode}",
            "published_at": published_at,
            "downloaded_at": downloaded_at,
            "media_type": media_type,
            "cover_path": relative,
        },
        [{"position": 0, "kind": "image", "relative_path": relative}],
    )


def test_items_are_ordered_by_download_and_filterable(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    older_id = add_item(
        database,
        "OLD1",
        "alice",
        "2025-02-01T00:00:00+00:00",
        downloaded_at="2026-01-01T00:00:00+00:00",
    )
    newer_id = add_item(
        database,
        "NEW2",
        "bob",
        "2024-01-01T00:00:00+00:00",
        "carousel",
        downloaded_at="2026-02-01T00:00:00+00:00",
    )

    items, total = database.list_items()
    assert total == 2
    assert [item["id"] for item in items] == [newer_id, older_id]

    items, total = database.list_items(query="old1")
    assert total == 1 and items[0]["author"] == "alice"

    items, total = database.list_items(author="BOB", media_type="carousel")
    assert total == 1 and items[0]["id"] == newer_id

    detail = database.get_item(newer_id)
    assert detail is not None
    assert detail["media"][0]["relative_path"] == "NEW2/NEW2.jpg"


def test_item_neighbors_follow_timeline_order(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    older_id = add_item(
        database,
        "OLDER",
        "alice",
        "2026-01-01T00:00:00+00:00",
        downloaded_at="2024-01-01T00:00:00+00:00",
    )
    middle_id = add_item(
        database,
        "MIDDLE",
        "alice",
        "2025-01-01T00:00:00+00:00",
        downloaded_at="2025-01-01T00:00:00+00:00",
    )
    newer_id = add_item(
        database,
        "NEWER",
        "alice",
        "2024-01-01T00:00:00+00:00",
        downloaded_at="2026-01-01T00:00:00+00:00",
    )

    assert database.get_item_neighbors(newer_id) == {
        "previous_id": None,
        "next_id": middle_id,
    }
    assert database.get_item_neighbors(middle_id) == {
        "previous_id": newer_id,
        "next_id": older_id,
    }
    assert database.get_item_neighbors(older_id) == {
        "previous_id": middle_id,
        "next_id": None,
    }


def test_sync_history_records_errors(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    run_id = database.create_sync_run("test")
    database.update_sync_run(run_id, status="running", started_at="2026-07-15T00:00:00+00:00")
    database.add_sync_error(run_id, "download failed", "ABC")
    database.update_sync_run(run_id, status="error", error_count=1)

    run = database.get_sync_run(run_id)
    assert run is not None
    assert run["errors"][0]["shortcode"] == "ABC"
    assert database.recent_errors()[0]["message"] == "download failed"


def test_item_metadata_can_be_repaired_by_shortcode(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    item_id = add_item(database, "UNKNOWN1", "unknown", "2025-01-01T00:00:00+00:00")

    assert database.count_unknown_authors() == 1
    assert database.update_item_metadata("UNKNOWN1", author="alice") is True
    assert database.get_item(item_id)["author"] == "alice"
    assert database.get_item_by_shortcode("UNKNOWN1")["id"] == item_id
    assert database.count_unknown_authors() == 0


def test_upgrade_restores_cutoff_after_completed_sync_with_item_errors(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    run_id = database.create_sync_run("web")
    database.update_sync_run(
        run_id,
        status="completed_with_errors",
        completed_at="2026-07-16T00:00:00+00:00",
        error_count=2,
    )
    database.set_settings({"archive_scan_complete": False})
    database.set_settings({"archive_scan_state_migrated": False})

    database.initialize()

    assert database.get_setting("archive_scan_complete") is True
    assert database.get_setting("archive_scan_state_migrated") is True

    database.set_settings({"archive_scan_complete": False})
    database.initialize()
    assert database.get_setting("archive_scan_complete") is False
