"""One-shot HTTP webhook — mirrors sdks/js/src/webhook-session.ts.

Use this for non-streaming flows where you just need the final output.
For streaming flows that emit tokens/progress, use `WebhookStreamSession`.

Async-first (httpx.AsyncClient). A sync wrapper is exposed as
`run_webhook_sync` for callers that don't yet have an event loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from ._client_headers import client_headers
from ._url import join_http


@dataclass
class WebhookRunInput:
    api_url: str
    """The raw token (NOT a URL). The path embeds it server-side."""
    token: str
    """Free-form input passed to the flow as `base_input`."""
    input: dict[str, Any] | None = None
    timeout_seconds: float | None = 90.0


@dataclass
class WebhookRunResult:
    ok: bool
    execution_id: str
    status: str
    output: Any


class WebhookError(Exception):
    """Raised when the webhook call fails (network, HTTP error, or server error)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


async def run_webhook(input: WebhookRunInput) -> WebhookRunResult:
    """Fire-and-wait POST to `/h/:token`. Returns the final `WebhookRunResult`."""
    url = join_http(input.api_url, f"/h/{quote(input.token, safe='')}")
    body = input.input or {}
    timeout = httpx.Timeout(input.timeout_seconds or 90.0)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json=body,
                headers={"Content-Type": "application/json", **client_headers()},
            )
    except httpx.HTTPError as err:
        raise WebhookError(str(err) or "network error") from err

    if response.status_code >= 400:
        text = response.text
        raise WebhookError(
            f"HTTP {response.status_code}: {text or response.reason_phrase}",
            response.status_code,
        )

    try:
        parsed = response.json()
    except ValueError as err:
        raise WebhookError(f"invalid JSON response: {err}", response.status_code) from err

    if isinstance(parsed, dict) and parsed.get("error"):
        raise WebhookError(str(parsed["error"]), response.status_code)

    return WebhookRunResult(
        ok=bool(parsed.get("ok", False)) if isinstance(parsed, dict) else False,
        execution_id=str(parsed.get("execution_id", ""))
        if isinstance(parsed, dict)
        else "",
        status=str(parsed.get("status", "unknown"))
        if isinstance(parsed, dict)
        else "unknown",
        output=parsed.get("output") if isinstance(parsed, dict) else None,
    )


def run_webhook_sync(input: WebhookRunInput) -> WebhookRunResult:
    """Synchronous wrapper. Use only when you don't have a running event loop."""
    return asyncio.run(run_webhook(input))
