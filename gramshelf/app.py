from __future__ import annotations

import hmac
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from . import __version__
from .config import AppConfig
from .database import Database, utc_now
from .instagram import (
    InstaloaderClient,
    InstagramSessionError,
    SessionLoginManager,
    validate_session,
)
from .scheduler import SchedulerController
from .schemas import (
    AppStatusOut,
    HealthResponse,
    ItemListOut,
    ItemOut,
    MessageOut,
    SessionLoginIn,
    SessionStatusOut,
    SessionTwoFactorIn,
    SettingsOut,
    SettingsUpdate,
    SyncRunOut,
    SyncStartOut,
    SyncStopOut,
    SyncStatusOut,
)
from .security import hash_password, new_api_token, new_csrf_token, verify_password
from .sync import ClientFactory, SyncManager


PACKAGE_DIR = Path(__file__).parent
MAX_SESSION_BYTES = 2 * 1024 * 1024
bearer_scheme = HTTPBearer(auto_error=False, scheme_name="GramShelf API token")


def _format_datetime(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y, %H:%M UTC")
    except (ValueError, TypeError):
        return str(value)


def _excerpt(value: str, length: int = 170) -> str:
    compact = " ".join((value or "").split())
    return compact if len(compact) <= length else f"{compact[: length - 1].rstrip()}…"


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def create_app(
    config: AppConfig | None = None,
    client_factory: ClientFactory = InstaloaderClient,
) -> FastAPI:
    config = config or AppConfig.from_env()
    config.prepare()
    database = Database(config.database_path)
    database.initialize()
    secret = config.load_or_create_secret()
    sync_manager = SyncManager(database, config, client_factory=client_factory)
    scheduler = SchedulerController(database, sync_manager)
    session_login_manager = SessionLoginManager(config.session_path, config.media_dir)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.mark_abandoned_runs()
        scheduler.start()
        try:
            yield
        finally:
            scheduler.shutdown()
            session_login_manager.cancel()

    app = FastAPI(
        title="GramShelf API",
        summary="Archive and browse Instagram Saved posts",
        description=(
            "All endpoints except health require either an authenticated administrator "
            "session or the Bearer token shown on the Settings page."
        ),
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        root_path=config.root_path,
        lifespan=lifespan,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="gramshelf_session",
        max_age=60 * 60 * 24 * 30,
        same_site="lax",
        https_only=config.secure_cookies,
    )
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    app.state.config = config
    app.state.database = database
    app.state.sync_manager = sync_manager
    app.state.scheduler = scheduler
    app.state.session_login_manager = session_login_manager

    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    templates.env.filters["datetime"] = _format_datetime
    templates.env.filters["excerpt"] = _excerpt
    templates.env.filters["human_bytes"] = _human_bytes

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[..., Any]):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.endswith("/api/docs"):
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
                "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' data:",
            )
        else:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; media-src 'self'; "
                "style-src 'self'; script-src 'self'; frame-ancestors 'none'",
            )
        return response

    def db_from(request: Request) -> Database:
        return request.app.state.database

    def csrf_token(request: Request) -> str:
        token = request.session.get("csrf_token")
        if not token:
            token = new_csrf_token()
            request.session["csrf_token"] = token
        return str(token)

    def verify_csrf(request: Request, supplied: str) -> None:
        expected = request.session.get("csrf_token", "")
        if not expected or not hmac.compare_digest(str(expected), supplied):
            raise HTTPException(status_code=403, detail="Invalid form token. Refresh and try again.")

    def flash(request: Request, message: str, level: str = "info") -> None:
        messages = list(request.session.get("flash", []))
        messages.append({"message": message, "level": level})
        request.session["flash"] = messages[-4:]

    def render(request: Request, name: str, **context: Any) -> HTMLResponse:
        values = {
            "request": request,
            "version": __version__,
            "csrf_token": csrf_token(request),
            "is_authenticated": bool(request.session.get("admin_authenticated")),
            "flash_messages": request.session.pop("flash", []),
            "sync_status": sync_manager.status(),
            **context,
        }
        return templates.TemplateResponse(request=request, name=name, context=values)

    def require_web_admin(request: Request) -> bool:
        if not db_from(request).is_setup():
            raise HTTPException(status_code=303, headers={"Location": str(request.url_for("setup"))})
        if not request.session.get("admin_authenticated"):
            raise HTTPException(status_code=303, headers={"Location": str(request.url_for("login"))})
        return True

    def require_api_auth(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    ) -> bool:
        if request.session.get("admin_authenticated"):
            return True
        expected = str(db_from(request).get_setting("api_token", ""))
        if (
            credentials is not None
            and credentials.scheme.casefold() == "bearer"
            and expected
            and hmac.compare_digest(credentials.credentials, expected)
        ):
            return True
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator login or valid Bearer token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def media_url(request: Request, relative_path: str | None) -> str | None:
        if not relative_path:
            return None
        return str(request.url_for("media_file", path=relative_path))

    def item_summary(request: Request, item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result["cover_url"] = media_url(request, item.get("cover_path"))
        return result

    def item_detail(request: Request, item: dict[str, Any]) -> dict[str, Any]:
        result = dict(item)
        result["cover_url"] = media_url(request, item.get("cover_path"))
        result["media"] = [
            {**entry, "url": media_url(request, entry["relative_path"])}
            for entry in item.get("media", [])
        ]
        return result

    def settings_payload(request: Request) -> dict[str, Any]:
        values = db_from(request).get_settings()
        pending_username = session_login_manager.pending_username()
        return {
            "sync_enabled": bool(values.get("sync_enabled", True)),
            "sync_interval_minutes": int(values.get("sync_interval_minutes", 720)),
            "stop_after_known": int(values.get("stop_after_known", 3)),
            "instagram_username": str(values.get("instagram_username", "")),
            "session_configured": config.session_path.is_file(),
            "session_last_validated_at": values.get("session_last_validated_at"),
            "session_last_error": values.get("session_last_error"),
            "login_pending": pending_username is not None,
            "pending_username": pending_username,
            "api_token": str(values.get("api_token", "")),
            "next_scheduled_sync": scheduler.next_run_at(),
            "legacy_import_path": str(config.import_dir),
            "legacy_import_available": config.import_dir.is_dir(),
            "unknown_author_count": database.count_unknown_authors(),
        }

    def session_payload(request: Request) -> dict[str, Any]:
        values = db_from(request).get_settings(
            ["instagram_username", "session_last_validated_at", "session_last_error"]
        )
        pending_username = session_login_manager.pending_username()
        return {
            "configured": config.session_path.is_file(),
            "username": str(values.get("instagram_username", "")),
            "last_validated_at": values.get("session_last_validated_at"),
            "last_error": values.get("session_last_error"),
            "login_pending": pending_username is not None,
            "pending_username": pending_username,
        }

    def record_created_session(username: str) -> None:
        database.set_settings(
            {
                "instagram_username": username,
                "session_last_validated_at": utc_now(),
                "session_last_error": None,
            }
        )

    def store_and_validate_session(username: str, content: bytes) -> str:
        username = username.strip().lstrip("@")
        if not username:
            raise InstagramSessionError("Instagram username is required")
        if not content:
            raise InstagramSessionError("Session file is empty")
        if len(content) > MAX_SESSION_BYTES:
            raise InstagramSessionError("Session file is larger than 2 MiB")
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=config.data_dir, prefix=".instagram-session-upload-", delete=False
        ) as handle:
            handle.write(content)
            temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        try:
            validated_username = validate_session(username, temporary, config.media_dir)
            os.replace(temporary, config.session_path)
            os.chmod(config.session_path, 0o600)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        session_login_manager.cancel()
        record_created_session(validated_username)
        return validated_username

    def validate_existing_session() -> str:
        username = str(database.get_setting("instagram_username", "")).strip()
        if not username or not config.session_path.is_file():
            raise InstagramSessionError("No Instagram session has been configured")
        try:
            validated_username = validate_session(username, config.session_path, config.media_dir)
        except Exception as exc:
            database.set_settings({"session_last_error": str(exc)[:4000]})
            raise
        database.set_settings(
            {
                "instagram_username": validated_username,
                "session_last_validated_at": utc_now(),
                "session_last_error": None,
            }
        )
        return validated_username

    def remove_session() -> None:
        session_login_manager.cancel()
        config.session_path.unlink(missing_ok=True)
        database.set_settings(
            {
                "instagram_username": "",
                "session_last_validated_at": None,
                "session_last_error": None,
            }
        )

    @app.get("/", include_in_schema=False)
    def index(request: Request) -> RedirectResponse:
        if not database.is_setup():
            target = request.url_for("setup")
        elif not request.session.get("admin_authenticated"):
            target = request.url_for("login")
        else:
            target = request.url_for("timeline")
        return RedirectResponse(str(target), status_code=303)

    @app.get("/setup", response_class=HTMLResponse, include_in_schema=False, name="setup")
    def setup(request: Request) -> Response:
        if database.is_setup():
            return RedirectResponse(str(request.url_for("timeline")), status_code=303)
        return render(request, "setup.html")

    @app.post("/setup", include_in_schema=False, name="setup_submit")
    def setup_submit(
        request: Request,
        admin_username: str = Form(...),
        password: str = Form(...),
        password_confirm: str = Form(...),
        csrf: str = Form(...),
    ) -> Response:
        verify_csrf(request, csrf)
        if database.is_setup():
            return RedirectResponse(str(request.url_for("login")), status_code=303)
        admin_username = admin_username.strip()
        if not admin_username or len(admin_username) > 64:
            return render(request, "setup.html", error="Administrator name must be 1–64 characters")
        if password != password_confirm:
            return render(request, "setup.html", error="Passwords do not match")
        try:
            password_hash = hash_password(password)
        except ValueError as exc:
            return render(request, "setup.html", error=str(exc))
        database.configure_admin(admin_username, password_hash, new_api_token())
        request.session.clear()
        request.session["admin_authenticated"] = True
        request.session["admin_username"] = admin_username
        flash(request, "Administrator account created. Connect your Instagram account next.", "success")
        return RedirectResponse(str(request.url_for("settings_page")), status_code=303)

    @app.get("/login", response_class=HTMLResponse, include_in_schema=False, name="login")
    def login(request: Request) -> Response:
        if not database.is_setup():
            return RedirectResponse(str(request.url_for("setup")), status_code=303)
        if request.session.get("admin_authenticated"):
            return RedirectResponse(str(request.url_for("timeline")), status_code=303)
        return render(request, "login.html")

    @app.post("/login", include_in_schema=False, name="login_submit")
    def login_submit(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        csrf: str = Form(...),
    ) -> Response:
        verify_csrf(request, csrf)
        expected_user = str(database.get_setting("admin_username", ""))
        password_hash = str(database.get_setting("admin_password_hash", ""))
        valid_user = hmac.compare_digest(username.strip(), expected_user)
        valid_password = verify_password(password, password_hash)
        if not (valid_user and valid_password):
            return render(request, "login.html", error="Invalid administrator credentials")
        request.session.clear()
        request.session["admin_authenticated"] = True
        request.session["admin_username"] = expected_user
        return RedirectResponse(str(request.url_for("timeline")), status_code=303)

    @app.post("/logout", include_in_schema=False, name="logout")
    def logout(request: Request, csrf: str = Form(...)) -> RedirectResponse:
        verify_csrf(request, csrf)
        request.session.clear()
        return RedirectResponse(str(request.url_for("login")), status_code=303)

    @app.get("/timeline", response_class=HTMLResponse, include_in_schema=False, name="timeline")
    def timeline(
        request: Request,
        _: bool = Depends(require_web_admin),
        q: str = Query(default="", max_length=200),
        author: str = Query(default="", max_length=100),
        media_type: str = Query(default="", pattern="^(|image|video|carousel)$"),
        date_from: str = Query(default="", pattern=r"^(|\d{4}-\d{2}-\d{2})$"),
        date_to: str = Query(default="", pattern=r"^(|\d{4}-\d{2}-\d{2})$"),
        page: int = Query(default=1, ge=1),
    ) -> HTMLResponse:
        limit = 24
        filters = {
            "q": q.strip(),
            "author": author.strip(),
            "media_type": media_type,
            "date_from": date_from,
            "date_to": date_to,
        }
        items, total = database.list_items(
            query=filters["q"],
            author=filters["author"],
            media_type=filters["media_type"],
            date_from=filters["date_from"],
            date_to=filters["date_to"],
            limit=limit,
            offset=(page - 1) * limit,
        )
        base_filters = {key: value for key, value in filters.items() if value}
        previous_url = None
        next_url = None
        if page > 1:
            previous_url = f"{request.url_for('timeline')}?{urlencode({**base_filters, 'page': page - 1})}"
        if page * limit < total:
            next_url = f"{request.url_for('timeline')}?{urlencode({**base_filters, 'page': page + 1})}"
        return render(
            request,
            "timeline.html",
            items=items,
            total=total,
            authors=database.list_authors(),
            filters=filters,
            page=page,
            previous_url=previous_url,
            next_url=next_url,
        )

    @app.get("/items/{item_id}", response_class=HTMLResponse, include_in_schema=False, name="item_page")
    def item_page(
        request: Request, item_id: int, _: bool = Depends(require_web_admin)
    ) -> HTMLResponse:
        item = database.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Archived item not found")
        return render(request, "item.html", item=item)

    @app.get("/activity", response_class=HTMLResponse, include_in_schema=False, name="activity_page")
    def activity_page(request: Request, _: bool = Depends(require_web_admin)) -> HTMLResponse:
        runs = [database.get_sync_run(run["id"]) for run in database.list_sync_runs(limit=30)]
        return render(request, "activity.html", runs=[run for run in runs if run])

    @app.post("/sync", include_in_schema=False, name="manual_sync")
    def manual_sync(
        request: Request,
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        started, run = sync_manager.start("web")
        if started:
            flash(request, f"Synchronization #{run.get('id')} started.", "success")
        else:
            flash(request, "A synchronization is already running.", "warning")
        return RedirectResponse(str(request.url_for("activity_page")), status_code=303)

    @app.post("/sync/test", include_in_schema=False, name="test_sync_web")
    def test_sync_web(
        request: Request,
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        started, run = sync_manager.start("test", max_downloads=3)
        if started:
            flash(
                request,
                f"Test synchronization #{run.get('id')} started; it will download at most 3 items.",
                "success",
            )
        else:
            flash(request, "A synchronization is already running.", "warning")
        return RedirectResponse(str(request.url_for("activity_page")), status_code=303)

    @app.post("/sync/stop", include_in_schema=False, name="stop_sync_web")
    def stop_sync_web(
        request: Request,
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        stop_requested, _run = sync_manager.stop()
        if stop_requested:
            flash(
                request,
                "Stop requested. The current item will finish before the active job stops.",
                "warning",
            )
        else:
            flash(request, "No synchronization or import is currently running.", "warning")
        return RedirectResponse(str(request.url_for("activity_page")), status_code=303)

    @app.post("/settings/import", include_in_schema=False, name="legacy_import_web")
    def legacy_import_web(
        request: Request,
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        try:
            started, run = sync_manager.start_import()
            if started:
                flash(request, f"Legacy import #{run.get('id')} started.", "success")
            else:
                flash(request, "Another synchronization or import is already running.", "warning")
        except ValueError as exc:
            flash(request, str(exc), "error")
        return RedirectResponse(str(request.url_for("activity_page")), status_code=303)

    @app.post(
        "/settings/authors/repair",
        include_in_schema=False,
        name="repair_authors_web",
    )
    def repair_authors_web(
        request: Request,
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        started, run = sync_manager.start_author_repair()
        if started:
            flash(request, f"Author repair #{run.get('id')} started.", "success")
        else:
            flash(request, "Another synchronization or import is already running.", "warning")
        return RedirectResponse(str(request.url_for("activity_page")), status_code=303)

    @app.get("/settings", response_class=HTMLResponse, include_in_schema=False, name="settings_page")
    def settings_page(request: Request, _: bool = Depends(require_web_admin)) -> HTMLResponse:
        return render(request, "settings.html", settings=settings_payload(request))

    @app.post("/settings", include_in_schema=False, name="settings_update_web")
    def settings_update_web(
        request: Request,
        sync_interval_minutes: int = Form(...),
        stop_after_known: int = Form(...),
        sync_enabled: str | None = Form(default=None),
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        if not 15 <= sync_interval_minutes <= 10080:
            flash(request, "Schedule must be between 15 and 10,080 minutes.", "error")
        elif not 1 <= stop_after_known <= 50:
            flash(request, "Known-item stop count must be between 1 and 50.", "error")
        else:
            database.set_settings(
                {
                    "sync_enabled": sync_enabled == "on",
                    "sync_interval_minutes": sync_interval_minutes,
                    "stop_after_known": stop_after_known,
                }
            )
            scheduler.refresh()
            flash(request, "Settings saved.", "success")
        return RedirectResponse(str(request.url_for("settings_page")), status_code=303)

    @app.post("/settings/session/login", include_in_schema=False, name="session_login_web")
    async def session_login_web(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        try:
            result = await run_in_threadpool(session_login_manager.start, username, password)
            if result["two_factor_required"]:
                flash(
                    request,
                    f"Instagram requires a verification code for @{result['username']}.",
                    "warning",
                )
            else:
                record_created_session(str(result["username"]))
                flash(
                    request,
                    f"Instagram session for @{result['username']} was created and saved.",
                    "success",
                )
        except Exception as exc:
            database.set_settings({"session_last_error": str(exc)[:4000]})
            flash(request, str(exc), "error")
        return RedirectResponse(str(request.url_for("settings_page")), status_code=303)

    @app.post(
        "/settings/session/two-factor",
        include_in_schema=False,
        name="session_two_factor_web",
    )
    async def session_two_factor_web(
        request: Request,
        code: str = Form(...),
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        try:
            username = await run_in_threadpool(
                session_login_manager.complete_two_factor, code
            )
            record_created_session(username)
            flash(
                request,
                f"Instagram session for @{username} was created and saved.",
                "success",
            )
        except Exception as exc:
            database.set_settings({"session_last_error": str(exc)[:4000]})
            flash(request, str(exc), "error")
        return RedirectResponse(str(request.url_for("settings_page")), status_code=303)

    @app.post("/settings/session", include_in_schema=False, name="session_upload_web")
    async def session_upload_web(
        request: Request,
        username: str = Form(...),
        session_file: UploadFile = File(...),
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        content = await session_file.read(MAX_SESSION_BYTES + 1)
        try:
            validated = await run_in_threadpool(store_and_validate_session, username, content)
            flash(request, f"Instagram session for @{validated} is valid and saved.", "success")
        except Exception as exc:
            database.set_settings({"session_last_error": str(exc)[:4000]})
            flash(request, str(exc), "error")
        return RedirectResponse(str(request.url_for("settings_page")), status_code=303)

    @app.post("/settings/session/validate", include_in_schema=False, name="session_validate_web")
    def session_validate_web(
        request: Request,
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        try:
            username = validate_existing_session()
            flash(request, f"Instagram session for @{username} is valid.", "success")
        except Exception as exc:
            flash(request, str(exc), "error")
        return RedirectResponse(str(request.url_for("settings_page")), status_code=303)

    @app.post("/settings/session/remove", include_in_schema=False, name="session_remove_web")
    def session_remove_web(
        request: Request,
        csrf: str = Form(...),
        _: bool = Depends(require_web_admin),
    ) -> RedirectResponse:
        verify_csrf(request, csrf)
        remove_session()
        flash(request, "Instagram session removed. Archived items were kept.", "success")
        return RedirectResponse(str(request.url_for("settings_page")), status_code=303)

    @app.get("/diagnostics", response_class=HTMLResponse, include_in_schema=False, name="diagnostics_page")
    def diagnostics_page(request: Request, _: bool = Depends(require_web_admin)) -> HTMLResponse:
        media_files = [path for path in config.media_dir.rglob("*") if path.is_file()]
        disk = shutil.disk_usage(config.data_dir)
        diagnostics = {
            "version": __version__,
            "database_size": config.database_path.stat().st_size if config.database_path.exists() else 0,
            "media_size": sum(path.stat().st_size for path in media_files),
            "media_files": len(media_files),
            "free_space": disk.free,
            "item_count": database.count_items(),
            "unknown_author_count": database.count_unknown_authors(),
            "legacy_import_path": str(config.import_dir),
            "legacy_import_available": config.import_dir.is_dir(),
            "session": session_payload(request),
            "next_scheduled_sync": scheduler.next_run_at(),
            "recent_errors": database.recent_errors(limit=20),
        }
        return render(request, "diagnostics.html", diagnostics=diagnostics)

    @app.get("/media/{path:path}", include_in_schema=False, name="media_file")
    def media_file(
        path: str,
        _: bool = Depends(require_api_auth),
    ) -> FileResponse:
        root = config.media_dir.resolve()
        requested = (root / path).resolve()
        if not requested.is_relative_to(root) or not requested.is_file():
            raise HTTPException(status_code=404, detail="Media file not found")
        return FileResponse(requested, headers={"Cache-Control": "private, max-age=86400"})

    @app.get("/api/docs", response_class=HTMLResponse, include_in_schema=False, name="api_docs")
    def api_docs(request: Request, _: bool = Depends(require_web_admin)) -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=str(request.url_for("openapi_json")),
            title="GramShelf API documentation",
        )

    @app.get("/api/openapi.json", include_in_schema=False, name="openapi_json")
    def openapi_json(_: bool = Depends(require_api_auth)) -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get(
        "/api/v1/health",
        response_model=HealthResponse,
        tags=["Status"],
        summary="Health check",
    )
    def api_health() -> dict[str, Any]:
        database.count_items()
        return {"status": "ok", "version": __version__, "setup_complete": database.is_setup()}

    @app.get(
        "/api/v1/status",
        response_model=AppStatusOut,
        tags=["Status"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_status() -> dict[str, Any]:
        return {
            "version": __version__,
            "setup_complete": database.is_setup(),
            "item_count": database.count_items(),
            "instagram_session_configured": config.session_path.is_file(),
            "sync": sync_manager.status(),
            "next_scheduled_sync": scheduler.next_run_at(),
        }

    @app.get(
        "/api/v1/items",
        response_model=ItemListOut,
        tags=["Items"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_items(
        request: Request,
        q: str = Query(default="", max_length=200),
        author: str = Query(default="", max_length=100),
        media_type: str = Query(default="", pattern="^(|image|video|carousel)$"),
        date_from: str = Query(default="", pattern=r"^(|\d{4}-\d{2}-\d{2})$"),
        date_to: str = Query(default="", pattern=r"^(|\d{4}-\d{2}-\d{2})$"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        items, total = database.list_items(
            query=q.strip(),
            author=author.strip(),
            media_type=media_type,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [item_summary(request, item) for item in items],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    @app.get(
        "/api/v1/items/{item_id}",
        response_model=ItemOut,
        tags=["Items"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_item(request: Request, item_id: int) -> dict[str, Any]:
        item = database.get_item(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Archived item not found")
        return item_detail(request, item)

    @app.get(
        "/api/v1/instagram/session",
        response_model=SessionStatusOut,
        tags=["Instagram session"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_session_status(request: Request) -> dict[str, Any]:
        return session_payload(request)

    @app.post(
        "/api/v1/instagram/session/login",
        response_model=SessionStatusOut,
        tags=["Instagram session"],
        dependencies=[Depends(require_api_auth)],
    )
    async def api_session_login(
        request: Request, credentials: SessionLoginIn
    ) -> dict[str, Any]:
        try:
            result = await run_in_threadpool(
                session_login_manager.start,
                credentials.username,
                credentials.password.get_secret_value(),
            )
            if not result["two_factor_required"]:
                record_created_session(str(result["username"]))
        except Exception as exc:
            database.set_settings({"session_last_error": str(exc)[:4000]})
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return session_payload(request)

    @app.post(
        "/api/v1/instagram/session/two-factor",
        response_model=SessionStatusOut,
        tags=["Instagram session"],
        dependencies=[Depends(require_api_auth)],
    )
    async def api_session_two_factor(
        request: Request, verification: SessionTwoFactorIn
    ) -> dict[str, Any]:
        try:
            username = await run_in_threadpool(
                session_login_manager.complete_two_factor,
                verification.code.get_secret_value(),
            )
            record_created_session(username)
        except Exception as exc:
            database.set_settings({"session_last_error": str(exc)[:4000]})
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return session_payload(request)

    @app.post(
        "/api/v1/instagram/session",
        response_model=SessionStatusOut,
        tags=["Instagram session"],
        dependencies=[Depends(require_api_auth)],
    )
    async def api_session_upload(
        request: Request,
        username: str = Form(...),
        session_file: UploadFile = File(...),
    ) -> dict[str, Any]:
        content = await session_file.read(MAX_SESSION_BYTES + 1)
        try:
            await run_in_threadpool(store_and_validate_session, username, content)
        except Exception as exc:
            database.set_settings({"session_last_error": str(exc)[:4000]})
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return session_payload(request)

    @app.post(
        "/api/v1/instagram/session/validate",
        response_model=SessionStatusOut,
        tags=["Instagram session"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_session_validate(request: Request) -> dict[str, Any]:
        try:
            validate_existing_session()
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return session_payload(request)

    @app.delete(
        "/api/v1/instagram/session",
        response_model=MessageOut,
        tags=["Instagram session"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_session_remove() -> dict[str, str]:
        remove_session()
        return {"message": "Instagram session removed; archived items were kept"}

    @app.post(
        "/api/v1/sync",
        response_model=SyncStartOut,
        status_code=202,
        tags=["Synchronization"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_sync_start() -> dict[str, Any]:
        started, run = sync_manager.start("api")
        return {"started": started, "run": run}

    @app.post(
        "/api/v1/sync/test",
        response_model=SyncStartOut,
        status_code=202,
        tags=["Synchronization"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_test_sync_start() -> dict[str, Any]:
        started, run = sync_manager.start("test", max_downloads=3)
        return {"started": started, "run": run}

    @app.post(
        "/api/v1/sync/stop",
        response_model=SyncStopOut,
        tags=["Synchronization"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_sync_stop() -> dict[str, Any]:
        stop_requested, run = sync_manager.stop()
        return {"stop_requested": stop_requested, "run": run}

    @app.post(
        "/api/v1/import/legacy",
        response_model=SyncStartOut,
        status_code=202,
        tags=["Import"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_legacy_import_start() -> dict[str, Any]:
        try:
            started, run = sync_manager.start_import()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"started": started, "run": run}

    @app.post(
        "/api/v1/authors/repair",
        response_model=SyncStartOut,
        status_code=202,
        tags=["Items"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_repair_authors_start() -> dict[str, Any]:
        started, run = sync_manager.start_author_repair()
        return {"started": started, "run": run}

    @app.get(
        "/api/v1/sync/status",
        response_model=SyncStatusOut,
        tags=["Synchronization"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_sync_status() -> dict[str, Any]:
        current = sync_manager.status()
        return {
            "running": bool(current.get("running")),
            "stopping": bool(current.get("stopping")),
            "status": str(current.get("status", "unknown")),
            "run": current if current.get("id") else None,
        }

    @app.get(
        "/api/v1/sync/history",
        response_model=list[SyncRunOut],
        tags=["Synchronization"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_sync_history(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        return database.list_sync_runs(limit=limit, offset=offset)

    @app.get(
        "/api/v1/sync/history/{run_id}",
        response_model=SyncRunOut,
        tags=["Synchronization"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_sync_run(run_id: int) -> dict[str, Any]:
        run = database.get_sync_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Synchronization run not found")
        return run

    @app.get(
        "/api/v1/settings",
        response_model=SettingsOut,
        tags=["Settings"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_settings_get(request: Request) -> dict[str, Any]:
        return settings_payload(request)

    @app.patch(
        "/api/v1/settings",
        response_model=SettingsOut,
        tags=["Settings"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_settings_update(request: Request, update: SettingsUpdate) -> dict[str, Any]:
        values = update.model_dump(exclude_none=True)
        if values:
            database.set_settings(values)
            scheduler.refresh()
        return settings_payload(request)

    @app.get(
        "/api/v1/diagnostics",
        tags=["Status"],
        dependencies=[Depends(require_api_auth)],
    )
    def api_diagnostics(request: Request) -> dict[str, Any]:
        disk = shutil.disk_usage(config.data_dir)
        return {
            "version": __version__,
            "database_bytes": config.database_path.stat().st_size if config.database_path.exists() else 0,
            "media_files": sum(1 for path in config.media_dir.rglob("*") if path.is_file()),
            "free_bytes": disk.free,
            "item_count": database.count_items(),
            "unknown_author_count": database.count_unknown_authors(),
            "legacy_import_path": str(config.import_dir),
            "legacy_import_available": config.import_dir.is_dir(),
            "session": session_payload(request),
            "next_scheduled_sync": scheduler.next_run_at(),
            "recent_errors": database.recent_errors(limit=20),
        }

    return app
