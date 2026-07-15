# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ARG APP_UID=568
ARG APP_GID=568

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GRAMSHELF_DATA_DIR=/data \
    GRAMSHELF_MEDIA_DIR=/media \
    GRAMSHELF_PORT=8080

RUN groupadd --gid "${APP_GID}" gramshelf \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --no-create-home --shell /usr/sbin/nologin gramshelf

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY gramshelf ./gramshelf

RUN python -m pip install --no-cache-dir . \
    && mkdir -p /data /media \
    && chown -R "${APP_UID}:${APP_GID}" /data /media

USER gramshelf

EXPOSE 8080
VOLUME ["/data", "/media"]

HEALTHCHECK --interval=30s --timeout=6s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=5)"

CMD ["gramshelf"]
