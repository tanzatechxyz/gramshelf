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
        json={
            "sync_enabled": False,
            "sync_interval_minutes": 60,
            "stop_after_known": 5,
            "archive_scan_complete": True,
        },
    )
    assert settings.status_code == 200
    assert settings.json()["sync_enabled"] is False
    assert settings.json()["sync_interval_minutes"] == 60
    assert settings.json()["archive_scan_complete"] is True

    schema = client.get("/api/openapi.json", headers={"Authorization": f"Bearer {token}"})
    assert schema.status_code == 200
    assert "/api/v1/items" in schema.json()["paths"]
    assert "/api/v1/instagram/session/login" in schema.json()["paths"]
    assert "/api/v1/instagram/session/two-factor" in schema.json()["paths"]
    assert "/api/v1/sync/test" in schema.json()["paths"]
    assert "/api/v1/sync/stop" in schema.json()["paths"]
    assert "/api/v1/import/legacy" in schema.json()["paths"]
    assert "/api/v1/authors/repair" in schema.json()["paths"]


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


def test_item_page_navigates_in_timeline_order(client, app) -> None:
    complete_setup(client, app)

    def insert(shortcode: str, published_at: str) -> int:
        relative_path = f"{shortcode}/{shortcode}.jpg"
        return app.state.database.insert_item(
            {
                "shortcode": shortcode,
                "instagram_url": f"https://www.instagram.com/p/{shortcode}/",
                "author": "alice",
                "caption": shortcode,
                "published_at": published_at,
                "downloaded_at": "2026-07-15T12:00:00+00:00",
                "media_type": "image",
                "cover_path": relative_path,
            },
            [{"position": 0, "kind": "image", "relative_path": relative_path}],
        )

    older_id = insert("OLDER", "2024-01-01T00:00:00+00:00")
    middle_id = insert("MIDDLE", "2025-01-01T00:00:00+00:00")
    newer_id = insert("NEWER", "2026-01-01T00:00:00+00:00")

    page = client.get(f"/items/{middle_id}")
    assert page.status_code == 200
    assert f'href="http://testserver/items/{newer_id}" rel="prev"' in page.text
    assert f'href="http://testserver/items/{older_id}" rel="next"' in page.text
    assert "View on Instagram" in page.text


def test_archive_scan_state_can_be_changed_from_settings(client, app) -> None:
    complete_setup(client, app)
    page = client.get("/settings")
    assert "Known-item cutoff state" in page.text
    assert "Mark scan complete" in page.text

    response = client.post(
        "/settings/archive-scan",
        data={"complete": "true", "csrf": csrf_from(page.text)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert app.state.database.get_setting("archive_scan_complete") is True

    page = client.get("/settings")
    assert "Force next full scan" in page.text
    response = client.post(
        "/settings/archive-scan",
        data={"complete": "false", "csrf": csrf_from(page.text)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert app.state.database.get_setting("archive_scan_complete") is False


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


def test_web_ui_can_create_session_from_credentials(client, app, config, monkeypatch) -> None:
    complete_setup(client, app)
    manager = app.state.session_login_manager

    def create_session(username: str, password: str):
        assert password == "one-time-password"
        config.session_path.write_bytes(b"created session")
        return {"username": username, "two_factor_required": False}

    monkeypatch.setattr(manager, "start", create_session)
    page = client.get("/settings")
    assert "Create in GramShelf" in page.text
    assert "Test download (max 3)" not in page.text

    response = client.post(
        "/settings/session/login",
        data={
            "username": "archive_user",
            "password": "one-time-password",
            "csrf": csrf_from(page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert config.session_path.read_bytes() == b"created session"
    assert app.state.database.get_setting("instagram_username") == "archive_user"
    assert "Test download (max 3)" in client.get("/settings").text


def test_api_session_login_supports_two_factor(client, app, config, monkeypatch) -> None:
    complete_setup(client, app)
    manager = app.state.session_login_manager
    pending = {"username": None}

    def begin(username: str, password: str):
        assert password == "one-time-password"
        pending["username"] = username
        return {"username": username, "two_factor_required": True}

    def pending_username():
        return pending["username"]

    def complete(code: str):
        assert code == "123456"
        username = str(pending["username"])
        pending["username"] = None
        config.session_path.write_bytes(b"two-factor session")
        return username

    monkeypatch.setattr(manager, "start", begin)
    monkeypatch.setattr(manager, "pending_username", pending_username)
    monkeypatch.setattr(manager, "complete_two_factor", complete)

    response = client.post(
        "/api/v1/instagram/session/login",
        json={"username": "archive_user", "password": "one-time-password"},
    )
    assert response.status_code == 200
    assert response.json()["login_pending"] is True
    assert response.json()["pending_username"] == "archive_user"
    settings_page = client.get("/settings")
    assert "Enter the Instagram verification code" in settings_page.text

    response = client.post(
        "/api/v1/instagram/session/two-factor", json={"code": "123456"}
    )
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert response.json()["login_pending"] is False
    assert response.json()["username"] == "archive_user"


def test_test_sync_endpoint_uses_three_item_limit(client, app, monkeypatch) -> None:
    complete_setup(client, app)
    calls = []

    def start(trigger: str, max_downloads=None):
        calls.append((trigger, max_downloads))
        return True, {"id": 99, "status": "queued"}

    monkeypatch.setattr(app.state.sync_manager, "start", start)
    response = client.post("/api/v1/sync/test")

    assert response.status_code == 202
    assert response.json()["started"] is True
    assert calls == [("test", 3)]


def test_running_sync_can_be_stopped_from_web_and_api(client, app, monkeypatch) -> None:
    complete_setup(client, app)
    manager = app.state.sync_manager
    running = {
        "id": 42,
        "status": "running",
        "running": True,
        "stopping": False,
        "discovered_count": 2,
        "downloaded_count": 1,
        "skipped_count": 0,
    }
    calls = []

    monkeypatch.setattr(manager, "status", lambda: running)

    def stop():
        calls.append("stop")
        return True, {**running, "stopping": True}

    monkeypatch.setattr(manager, "stop", stop)
    page = client.get("/activity")
    assert "Stop current job" in page.text

    response = client.post(
        "/sync/stop",
        data={"csrf": csrf_from(page.text)},
        follow_redirects=False,
    )
    assert response.status_code == 303

    response = client.post("/api/v1/sync/stop")
    assert response.status_code == 200
    assert response.json()["stop_requested"] is True
    assert response.json()["run"]["stopping"] is True
    assert calls == ["stop", "stop"]


def test_maintenance_jobs_can_be_started_from_api(client, app, monkeypatch) -> None:
    complete_setup(client, app)
    calls = []

    def start_import():
        calls.append("import")
        return True, {"id": 70, "status": "queued"}

    def start_repair():
        calls.append("repair")
        return True, {"id": 71, "status": "queued"}

    monkeypatch.setattr(app.state.sync_manager, "start_import", start_import)
    monkeypatch.setattr(app.state.sync_manager, "start_author_repair", start_repair)

    assert client.post("/api/v1/import/legacy").status_code == 202
    assert client.post("/api/v1/authors/repair").status_code == 202
    assert calls == ["import", "repair"]
    page = client.get("/settings")
    assert "Previous Instaloader archive" in page.text
    assert "Repair unknown authors" in page.text


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
