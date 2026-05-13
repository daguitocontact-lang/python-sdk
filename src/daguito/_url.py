"""URL helpers — mirror sdks/js/src/url.ts behavior."""

from __future__ import annotations

import secrets
from urllib.parse import urlencode, urlparse, urlunparse


def join_http(base: str, path: str) -> str:
    """Join an HTTP base URL with a path, normalizing slashes."""
    base = base.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def to_ws_url(api_url: str, path: str, query: dict[str, str] | None = None) -> str:
    """Convert http(s):// to ws(s):// and append path + optional query."""
    parsed = urlparse(api_url)
    scheme = {"http": "ws", "https": "wss"}.get(parsed.scheme, parsed.scheme)
    base_path = parsed.path.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    full_path = f"{base_path}{path}"
    qs = urlencode(query) if query else ""
    return urlunparse((scheme, parsed.netloc, full_path, "", qs, ""))


def random_session_id(prefix: str = "py") -> str:
    """Cryptographically-strong, human-friendly session id."""
    return f"{prefix}_{secrets.token_urlsafe(12)}"
