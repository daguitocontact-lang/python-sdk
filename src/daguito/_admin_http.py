"""Shared HTTP helpers for the admin client services.

Lives under `daguito._admin_http` so the public surface stays clean. The
admin services (`account_keys`, `public_keys`, `budgets`) all share the
same auth + error-mapping path — keeping it here avoids duplicating the
Bearer/4xx plumbing across three services.
"""

from __future__ import annotations

from typing import Any

import httpx


class DaguitoError(Exception):
    """Raised when an admin API call fails (network, HTTP error, or body error).

    `status` is the HTTP status code when the failure came from the server.
    Network/transport errors leave it `None`.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
) -> Any:
    """POST/PATCH/GET/DELETE helper that returns parsed JSON (or `None` on 204).

    Raises `DaguitoError` on transport failures, non-2xx responses, or
    invalid JSON. The body, when supplied, is sent as JSON.
    """
    try:
        if method == "GET":
            response = await client.get(url)
        elif method == "DELETE":
            response = await client.delete(url)
        elif method == "POST":
            response = await client.post(url, json=body or {})
        elif method == "PATCH":
            response = await client.patch(url, json=body or {})
        else:
            raise DaguitoError(f"unsupported method: {method}")
    except httpx.HTTPError as err:
        raise DaguitoError(str(err) or "network error") from err

    if response.status_code == 204:
        return None

    if response.status_code >= 400:
        message = _extract_error(response)
        raise DaguitoError(message, response.status_code)

    if not response.content:
        return None
    try:
        parsed = response.json()
    except ValueError as err:
        raise DaguitoError(
            f"invalid JSON response: {err}", response.status_code
        ) from err
    return parsed


def _extract_error(response: httpx.Response) -> str:
    text = response.text
    try:
        parsed = response.json()
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
            return parsed["error"]
    except ValueError:
        pass
    return text or response.reason_phrase or f"HTTP {response.status_code}"
