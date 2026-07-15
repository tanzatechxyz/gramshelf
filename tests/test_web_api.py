from __future__ import annotations

import gramshelf.app as app_module

from .conftest import complete_setup, csrf_from


def test_setup_login_and_api_auth(client, app) -> None:
    assert client.get("/api/v1/health").json()["setup_complete"] is False
    assert client.get("/timeline", follow_redirects=False).status_code == 303

    token = complete_setup(client, app)
    assert client.get("/settings").status_code == 200
    assert token.startswith("gs_")

    client.cookies.clear()
    assert client.get("/api/v1/status").status_code == 401
    response = client.get(
        "/api/v1/status", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["item_count"] == 0

    settings = client.patch(
        "/api/v1/settings",
        headers={"Authorization": f"Bearer {token}"},
        json={"sync_enabled": False, "sync_interval_minutes": 60, "stop_after_known": 5},
    )
    assert settings.status_code == 200
    assert settings.json()["sync_enabled"] is False
    assert settings.json()["sync_interval_minutes"] == 60

    schema = client.get("/api/openapi.json", headers={"Authorization": f"Bearer {token}"})
    assert schema.status_code == 200
    assert "/api/v1/items" in schema.json()["paths"]


def test_timeline_search_and_item_api(client, app, config) -> None:
    complete_setup(client, app)
    media_path = config.media_dir / "ABC123" / "ABC123.jpg"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"jpeg")
    item_id = app.state.database.insert_item(
        {
            "shortcode": "ABC123",
            "instagram_url": "https://www.instagram.com/p/ABC123/",
            "author": "alice",
            "caption": "A searchable garden caption",
            "published_at": "2025-06-01T12:00:00+00:00",
            "downloaded_at": "2026-07-15T12:00:00+00:00",
            "media_type": "image",
            "cover_path": "ABC123/ABC123.jpg",
        },
        [{"position": 0, "kind": "image", "relative_path": "ABC123/ABC123.jpg"}],
    )

    timeline = client.get("/timeline?q=garden")
    assert timeline.status_code == 200
    assert "searchable garden caption" in timeline.text

    response = client.get(f"/api/v1/items/{item_id}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["author"] == "alice"
    assert payload["media"][0]["url"].endswith("/media/ABC123/ABC123.jpg")
    assert client.get("/media/ABC123/ABC123.jpg").content == b"jpeg"
    assert client.get(f"/items/{item_id}").status_code == 200
    assert client.get("/activity").status_code == 200
    assert client.get("/diagnostics").status_code == 200


def test_session_import_validate_and_remove(client, app, monkeypatch) -> None:
    complete_setup(client, app)
    monkeypatch.setattr(app_module, "validate_session", lambda username, path, media: username)

    response = client.post(
        "/api/v1/instagram/session",
        data={"username": "archive_user"},
        files={"session_file": ("session-archive_user", b"trusted session", "application/octet-stream")},
    )
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["username"] == "archive_user"

    response = client.post("/api/v1/instagram/session/validate")
    assert response.status_code == 200
    assert response.json()["last_error"] is None

    response = client.delete("/api/v1/instagram/session")
    assert response.status_code == 200
    assert not app.state.config.session_path.exists()


def test_csrf_rejects_invalid_form(client, app) -> None:
    complete_setup(client, app)
    response = client.post("/settings", data={
        "sync_interval_minutes": 720,
        "stop_after_known": 3,
        "sync_enabled": "on",
        "csrf": "invalid",
    })
    assert response.status_code == 403

    page = client.get("/settings")
    assert csrf_from(page.text)
