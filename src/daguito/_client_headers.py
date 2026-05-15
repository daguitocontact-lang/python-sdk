"""SDK origin tracking headers.

Every HTTP request and WebSocket upgrade from this SDK carries
X-Daguito-Client-* headers so the server can attribute traffic by
SDK language + version. WS connections also send the same values as
query params for resilience to header-stripping proxies.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def _read_version() -> str:
    try:
        from importlib.metadata import version

        return version("daguito-sdk")
    except Exception:
        return "0.4.0"


SDK_LANG = "python"
SDK_VERSION = _read_version()


def client_headers() -> dict[str, str]:
    return {
        "X-Daguito-Client": f"daguito-sdk-python/{SDK_VERSION}",
        "X-Daguito-Client-Lang": SDK_LANG,
        "X-Daguito-Client-Version": SDK_VERSION,
    }


def client_query_params() -> dict[str, str]:
    return {
        "x_daguito_client_lang": SDK_LANG,
        "x_daguito_client_version": SDK_VERSION,
    }


def append_client_query_params(url: str) -> str:
    parsed = urlparse(url)
    existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
    existing.update(client_query_params())
    new_query = urlencode(existing)
    return urlunparse(parsed._replace(query=new_query))
