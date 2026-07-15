# Deploy on TrueNAS SCALE

GramShelf is suitable for the TrueNAS SCALE custom-app workflow that accepts a Docker image or Compose YAML. Labels in the TrueNAS UI vary by SCALE release, but the required values are the same.

## Prepare datasets

Create two datasets, for example:

- `/mnt/tank/apps/gramshelf/data`
- `/mnt/tank/apps/gramshelf/media`

Grant read/write/execute access on both datasets to UID and GID `568` (the non-root user built into the image). Keep the session/database dataset private; it contains the API token, cookie signing key, and Instagram session.

## Custom app values

Use these values when installing a custom image:

| Setting | Value |
| --- | --- |
| Image | `ghcr.io/tanzatechxyz/gramshelf:latest` |
| Container port | `8080` TCP |
| Host port | Any available port, commonly `30080` or `8080` |
| Restart policy | Unless stopped |
| Run as user/group | `568:568` |
| Host path 1 | `/mnt/tank/apps/gramshelf/data` → `/data`, read/write |
| Host path 2 | `/mnt/tank/apps/gramshelf/media` → `/media`, read/write |
| Health path | `/api/v1/health` |

No environment variables are required for a direct host/port deployment.

For YAML-based custom apps, adapt this minimal definition:

```yaml
services:
  gramshelf:
    image: ghcr.io/tanzatechxyz/gramshelf:latest
    user: "568:568"
    restart: unless-stopped
    ports:
      - "30080:8080"
    volumes:
      - /mnt/tank/apps/gramshelf/data:/data
      - /mnt/tank/apps/gramshelf/media:/media
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
```

After deployment, open `http://TRUENAS_IP:30080` and complete the first-run setup.

## Reverse proxy

If a reverse proxy terminates HTTPS, set `GRAMSHELF_SECURE_COOKIES=true`. Also set `GRAMSHELF_FORWARDED_ALLOW_IPS` to the proxy's container or host IP. If GramShelf is mounted below a path rather than a subdomain, set `GRAMSHELF_ROOT_PATH`, for example `/gramshelf`.

Do not expose the raw HTTP port to the internet. Use HTTPS and an access policy appropriate for private media.

## Backups and upgrades

Snapshot or back up both datasets together. SQLite uses WAL mode, so use a filesystem snapshot or stop the app before a file-level copy if you need a strictly consistent standalone backup.

To upgrade, pull the new image and redeploy the single container. Keep one replica; the in-process scheduler and synchronization lock intentionally do not support clustering.
