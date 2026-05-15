"""Upload helper for webhook integrators — one-shot, mirrors `run_webhook`.

Mints a presigned PUT URL via the Daguito webhook upload endpoint, PUTs
the bytes, and returns the resulting `media_key`. The caller feeds that
key to `media_key_message(...)` on a subsequent `session.send`.

The flow mirrors what OpenAI Files API and Anthropic Files API expose:
bytes never stream through the Daguito API — only the presign POST does.
The PUT goes straight to object storage. Cheaper, faster, scales linearly.

    from daguito import upload_file, UploadInput
    result = await upload_file(UploadInput(
        api_url="https://api.daguito.com",
        webhook_id="wh_xxx",
        token="sk_wh_yyy",
        kind="document",
        path="/tmp/contract.pdf",
    ))
    print(result.media_key)
"""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from typing import Literal

import httpx

from ._client_headers import client_headers
from ._url import join_http

# The message kinds that accept an attachment (mirrors `@daguito/core`
# `MESSAGE_KINDS`). text / voice_stream / rich never upload anything.
UploadKind = Literal["image", "audio", "document", "video"]


@dataclass
class UploadInput:
    """Input for `upload_file`. Mirrors `WebhookRunInput` in shape — all
    connection-time params here, no hidden globals.

    Exactly one of `path` or `data` must be set.
    """

    api_url: str
    webhook_id: str
    token: str
    kind: UploadKind
    path: str | None = None
    data: bytes | None = None
    filename: str | None = None
    mime_type: str | None = None
    timeout_sec: float = 30.0


@dataclass
class UploadResult:
    """Output of a successful upload. `media_key` is what the integrator
    passes to `media_key_message(...)` in a subsequent `session.send`."""

    media_key: str
    mime_type: str
    size_bytes: int
    expires_in_sec: int


class UploadError(Exception):
    """Raised when the presign POST or the PUT to object storage fails.
    The message includes the HTTP status + a short body excerpt — log it,
    do not retry blindly without a backoff."""


async def upload_file(inp: UploadInput) -> UploadResult:
    """Upload a local file (or in-memory bytes) to Daguito's object storage
    and return the `media_key`. Use the key on the next
    `session.send(media_key_message(...))`.

    Raises:
        UploadError: when either HTTP call returns non-2xx, or both
            `path` and `data` are missing/both set.
        FileNotFoundError: when `path` does not exist.
    """
    if (inp.path is None) == (inp.data is None):
        raise UploadError("UploadInput requires exactly one of `path` or `data`")

    if inp.path is not None:
        with open(inp.path, "rb") as f:
            payload = f.read()
        resolved_filename = inp.filename or os.path.basename(inp.path)
    else:
        if not inp.filename:
            raise UploadError("UploadInput.filename is required when passing raw `data`")
        payload = inp.data  # type: ignore[assignment]
        resolved_filename = inp.filename

    size_bytes = len(payload)
    if size_bytes == 0:
        raise UploadError("UploadInput payload is empty")

    resolved_mime = (
        inp.mime_type
        or mimetypes.guess_type(resolved_filename)[0]
        or _default_mime(inp.kind)
    )

    presign_url = join_http(inp.api_url, f"/v1/webhooks/{inp.webhook_id}/upload")
    async with httpx.AsyncClient(timeout=inp.timeout_sec) as client:
        # Step 1: ask Daguito for a presigned PUT URL bound to this exact
        # kind/mime/size. The signer encodes both into the signature so a
        # client cannot upload a larger or different file than it announced.
        presign_resp = await client.post(
            presign_url,
            headers={"Authorization": f"Bearer {inp.token}", **client_headers()},
            json={
                "kind": inp.kind,
                "mime_type": resolved_mime,
                "size_bytes": size_bytes,
                "filename": resolved_filename,
            },
        )
        if presign_resp.status_code >= 400:
            raise UploadError(
                f"presign failed: HTTP {presign_resp.status_code} {presign_resp.text[:200]}"
            )
        presign = presign_resp.json()
        upload_url = presign["upload_url"]
        media_key = presign["key"]
        required_headers = presign.get("required_headers") or {}
        expires_in_sec = int(presign.get("expires_in_sec") or 0)

        # Step 2: PUT bytes directly to object storage. The presigned URL
        # carries auth in its query string — we MUST NOT add the bearer
        # token here (S3/R2 would reject the signed request).
        put_resp = await client.put(
            upload_url,
            headers=required_headers,
            content=payload,
        )
        if put_resp.status_code >= 400:
            raise UploadError(
                f"PUT to storage failed: HTTP {put_resp.status_code} {put_resp.text[:200]}"
            )

    return UploadResult(
        media_key=media_key,
        mime_type=resolved_mime,
        size_bytes=size_bytes,
        expires_in_sec=expires_in_sec,
    )


def _default_mime(kind: UploadKind) -> str:
    """Fallback MIME when caller passes no `mime_type` and filename has no
    recognisable extension."""
    if kind == "image":
        return "image/jpeg"
    if kind == "audio":
        return "audio/mpeg"
    return "application/octet-stream"
