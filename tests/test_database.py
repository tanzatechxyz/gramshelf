from __future__ import annotations

from pathlib import Path

from gramshelf.database import Database


def add_item(database: Database, shortcode: str, author: str, published_at: str, media_type: str = "image") -> int:
    relative = f"{shortcode}/{shortcode}.jpg"
    return database.insert_item(
        {
            "shortcode": shortcode,
            "instagram_url": f"https://www.instagram.com/p/{shortcode}/",
            "author": author,
            "caption": f"Caption for {shortcode}",
            "published_at": published_at,
            "downloaded_at": "2026-07-15T12:00:00+00:00",
            "media_type": media_type,
            "cover_path": relative,
        },
        [{"position": 0, "kind": "image", "relative_path": relative}],
    )


def test_items_are_chronological_and_filterable(tmp_path: Path) -> None:
    database = Database(tmp_path / "db.sqlite3")
    database.initialize()
    older_id = add_item(database, "OLD1", "alice", "2024-01-01T00:00:00+00:00")
    newer_id = add_item(database, "NEW2", "bob", "2025-02-01T00:00:00+00:00", "carousel")

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
