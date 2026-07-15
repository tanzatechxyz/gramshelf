from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class AppConfig:
    data_dir: Path
    media_dir: Path
    import_dir: Path = Path("/import")
    host: str = "0.0.0.0"
    port: int = 8080
    root_path: str = ""
    secure_cookies: bool = False
    forwarded_allow_ips: str = "127.0.0.1"

    @classmethod
    def from_env(cls) -> "AppConfig":
        root_path = os.getenv("GRAMSHELF_ROOT_PATH", "").strip()
        if root_path and not root_path.startswith("/"):
            root_path = f"/{root_path}"
        return cls(
            data_dir=Path(os.getenv("GRAMSHELF_DATA_DIR", "/data")),
            media_dir=Path(os.getenv("GRAMSHELF_MEDIA_DIR", "/media")),
            import_dir=Path(os.getenv("GRAMSHELF_IMPORT_DIR", "/import")),
            host=os.getenv("GRAMSHELF_HOST", "0.0.0.0"),
            port=int(os.getenv("GRAMSHELF_PORT", "8080")),
            root_path=root_path.rstrip("/"),
            secure_cookies=_env_bool("GRAMSHELF_SECURE_COOKIES"),
            forwarded_allow_ips=os.getenv("GRAMSHELF_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "gramshelf.sqlite3"

    @property
    def session_path(self) -> Path:
        return self.data_dir / "instagram-session"

    @property
    def secret_path(self) -> Path:
        return self.data_dir / "secret.key"

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)

    def load_or_create_secret(self) -> str:
        self.prepare()
        if self.secret_path.exists():
            return self.secret_path.read_text(encoding="utf-8").strip()
        secret = secrets.token_urlsafe(48)
        fd = os.open(self.secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secret)
        return secret
