# HTTP API

GramShelf exposes OpenAPI at `/api/openapi.json` and Swagger UI at `/api/docs`. The documentation routes require an administrator login or token as applicable.

Except for health, authenticate with the token from Settings:

```http
Authorization: Bearer gs_REPLACE_ME
```

The administrator browser session is also accepted. JSON errors use FastAPI's standard `{"detail": "..."}` shape.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Public liveness/readiness check and setup state |
| `GET` | `/api/v1/status` | Version, archive count, session state, current sync, and next scheduled run |
| `GET` | `/api/v1/items` | Chronological item list with search, filters, limit, and offset |
| `GET` | `/api/v1/items/{id}` | One archived item and all downloaded media |
| `POST` | `/api/v1/authors/repair` | Queue a Saved-feed scan that repairs archived `unknown` authors without downloading media |
| `GET` | `/api/v1/instagram/session` | Saved-session and pending two-factor state |
| `POST` | `/api/v1/instagram/session` | Upload and validate a session as multipart fields `username` and `session_file` |
| `POST` | `/api/v1/instagram/session/login` | Create a session from JSON fields `username` and `password`; the password is not stored |
| `POST` | `/api/v1/instagram/session/two-factor` | Complete a pending login with JSON field `code` |
| `POST` | `/api/v1/instagram/session/validate` | Revalidate the stored session |
| `DELETE` | `/api/v1/instagram/session` | Remove the stored session without deleting the archive |
| `POST` | `/api/v1/sync` | Queue an on-demand synchronization; returns HTTP 202 |
| `POST` | `/api/v1/sync/test` | Queue a test synchronization that downloads at most three new items |
| `POST` | `/api/v1/sync/stop` | Request that the active synchronization stop after its current item |
| `POST` | `/api/v1/import/legacy` | Queue a deduplicating import from the configured read-only legacy folder |
| `GET` | `/api/v1/sync/status` | Current or most recent synchronization state |
| `GET` | `/api/v1/sync/history` | Paginated synchronization history |
| `GET` | `/api/v1/sync/history/{id}` | One run with its errors |
| `GET` | `/api/v1/settings` | Read synchronization settings and API token |
| `PATCH` | `/api/v1/settings` | Update synchronization settings and the archive-scan cutoff state |
| `GET` | `/api/v1/diagnostics` | Storage, session, schedule, and recent error diagnostics |

## Item filters

`GET /api/v1/items` accepts:

- `q`: case-insensitive caption, author, or shortcode search
- `author`: exact author username, case-insensitive
- `media_type`: `image`, `video`, or `carousel`
- `date_from` and `date_to`: inclusive publication dates in `YYYY-MM-DD`
- `limit`: 1–200, default 50
- `offset`: zero-based offset

Items are always ordered by `published_at` descending. Media URLs in API responses remain authenticated and accept the same Bearer token or browser session.

## Settings example

```bash
curl -X PATCH http://localhost:8080/api/v1/settings \
  -H "Authorization: Bearer gs_REPLACE_ME" \
  -H "Content-Type: application/json" \
  -d '{"sync_enabled":true,"sync_interval_minutes":720,"stop_after_known":3,"archive_scan_complete":true}'
```

Intervals must be between 15 and 10,080 minutes. The known-item setting is between 1 and 50.
Set `archive_scan_complete` to `false` to force the next synchronization to traverse the full Saved feed, or to `true` to enable the consecutive-known-item cutoff immediately.

## Create a session through the API

Send credentials only over HTTPS or a trusted private network. GramShelf passes the password directly to Instaloader and does not write it to the database, logs, or session file.

```bash
curl -X POST http://localhost:8080/api/v1/instagram/session/login \
  -H "Authorization: Bearer gs_REPLACE_ME" \
  -H "Content-Type: application/json" \
  -d '{"username":"YOUR_USERNAME","password":"YOUR_PASSWORD"}'
```

If the response has `"login_pending": true`, complete the in-memory login within 10 minutes:

```bash
curl -X POST http://localhost:8080/api/v1/instagram/session/two-factor \
  -H "Authorization: Bearer gs_REPLACE_ME" \
  -H "Content-Type: application/json" \
  -d '{"code":"123456"}'
```

The pending two-factor login is intentionally lost when the container restarts. Existing session-file upload remains available when Instagram rejects a direct login.

## Stop a synchronization

```bash
curl -X POST http://localhost:8080/api/v1/sync/stop \
  -H "Authorization: Bearer gs_REPLACE_ME"
```

Stopping is cooperative: an in-progress Instaloader media request is allowed to finish so files are not deliberately interrupted mid-write. The response field `stop_requested` indicates whether the active job accepted the request. Status reports `stopping: true` until the run finishes with status `cancelled`.

The same stop endpoint also stops a legacy import or author-repair run after its current item. These maintenance jobs appear in the normal status and history endpoints with triggers `legacy-import` and `author-repair`.

## Import and author-repair examples

Mount the old Instaloader archive at the configured `GRAMSHELF_IMPORT_DIR` (default `/import`) before starting the import:

```bash
curl -X POST http://localhost:8080/api/v1/import/legacy \
  -H "Authorization: Bearer gs_REPLACE_ME"
```

The source is read-only. GramShelf copies matching media, converts JSON/TXT metadata into its database, and deduplicates by shortcode. To repair existing `unknown` authors using the current Saved feed:

```bash
curl -X POST http://localhost:8080/api/v1/authors/repair \
  -H "Authorization: Bearer gs_REPLACE_ME"
```
