from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gramshelf.app import create_app
from gramshelf.config import AppConfig


class EmptyInstagramClient:
    def __init__(self, username: str, session_path: Path, media_dir: Path):
        self.username = username

    def connect(self) -> str:
        return self.username

    def iter_saved_posts(self):
        return []

    def close(self) -> None:
        pass


@pytest.fixture
def config(tmp_path: Path) -> AppConfig:
    return AppConfig(data_dir=tmp_path / "data", media_dir=tmp_path / "media")


@pytest.fixture
def app(config: AppConfig):
    return create_app(config, client_factory=EmptyInstagramClient)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


def csrf_from(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, "CSRF input was not rendered"
    return match.group(1)


def complete_setup(client: TestClient, app) -> str:
    response = client.get("/setup")
    csrf = csrf_from(response.text)
    response = client.post(
        "/setup",
        data={
            "admin_username": "admin",
            "password": "correct horse battery staple",
            "password_confirm": "correct horse battery staple",
            "csrf": csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    return str(app.state.database.get_setting("api_token"))
