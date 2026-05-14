"""Streaming WebSocket session — mirrors sdks/js/src/webhook-stream-session.ts.

The integrator deals only in semantic events:

    session.on("node.token", lambda ev: append(ev.text))
    session.on("flow.completed", lambda ev: done())
    await session.send(text_message("hola"))

Or, more pythonic, async-iterate events as they arrive:

    async with WebhookStreamSession(opts) as session:
        await session.send(text_message("hola"))
        async for event_type, payload in session.events():
            if event_type == "node.token":
                print(payload.text, end="")
            elif event_type == "flow.completed":
                break

Wire concerns (handshake, frame parsing, heartbeats, reconnect) are owned
by this class so callers stay focused on the conversation.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import time
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

import websockets
from websockets.asyncio.client import ClientConnection, connect

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]] | Callable[[dict[str, Any]], Any]
T = TypeVar("T", bound=ToolHandler)

from ._url import random_session_id, to_ws_url
from .emitter import Emitter
from .types import (
    ClosedEvent,
    ErrorEvent,
    FlowCompletedEvent,
    FlowFailedEvent,
    NodeCompletedEvent,
    NodeEmitEvent,
    NodeFailedEvent,
    NodeStartedEvent,
    NodeTokenEvent,
    ReadyEvent,
    WebhookStreamOptions,
)

log = logging.getLogger("daguito.stream")

_TOKEN_KEYS = ("token", "text", "delta", "content")


class WebhookStreamSession:
    """Long-lived bidirectional session for streaming webhooks.

    Use as an async context manager so the socket closes deterministically:

        async with WebhookStreamSession(opts) as session:
            await session.send(text_message("hola"))
            async for event_type, payload in session.events():
                ...
    """

    def __init__(self, opts: WebhookStreamOptions) -> None:
        self._opts = opts
        self._emitter = Emitter()
        self._ws: ClientConnection | None = None
        self._session_key = opts.session_key or random_session_id("py")
        self._started_at = 0.0
        self._opened = asyncio.Event()
        self._closed = False
        # Queue of (event_type, payload) for async iterators. Multiple
        # iterators each get their own queue via `events()`.
        self._iter_queues: list[asyncio.Queue[tuple[str, Any] | None]] = []
        self._recv_task: asyncio.Task[None] | None = None
        self._pending: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        # Registered tool handlers keyed by tool name. When the server emits
        # `agent.tool_call_started` we look up the handler, run it, and push
        # a `tool_result` frame back so the LLM gets the actual return value.
        self._tool_handlers: dict[str, ToolHandler] = {}
        # OpenAI-style tool specs (name/description/parameters) we send on
        # every message via `base_input.client_tools` so the flow's ai_agent
        # node merges them with its statically-declared tools.
        self._tool_specs: dict[str, dict[str, Any]] = {}

    # ─── Lifecycle ──────────────────────────────────────────────────────

    async def __aenter__(self) -> WebhookStreamSession:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the socket and run the auth + session.start handshake."""
        if self._ws is not None or self._closed:
            return
        url = to_ws_url(
            self._opts.api_url,
            f"/v1/webhooks/{self._opts.webhook_id}/stream",
            {"token": self._opts.token},
        )
        log.debug("connecting to %s", url)
        self._ws = await connect(url, ping_interval=25, ping_timeout=20)
        self._recv_task = asyncio.create_task(self._recv_loop(), name="daguito-stream-recv")

    async def close(self) -> None:
        """Close the session. Subsequent calls are no-ops."""
        if self._closed:
            return
        self._closed = True
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "session.end"}))
            except Exception:
                pass
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._recv_task is not None:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except (asyncio.CancelledError, Exception):
                pass
            self._recv_task = None
        # Signal all live iterators to stop.
        for q in self._iter_queues:
            q.put_nowait(None)
        self._iter_queues.clear()
        self._emitter.remove_all()

    # ─── Send ───────────────────────────────────────────────────────────

    async def send(
        self,
        message: dict[str, Any],
        base_input: dict[str, Any] | None = None,
    ) -> None:
        """Send a message into the active session.

        Queues until `ready + session.started` complete, so callers don't
        need to wait themselves. Build `message` with helpers from
        `daguito.types` (text_message, image_url_message, …).
        """
        if self._closed:
            return
        if "file" in message:
            raise ValueError(
                f"WebhookStreamSession.send: kind={message.get('kind')} with file input is not supported. "
                "Use image_url, image_urls, or pre-uploaded media_key instead."
            )

        if not self._opened.is_set():
            self._pending.append((message, base_input))
            await self.connect()
            return
        await self._dispatch(message, base_input)

    async def send_raw(self, frame: dict[str, Any]) -> None:
        """Send a raw control frame. Escape hatch — most callers should use `send()`."""
        if self._closed or self._ws is None:
            return
        await self._ws.send(json.dumps(frame))

    # ─── Subscriptions ──────────────────────────────────────────────────

    def on(self, event: str, listener: Callable[[Any], None]) -> Callable[[], None]:
        """Subscribe to a semantic event. Returns an unsubscribe function."""
        return self._emitter.on(event, listener)

    def off(self, event: str, listener: Callable[[Any], None]) -> None:
        self._emitter.off(event, listener)

    async def events(self) -> AsyncIterator[tuple[str, Any]]:
        """Async-iterate every event received until the session closes.

        Each item is `(event_type, payload_dataclass)`. See
        `daguito.types` for payload shapes.
        """
        queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()
        self._iter_queues.append(queue)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item
        finally:
            try:
                self._iter_queues.remove(queue)
            except ValueError:
                pass

    # ─── Client-side tools ──────────────────────────────────────────────

    def tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        timeout_seconds: float = 30.0,
    ) -> Callable[[T], T]:
        """Register a tool the LLM can invoke during this session.

        The shape follows OpenAI function-calling exactly:
        `name`, `description`, and a JSON Schema `parameters` object. When the
        LLM calls this tool, your handler runs locally and its return value
        is fed back to the model as the tool result.

        Usage:

            @session.tool(
                name="update_soap_section",
                description="Updates a SOAP section with new info",
                parameters={
                    "type": "object",
                    "properties": {
                        "section": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["section", "content"],
                },
            )
            async def update_soap(args: dict) -> dict:
                # do work, return JSON-serialisable payload
                return {"success": True, "soap_id": "..."}

        Returns the original function so the decorator is transparent.
        """

        def decorator(func: T) -> T:
            self._tool_handlers[name] = func
            self._tool_specs[name] = {
                "name": name,
                "description": description,
                "parameters": parameters,
                "client_timeout_ms": int(timeout_seconds * 1000),
            }
            return func

        return decorator

    # ─── Internals ──────────────────────────────────────────────────────

    async def _dispatch(
        self, message: dict[str, Any], base_input: dict[str, Any] | None
    ) -> None:
        if self._ws is None:
            return
        inbound = self._to_inbound(message)
        envelope: dict[str, Any] = {"type": "message", "message": inbound}
        computed_base = {
            **self._compute_base_input(message),
            **(base_input or self._opts.base_input or {}),
        }
        # Auto-inject the OpenAI-shaped tool specs for any tool registered
        # via @session.tool. The flow's ai_agent node merges these with the
        # tools declared statically on its config so the LLM sees both sets.
        if self._tool_specs:
            existing = computed_base.get("client_tools")
            specs = list(self._tool_specs.values())
            if isinstance(existing, list):
                computed_base["client_tools"] = existing + specs
            else:
                computed_base["client_tools"] = specs
        # Server-side scope filter for KB searches. Only set if the caller
        # didn't already provide one explicitly through base_input.
        if self._opts.scope and "scope" not in computed_base:
            computed_base["scope"] = dict(self._opts.scope)
        if computed_base:
            envelope["base_input"] = computed_base
        await self._ws.send(json.dumps(envelope))

    @staticmethod
    def _to_inbound(message: dict[str, Any]) -> dict[str, Any]:
        # The streaming WS path uses kind=text on the InboundMessage and
        # moves media references onto base_input — except for pre-uploaded
        # media which travels on `media`.
        kind = message.get("kind", "text")
        if kind != "form-response" and "media_key" in message:
            # MediaRefSchema on the server uses `key` (not `media_key`); the
            # SDK helper takes `media_key` as a friendlier alias and we
            # rename it here at the wire boundary.
            return {
                "kind": kind,
                "text": message.get("text"),
                "media": {
                    "key": message["media_key"],
                    "mime_type": message["mime_type"],
                    "size_bytes": message["size_bytes"],
                },
            }
        if kind == "form-response":
            return {"kind": "text", "text": "[form-response]"}
        if kind == "text":
            return {"kind": "text", "text": message.get("text", "")}
        return {"kind": "text", "text": message.get("text", "") or ""}

    @staticmethod
    def _compute_base_input(message: dict[str, Any]) -> dict[str, Any]:
        kind = message.get("kind")
        if kind == "image" and "image_url" in message:
            return {"image_url": message["image_url"]}
        if kind == "image-multi" and "image_urls" in message:
            return {"image_urls": message["image_urls"]}
        if kind == "form-response":
            return {
                "form_response": message.get("payload", {}),
                "form_response_id": message.get("form_id", ""),
                "is_form_response": True,
            }
        return {}

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    frame = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                if isinstance(frame, dict):
                    await self._handle_frame(frame)
        except websockets.exceptions.ConnectionClosed as err:
            self._dispatch_event(
                "closed", ClosedEvent(code=err.code, reason=err.reason or "")
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("recv loop crashed")
            self._dispatch_event("error", ErrorEvent(message="recv loop crashed"))

    async def _handle_frame(self, frame: dict[str, Any]) -> None:
        kind = frame.get("type", "") if isinstance(frame, dict) else ""

        if kind == "ready":
            self._dispatch_event(
                "ready",
                ReadyEvent(webhook_id=str(frame.get("webhook_id", self._opts.webhook_id))),
            )
            if self._ws is not None:
                await self._ws.send(
                    json.dumps({"type": "session.start", "session_key": self._session_key})
                )
            return

        if kind == "session.started":
            self._opened.set()
            self._started_at = time.time()
            queued = self._pending
            self._pending = []
            for message, base_input in queued:
                await self._dispatch(message, base_input)
            return

        if kind == "session.ended":
            self._opened.clear()
            return

        if kind in ("pong", "ping"):
            return

        if kind == "error":
            self._dispatch_event(
                "error", ErrorEvent(message=str(frame.get("message", "unknown error")))
            )
            return

        data = frame.get("data") if isinstance(frame.get("data"), dict) else {}
        node_id = str(frame.get("node_id", "")) if isinstance(frame.get("node_id"), str) else ""

        if kind == "node.token":
            text = _pick_token(data)
            if text:
                self._dispatch_event("node.token", NodeTokenEvent(node_id=node_id, text=text))
            return

        if kind in ("node.started", "merge.progress"):
            self._dispatch_event("node.started", NodeStartedEvent(node_id=node_id))
            return

        if kind == "node.completed":
            dur = data.get("duration_ms")
            if not isinstance(dur, int):
                dur = data.get("elapsed_ms")
                if not isinstance(dur, int):
                    dur = None
            self._dispatch_event(
                "node.completed",
                NodeCompletedEvent(node_id=node_id, duration_ms=dur, output=data.get("output")),
            )
            return

        if kind == "node.failed":
            self._dispatch_event(
                "node.failed",
                NodeFailedEvent(
                    node_id=node_id,
                    error=data.get("error") if isinstance(data.get("error"), str) else None,
                ),
            )
            return

        if kind == "node.emit":
            emit_kind = str(data.get("kind", ""))
            self._dispatch_event(
                "node.emit",
                NodeEmitEvent(node_id=node_id, kind=emit_kind, data=data),
            )
            # If the LLM invoked one of our registered tools, run the handler
            # in the background and push the result back. We schedule rather
            # than await so the recv loop keeps draining tokens/events from
            # the server while the tool runs.
            if emit_kind == "agent.tool_call_started":
                tool_name = data.get("tool_name")
                call_id = data.get("call_id")
                args = data.get("args")
                if (
                    isinstance(tool_name, str)
                    and isinstance(call_id, str)
                    and tool_name in self._tool_handlers
                ):
                    asyncio.create_task(
                        self._run_client_tool(tool_name, call_id, args or {})
                    )
            return

        if kind == "flow.completed":
            elapsed_ms = (
                int((time.time() - self._started_at) * 1000) if self._started_at else 0
            )
            self._dispatch_event(
                "flow.completed",
                FlowCompletedEvent(elapsed_ms=elapsed_ms, output=data.get("output")),
            )
            return

        if kind == "flow.failed":
            self._dispatch_event(
                "flow.failed",
                FlowFailedEvent(
                    error=str(data.get("error", "flow failed"))
                    if isinstance(data.get("error"), str)
                    else "flow failed"
                ),
            )
            return

    async def _run_client_tool(
        self, tool_name: str, call_id: str, args: dict[str, Any]
    ) -> None:
        """Execute a registered tool handler and push the result back over WS."""
        handler = self._tool_handlers.get(tool_name)
        if handler is None or self._ws is None:
            return
        result: Any
        error: str | None = None
        try:
            outcome = handler(args)
            if inspect.isawaitable(outcome):
                result = await outcome
            else:
                result = outcome
        except Exception as exc:
            log.exception("tool handler %r raised", tool_name)
            result = None
            error = f"{type(exc).__name__}: {exc}"

        frame: dict[str, Any] = {
            "type": "tool_result",
            "call_id": call_id,
            "ok": error is None,
        }
        if error is not None:
            frame["error"] = error
        else:
            frame["result"] = result
        try:
            await self._ws.send(json.dumps(frame))
        except Exception:
            log.exception("failed to send tool_result for %r", call_id)

    def _dispatch_event(self, event_type: str, payload: Any) -> None:
        self._emitter.emit(event_type, payload)
        for q in self._iter_queues:
            q.put_nowait((event_type, payload))


def _pick_token(data: dict[str, Any]) -> str:
    for key in _TOKEN_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
