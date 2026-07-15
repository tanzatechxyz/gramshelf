# GramShelf

GramShelf is a small, single-user web application that archives your Instagram Saved posts. It uses [Instaloader](https://instaloader.github.io/) for session authentication, Saved-post discovery, metadata retrieval, and every media download.

It is designed for a single Docker container on a home server such as TrueNAS SCALE: one FastAPI process, one SQLite database, server-rendered pages, and two persistent mounts.

## What it does

- Downloads available images, videos, and carousel media from your Saved feed.
- Deduplicates posts by Instagram shortcode.
- Stores the author, caption, original URL, publication time, download time, and media type.
- Shows a responsive publication-date timeline with search, author/type/date filters, and item details.
- Runs on a configurable interval or on demand from the UI and API.
- Provides a three-item test synchronization before running a full import.
- Lets the administrator stop a running synchronization after its current item finishes.
- Records synchronization progress, history, and per-item errors.
- Provides an administrator login, setup flow, session management, diagnostics, and an OpenAPI-documented HTTP API.

GramShelf intentionally has one administrator, one Instagram account, SQLite, and one application process. It does not mirror Instagram collections, delete archived posts when you unsave them, or attempt to bypass Instagram restrictions.

## Quick start with Docker Compose

1. Create writable persistent folders. The image runs as UID/GID `568` by default (the common TrueNAS Apps user):

   ```bash
   mkdir -p data media
   sudo chown -R 568:568 data media
   ```

2. Copy `.env.example` to `.env` if you want to change the port, then start the app:

   ```bash
   docker compose up -d --build
   ```

3. Open `http://YOUR_SERVER:8080`, create the administrator, and create or import an Instaloader session from Settings.

The container mounts application state at `/data` and downloaded media at `/media`. Back up both folders together.

## Connect Instagram

On Settings, enter your Instagram username and password to have GramShelf create the Instaloader session. The password is used only for that login request and is never stored. If Instagram requests two-factor authentication, enter the verification code in the follow-up form within 10 minutes.

Only submit Instagram credentials over HTTPS or a trusted private network. Direct Instagram logins can be fragile, so session-file import remains available as the reliable fallback.

To create the session on a trusted computer instead:

```bash
python -m pip install "instaloader>=4.15.2,<5"
instaloader --login YOUR_USERNAME
```

Complete any Instagram prompt, then upload Instaloader's generated `session-YOUR_USERNAME` file on GramShelf's Settings page. GramShelf validates the uploaded session before replacing the currently stored session.

Session files contain authentication cookies. Treat them as secrets and only upload a file you generated yourself. Instagram is an unofficial and changeable integration: sessions can expire, Saved-feed access can break when Instagram changes its private interfaces, and aggressive schedules can cause rate limits. The default 12-hour interval is deliberately conservative.

If Instagram refuses an optional full-metadata lookup after media has downloaded, GramShelf now archives the item from the metadata already present in the Saved-feed response. Missing fields use safe fallbacks instead of leaving downloaded media invisible.

## Container configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `GRAMSHELF_DATA_DIR` | `/data` | SQLite database, secret key, and Instagram session |
| `GRAMSHELF_MEDIA_DIR` | `/media` | Downloaded images and videos |
| `GRAMSHELF_HOST` | `0.0.0.0` | Listening address |
| `GRAMSHELF_PORT` | `8080` | Listening port inside the container |
| `GRAMSHELF_ROOT_PATH` | empty | Optional reverse-proxy path prefix, such as `/gramshelf` |
| `GRAMSHELF_SECURE_COOKIES` | `false` | Set `true` when access is exclusively HTTPS |
| `GRAMSHELF_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Trusted proxy IPs for forwarded headers |

Run exactly one application process. The scheduler and synchronization lock are in-process by design; multiple replicas are outside this project's scope.

Detailed TrueNAS steps are in [docs/TRUENAS.md](docs/TRUENAS.md).

## API

After logging in, open `/api/docs` for interactive documentation. Scripts can use the Bearer token shown on Settings:

```bash
curl -H "Authorization: Bearer gs_REPLACE_ME" \
  http://localhost:8080/api/v1/items?media_type=video

curl -X POST -H "Authorization: Bearer gs_REPLACE_ME" \
  http://localhost:8080/api/v1/sync
```

`GET /api/v1/health` is intentionally public for container health checks. All other API and media routes require the administrator session or Bearer token. See [docs/API.md](docs/API.md) for the endpoint map.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[test]"
pytest
GRAMSHELF_DATA_DIR=./dev-data GRAMSHELF_MEDIA_DIR=./dev-media gramshelf
```

## Packaging

The included GitHub Actions workflow tests the project and publishes a multi-architecture container to GitHub Container Registry on pushes to `main` and version tags. Main-branch images use:

```text
ghcr.io/tanzatechxyz/gramshelf:latest
ghcr.io/tanzatechxyz/gramshelf:main
```

A tag such as `v0.3.0` also publishes `0.3.0` and `0.3` image tags.

## Security and privacy

- Passwords use the standard-library scrypt KDF with a unique salt.
- Browser forms use signed, HTTP-only sessions and CSRF tokens.
- Archived media is not publicly mounted; it is served through authenticated routes.
- The API token and Instagram session live only in `/data`.
- The container runs without root privileges and drops all Linux capabilities in the supplied Compose file.

Put GramShelf behind HTTPS before exposing it outside a trusted network. It is an archive tool, not a public gallery.

## License

MIT. GramShelf is not affiliated with or endorsed by Instagram or Meta.
