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
    kind: Literal["image", "audio", "document", "video"],
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


# ─── Tool progress (rides on node.emit with kind="tool_progress") ─────────
#
# The server emits granular telemetry for long-running tools (web search,
# media description, KB indexing, …) so UIs can render "searching…",
# "analyzing image…", "indexing document…" without scraping token streams.
# The wire envelope is `node.emit` and the payload's `kind` is the literal
# string "tool_progress" — these dataclasses are pure type sugar over the
# `NodeEmitEvent.data` dict.


@dataclass
class ToolProgressResource:
    kind: str | None = None
    name: str | None = None
    media_key: str | None = None
    url: str | None = None


@dataclass
class ToolProgressEvent:
    """Data-only progress event. Consumers compose user-facing strings from
    (tool, stage, resource, result) via their own i18n.
    """

    tool: str
    stage: str
    progress: float | None = None
    resource: ToolProgressResource | None = None
    trace_id: str | None = None
    attempt: int | None = None


def parse_tool_progress(data: dict[str, Any]) -> ToolProgressEvent | None:
    """Narrow a `NodeEmitEvent.data` dict into a typed `ToolProgressEvent`.

    Returns None when `data['kind']` is not `'tool_progress'`, so callers
    can use it as a discriminator inside their `node.emit` handler.
    """
    if not isinstance(data, dict) or data.get("kind") != "tool_progress":
        return None

    raw_resource = data.get("resource")
    resource: ToolProgressResource | None = None
    if isinstance(raw_resource, dict):
        resource = ToolProgressResource(
            kind=_opt_str(raw_resource.get("kind")),
            name=_opt_str(raw_resource.get("name")),
            media_key=_opt_str(raw_resource.get("media_key")),
            url=_opt_str(raw_resource.get("url")),
        )

    progress_raw = data.get("progress")
    progress: float | None = (
        float(progress_raw) if isinstance(progress_raw, (int, float)) else None
    )

    attempt_raw = data.get("attempt")
    attempt: int | None = attempt_raw if isinstance(attempt_raw, int) else None

    return ToolProgressEvent(
        tool=str(data.get("tool", "")),
        stage=str(data.get("stage", "")),
        progress=progress,
        resource=resource,
        trace_id=_opt_str(data.get("trace_id")),
        attempt=attempt,
    )


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


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
