from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def post_node(post: Any) -> dict[str, Any]:
    try:
        node = getattr(post, "_node", {})
    except Exception:
        return {}
    return node if isinstance(node, dict) else {}


def shortcode(post: Any) -> str:
    node = post_node(post)
    value = node.get("shortcode") or node.get("code")
    if value:
        return str(value)
    try:
        return str(post.shortcode)
    except Exception:
        return ""


def published_at(post: Any, fallback: str) -> str:
    try:
        value = post.date_utc
    except Exception:
        node = post_node(post)
        timestamp = node.get("date", node.get("taken_at_timestamp"))
        try:
            value = datetime.fromtimestamp(float(timestamp), tz=UTC)
        except (TypeError, ValueError, OSError):
            return fallback
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat(timespec="seconds")


def media_type(post: Any) -> str:
    node = post_node(post)
    typename = str(node.get("__typename", ""))
    if not typename:
        try:
            typename = str(post.typename)
        except Exception:
            typename = ""
    if typename in {"GraphSidecar", "XDTGraphSidecar"}:
        return "carousel"
    if "is_video" in node:
        is_video = bool(node["is_video"])
    else:
        try:
            is_video = bool(post.is_video)
        except Exception:
            is_video = False
    if typename in {"GraphVideo", "XDTGraphVideo"} or is_video:
        return "video"
    return "image"


def cached_author(post: Any) -> str:
    node = post_node(post)
    for candidate in (node.get("owner"), node.get("user")):
        if isinstance(candidate, dict) and candidate.get("username"):
            return str(candidate["username"])
    if node.get("owner_username"):
        return str(node["owner_username"])
    return "unknown"


def owner_id(post: Any) -> int | None:
    node = post_node(post)
    for candidate in (node.get("owner"), node.get("user")):
        if isinstance(candidate, dict):
            value = candidate.get("id", candidate.get("pk"))
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    for key in ("owner_id", "user_id"):
        try:
            return int(node[key])
        except (KeyError, TypeError, ValueError):
            pass
    return None


def author(post: Any) -> str:
    value = cached_author(post)
    if value != "unknown":
        return value
    try:
        value = post.owner_username
        return str(value) if value else "unknown"
    except Exception:
        return "unknown"


def caption(post: Any) -> str:
    node = post_node(post)
    caption_node = node.get("edge_media_to_caption")
    edges = caption_node.get("edges", []) if isinstance(caption_node, dict) else []
    if edges and isinstance(edges[0], dict):
        edge_node = edges[0].get("node")
        if isinstance(edge_node, dict):
            return str(edge_node.get("text") or "")
    if "caption" in node:
        value = node.get("caption")
        if isinstance(value, dict):
            return str(value.get("text") or "")
        return str(value or "")
    try:
        return str(post.caption or "")
    except Exception:
        return ""


def is_unknown_author(value: Any) -> bool:
    return str(value or "").strip().lstrip("@").casefold() in {"", "unknown"}
