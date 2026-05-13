"""Public types — mirrors sdks/js/src/types.ts.

Pure dataclasses + literal-string enums. No external dep (pydantic optional).
SendableMessage variants are represented as plain dicts at the wire boundary;
helpers below build well-typed dicts for each modality.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

NodeLifecycle = Literal["started", "completed", "failed"]

# Wire-level event names emitted by streaming sessions.
StreamEvent = Literal[
    "ready",
    "closed",
    "node.token",
    "node.started",
    "node.completed",
    "node.failed",
    "node.emit",
    "flow.completed",
    "flow.failed",
    "error",
]


@dataclass
class WebhookStreamOptions:
    """Options for WebhookStreamSession. Mirrors WebhookStreamOptions in TS."""

    api_url: str
    webhook_id: str
    token: str
    session_key: str | None = None
    base_input: dict[str, Any] | None = None
    auto_reconnect: bool = True
    scope: dict[str, str | int | float | bool] | None = None
    """
    Server-enforced metadata filter applied to KB searches in this session.

    Example: `{"consultation_uuid": "abc-123", "patient_id": "456"}` makes
    every `search_knowledge_base` call return only chunks whose payload
    matches all those keys. The LLM never sees these values — Daguito
    injects them at the tool boundary, so a hallucinated UUID can't widen
    the scope or leak data across conversations.

    Only primitive values (str, int, float, bool) are forwarded. Arrays
    and objects are silently dropped.
    """


# ─── Sendable message builders ─────────────────────────────────────────────
#
# In TS this is a discriminated union; in Python we expose builders that
# return dicts in the wire shape. The session's `send()` method accepts these
# dicts directly.


def text_message(text: str) -> dict[str, Any]:
    return {"kind": "text", "text": text}


def image_url_message(image_url: str, text: str | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"kind": "image", "image_url": image_url}
    if text is not None:
        msg["text"] = text
    return msg


def image_multi_message(
    image_urls: list[str], text: str | None = None
) -> dict[str, Any]:
    msg: dict[str, Any] = {"kind": "image-multi", "image_urls": image_urls}
    if text is not None:
        msg["text"] = text
    return msg


def media_key_message(
    kind: Literal["image", "audio", "document"],
    media_key: str,
    mime_type: str,
    size_bytes: int,
    text: str | None = None,
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "kind": kind,
        "media_key": media_key,
        "mime_type": mime_type,
        "size_bytes": size_bytes,
    }
    if text is not None:
        msg["text"] = text
    return msg


def form_response_message(form_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "form-response", "form_id": form_id, "payload": payload}


# ─── Stream event payloads ────────────────────────────────────────────────


@dataclass
class ReadyEvent:
    webhook_id: str


@dataclass
class ClosedEvent:
    code: int | None = None
    reason: str | None = None


@dataclass
class NodeTokenEvent:
    node_id: str
    text: str


@dataclass
class NodeStartedEvent:
    node_id: str


@dataclass
class NodeCompletedEvent:
    node_id: str
    duration_ms: int | None = None
    output: Any = None


@dataclass
class NodeFailedEvent:
    node_id: str
    error: str | None = None


@dataclass
class NodeEmitEvent:
    node_id: str
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class FlowCompletedEvent:
    elapsed_ms: int
    output: Any = None


@dataclass
class FlowFailedEvent:
    error: str


@dataclass
class ErrorEvent:
    message: str
