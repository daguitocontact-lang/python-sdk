"""One-shot wrapper over `WebhookStreamSession` — mirrors
sdks/js/src/webhook-run-stream.ts.

Opens a streaming WS session, sends one message, waits for `flow.completed`,
closes, and returns the final output — same ergonomics as `run_webhook` HTTP,
but without the 100 s edge timeout the proxy enforces on HTTP. For flows that
may run longer than an HTTP request is willing to wait (long generations,
vision pipelines, multi-step tools).

The shape of `WebhookRunStreamResult` matches `WebhookRunResult` so callers
can swap from `run_webhook` to `run_webhook_stream` without touching their
parsing code.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal

from .types import WebhookStreamOptions, text_message
from .webhook_stream_session import WebhookStreamSession


@dataclass
class WebhookRunStreamInput:
    api_url: str
    """Streaming webhook id (`wh_...`). Resolve via `client.flows.resolve_webhook(slug)`."""
    webhook_id: str
    """Webhook token (`sk_wh_...`)."""
    token: str
    """Free-form input passed to the flow as `base_input`."""
    input: dict[str, Any] | None = None
    """Inline message text sent on the WS. Defaults to a single space when the
    caller only wants to deliver `input` (the flow may not need a user-facing
    message at all — webhook agents start from `base_input`)."""
    text: str | None = None
    """Optional caller-supplied session key (defaults to a fresh uuid)."""
    session_key: str | None = None
    """Optional ceiling that rejects if the flow has not completed in time.
    No default — WS has no edge timeout, so this is opt-in."""
    timeout_ms: int | None = None


@dataclass
class WebhookRunStreamResult:
    ok: bool
    execution_id: str
    status: Literal["completed", "failed", "unknown"]
    output: Any
    elapsed_ms: int


class WebhookStreamRunError(Exception):
    """Raised when the streaming run fails, times out, or is aborted."""

    def __init__(
        self,
        message: str,
        status: Literal["failed", "timeout", "aborted", "closed"] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status


def _payload_attr(payload: Any, key: str) -> Any:
    """Pull a field from an event payload that may be a dataclass or a dict."""
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload.get(key)
    return getattr(payload, key, None)


async def _run(
    session: WebhookStreamSession,
    input_: WebhookRunStreamInput,
) -> WebhookRunStreamResult:
    token_buffer: list[str] = []
    # Collect `node.completed` outputs in order so we can fall back when
    # the server does not emit `flow.completed` with an `output`.
    node_outputs: list[Any] = []
    execution_id = ""
    started_at = time.monotonic()

    loop = asyncio.get_running_loop()
    done: asyncio.Future[WebhookRunStreamResult] = loop.create_future()

    def _resolve(result: WebhookRunStreamResult) -> None:
        if not done.done():
            done.set_result(result)

    def _reject(err: WebhookStreamRunError) -> None:
        if not done.done():
            done.set_exception(err)

    def _on_token(evt: Any) -> None:
        text = _payload_attr(evt, "text")
        if isinstance(text, str):
            token_buffer.append(text)

    def _on_node_completed(evt: Any) -> None:
        out = _payload_attr(evt, "output")
        if out is not None:
            node_outputs.append(out)

    def _on_node_emit(evt: Any) -> None:
        nonlocal execution_id
        data = _payload_attr(evt, "data")
        if isinstance(data, dict):
            exec_id = data.get("execution_id")
            if isinstance(exec_id, str) and exec_id:
                execution_id = exec_id

    def _on_flow_completed(evt: Any) -> None:
        out = _payload_attr(evt, "output")
        if out is None:
            if node_outputs:
                out = node_outputs[-1]
            elif token_buffer:
                out = {"content": "".join(token_buffer)}
        elapsed_ms = _payload_attr(evt, "elapsed_ms")
        if not isinstance(elapsed_ms, int):
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
        _resolve(
            WebhookRunStreamResult(
                ok=True,
                execution_id=execution_id,
                status="completed",
                output=out,
                elapsed_ms=elapsed_ms,
            )
        )

    def _on_flow_failed(evt: Any) -> None:
        err = _payload_attr(evt, "error") or "flow failed"
        _reject(WebhookStreamRunError(str(err), "failed"))

    def _on_error(evt: Any) -> None:
        msg = _payload_attr(evt, "message") or "transport error"
        _reject(WebhookStreamRunError(str(msg), "failed"))

    def _on_closed(evt: Any) -> None:
        # Only fire if we hadn't already resolved (clean close after
        # flow.completed is normal).
        if not done.done():
            reason = _payload_attr(evt, "reason") or "closed before flow.completed"
            _reject(WebhookStreamRunError(str(reason), "closed"))

    # Register handlers BEFORE send() so the very first frames (ready,
    # session.started, node.* lifecycle) are observed. The emitter is sync —
    # listeners fire from `_handle_frame` during the recv loop, no race.
    session.on("node.token", _on_token)
    session.on("node.completed", _on_node_completed)
    session.on("node.emit", _on_node_emit)
    session.on("flow.completed", _on_flow_completed)
    session.on("flow.failed", _on_flow_failed)
    session.on("error", _on_error)
    session.on("closed", _on_closed)

    await session.connect()
    await session.send(
        text_message(input_.text if input_.text is not None else " "),
        input_.input,
    )

    return await done


async def run_webhook_stream(input: WebhookRunStreamInput) -> WebhookRunStreamResult:
    """Open a WS session, send one message, wait for `flow.completed`, close,
    and return the final output.

    Same ergonomics as `run_webhook()` HTTP but over WS — no Cloudflare 100 s
    edge timeout. Use this for flows that may run longer than an HTTP request
    is willing to wait.
    """
    session = WebhookStreamSession(
        WebhookStreamOptions(
            api_url=input.api_url,
            webhook_id=input.webhook_id,
            token=input.token,
            session_key=input.session_key,
            base_input=input.input,
            auto_reconnect=False,
        )
    )
    try:
        if input.timeout_ms and input.timeout_ms > 0:
            try:
                return await asyncio.wait_for(_run(session, input), timeout=input.timeout_ms / 1000.0)
            except asyncio.TimeoutError as err:
                raise WebhookStreamRunError(
                    f"timed out after {input.timeout_ms}ms", "timeout"
                ) from err
        return await _run(session, input)
    finally:
        try:
            await session.close()
        except Exception:
            pass
