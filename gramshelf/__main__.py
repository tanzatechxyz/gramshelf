from __future__ import annotations

import uvicorn

from .config import AppConfig


def main() -> None:
    config = AppConfig.from_env()
    uvicorn.run(
        "gramshelf.app:create_app",
        factory=True,
        host=config.host,
        port=config.port,
        proxy_headers=True,
        forwarded_allow_ips=config.forwarded_allow_ips,
        workers=1,
    )


if __name__ == "__main__":
    main()
