from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    setup_complete: bool


class MediaOut(BaseModel):
    id: int
    position: int
    kind: Literal["image", "video"]
    relative_path: str
    url: str


class ItemSummaryOut(BaseModel):
    id: int
    shortcode: str
    instagram_url: str
    author: str
    caption: str
    published_at: str
    downloaded_at: str
    media_type: Literal["image", "video", "carousel"]
    cover_path: str | None
    cover_url: str | None
    media_count: int


class ItemOut(BaseModel):
    id: int
    shortcode: str
    instagram_url: str
    author: str
    caption: str
    published_at: str
    downloaded_at: str
    media_type: Literal["image", "video", "carousel"]
    cover_path: str | None
    cover_url: str | None
    media: list[MediaOut]


class ItemListOut(BaseModel):
    items: list[ItemSummaryOut]
    total: int
    limit: int
    offset: int


class SyncErrorOut(BaseModel):
    id: int
    shortcode: str | None = None
    occurred_at: str
    message: str


class SyncRunOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    trigger: str
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    discovered_count: int = 0
    downloaded_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    message: str | None = None
    errors: list[SyncErrorOut] = Field(default_factory=list)


class SyncStartOut(BaseModel):
    started: bool
    run: dict[str, Any]


class SyncStatusOut(BaseModel):
    running: bool
    status: str
    run: dict[str, Any] | None = None


class SettingsOut(BaseModel):
    sync_enabled: bool
    sync_interval_minutes: int
    stop_after_known: int
    instagram_username: str
    session_configured: bool
    session_last_validated_at: str | None
    session_last_error: str | None
    login_pending: bool
    pending_username: str | None
    api_token: str
    next_scheduled_sync: str | None


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sync_enabled: bool | None = None
    sync_interval_minutes: int | None = Field(default=None, ge=15, le=10080)
    stop_after_known: int | None = Field(default=None, ge=1, le=50)


class SessionStatusOut(BaseModel):
    configured: bool
    username: str
    last_validated_at: str | None
    last_error: str | None
    login_pending: bool = False
    pending_username: str | None = None


class SessionLoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=31)
    password: SecretStr = Field(min_length=1, max_length=512)


class SessionTwoFactorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: SecretStr = Field(min_length=1, max_length=32)


class AppStatusOut(BaseModel):
    version: str
    setup_complete: bool
    item_count: int
    instagram_session_configured: bool
    sync: dict[str, Any]
    next_scheduled_sync: str | None


class MessageOut(BaseModel):
    message: str
