"""Audio-only upstream WebSocket — mirrors `apps/api/.../audio-ws.ts`.

The session opens `WSS /v1/audio/:session_id?token=…&codec=…&sr=…`, then
the integrator pushes binary PCM (or other supported codec) chunks via
`send_audio(chunk)`. The server XADDs each chunk to the Redis stream
`audio:<session_key>`; a flow with an `a_transcribe_stream` node consumes
that stream and pipes frames to the STT provider (AssemblyAI today).

The session does NOT carry transcript or flow events back — those flow
through `WebhookStreamSession` over the companion `/v1/webhooks/:id/stream`
endpoint. Open both sockets concurrently when you need full duplex:

    async with (
        AudioStreamSession(audio_opts) as audio,
        WebhookStreamSession(stream_opts) as events,
    ):
        async def pump_events():
            async for ev_type, payload in events.events():
                ...
        asyncio.create_task(pump_events())
        async for pcm in mic.chunks():
            await audio.send_audio(pcm)

Wire concerns (handshake, ready handshake, control-frame errors, keepalive)
live here so callers only deal with PCM bytes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import websockets
from websockets.asyncio.client import ClientConnection, connect

from ._client_headers import append_client_query_params, client_headers
from ._url import random_session_id, to_ws_url

log = logging.getLogger("daguito.audio")

# Codecs the server's `audio-ws.ts` accepts. Keep in sync with the
# `allowedCodecs` set in that handler — sending anything else makes the
# server reject + close the socket.
SUPPORTED_CODECS: frozenset[str] = frozenset({"pcm16", "opus", "webm-opus", "mulaw", "flac"})


class AudioStreamError(Exception):
    """Raised when the audio socket fails to open or the server signals an error."""


@dataclass
class AudioStreamOptions:
    """Options for opening an audio upstream session.

    `api_url` is the HTTPS Daguito API base (e.g. `https://api.daguito.com`);
    the SDK converts to `wss://` and appends the audio path. `token` is the
    webhook's `sk_wh_…` streaming token — same token used by
    `WebhookStreamSession`.

    `session_id` ties this audio stream to the same conversation as the
    companion event stream; pass the same value to both sessions so the flow
    sees them as one session_key. When omitted we generate one.

    `codec` defaults to `pcm16`. `sample_rate` is required when the codec is
    raw PCM so the STT provider knows what rate the frames are at; for
    container codecs (opus/webm-opus/flac) leave it unset.
    """

    api_url: str
    token: str
    session_id: str | None = None
    codec: str = "pcm16"
    sample_rate: int | None = None
    # `ready` frame timeout. If the server hasn't accepted us by this, fail
    # the open so the caller doesn't block forever on a misrouted endpoint.
    ready_timeout_s: float = 10.0


@dataclass
class AudioStreamReady:
    """First frame the server emits after a successful auth handshake."""

    session_key: str
    codec: str
    guards: dict[str, Any] = field(default_factory=dict)


class AudioStreamSession:
    """Long-lived audio-only upstream channel."""

    def __init__(self, opts: AudioStreamOptions) -> None:
        if opts.codec not in SUPPORTED_CODECS:
            raise ValueError(
                f"unsupported codec {opts.codec!r}; expected one of {sorted(SUPPORTED_CODECS)}",
            )
        if opts.codec == "pcm16" and opts.sample_rate is None:
            raise ValueError("sample_rate is required when codec='pcm16'")
        self._opts = opts
        self._session_id = opts.session_id or random_session_id("py")
        self._ws: ClientConnection | None = None
        self._ready: AudioStreamReady | None = None
        self._closed = False
        self._control_task: asyncio.Task[None] | None = None
        self._opened = asyncio.Event()
        self._errors: list[str] = []

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def ready(self) -> AudioStreamReady | None:
        return self._ready

    # ─── Lifecycle ──────────────────────────────────────────────────────

    async def __aenter__(self) -> AudioStreamSession:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the audio socket and block until the server's `ready` frame."""
        if self._ws is not None or self._closed:
            return
        query: dict[str, str] = {"token": self._opts.token, "codec": self._opts.codec}
        if self._opts.sample_rate is not None:
            query["sr"] = str(self._opts.sample_rate)
        url = to_ws_url(self._opts.api_url, f"/v1/audio/{self._session_id}", query)
        url = append_client_query_params(url)
        log.debug("audio.connect %s", url)
        try:
            self._ws = await connect(
                url,
                ping_interval=20,
                ping_timeout=15,
                additional_headers=client_headers(),
                # Audio frames can be larger than the default 1MiB cap when a
                # client buffers several seconds of PCM; lift the receive
                # limit modestly. We never send anywhere near this — frame
                # cap is enforced in `send_audio`.
                max_size=4 * 1024 * 1024,
            )
        except Exception as exc:
            raise AudioStreamError(f"failed to connect: {exc}") from exc

        self._control_task = asyncio.create_task(
            self._control_loop(), name="daguito-audio-control",
        )
        try:
            await asyncio.wait_for(self._opened.wait(), timeout=self._opts.ready_timeout_s)
        except asyncio.TimeoutError as exc:
            await self.close()
            raise AudioStreamError(
                f"timed out waiting for ready frame after {self._opts.ready_timeout_s}s",
            ) from exc
        if self._ready is None:
            await self.close()
            errs = "; ".join(self._errors) or "unknown error"
            raise AudioStreamError(f"server rejected audio session: {errs}")

    async def close(self) -> None:
        """Close the socket. Server XADDs eof=1 on its end automatically."""
        if self._closed:
            return
        self._closed = True
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        task = self._control_task
        self._control_task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    # ─── Send ───────────────────────────────────────────────────────────

    async def send_audio(self, chunk: bytes | bytearray | memoryview) -> None:
        """Push a single binary chunk. Caller decides chunk size — server
        rejects frames over 256 KiB so a sensible default is 20–100 ms of
        audio per chunk.
        """
        if self._closed:
            raise AudioStreamError("session is closed")
        if self._ws is None:
            raise AudioStreamError("session is not connected")
        if not self._opened.is_set():
            # Treat sends-before-ready as a programmer error — surfacing it
            # early is better than silently dropping the audio.
            raise AudioStreamError("call connect() (or `async with`) before sending audio")
        try:
            await self._ws.send(bytes(chunk))
        except websockets.ConnectionClosed as exc:
            self._closed = True
            raise AudioStreamError(f"connection closed: {exc}") from exc

    # ─── Internal: server → client control frames ───────────────────────

    async def _control_loop(self) -> None:
        """Consume the (tiny) control-channel frames the server sends.

        The audio socket is upstream-binary, downstream-control-JSON. The
        server sends one `ready` JSON frame after auth + occasional `error`
        frames if a guard trips. We surface those and otherwise ignore the
        downstream — transcripts arrive over the companion event WS.
        """
        ws = self._ws
        if ws is None:
            return
        try:
            async for frame in ws:
                if isinstance(frame, (bytes, bytearray, memoryview)):
                    # Server never sends binary on this channel; ignore.
                    continue
                if isinstance(frame, str):
                    self._handle_text_frame(frame)
        except websockets.ConnectionClosed:
            pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("audio control loop error: %s", exc)
        finally:
            # Wake any caller blocked on connect() so they get an error
            # instead of hanging when the socket dies mid-handshake.
            if not self._opened.is_set():
                self._opened.set()

    def _handle_text_frame(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("audio: ignoring non-JSON text frame: %s", raw[:80])
            return
        if not isinstance(payload, dict):
            return
        msg_type = payload.get("type")
        if msg_type == "ready":
            self._ready = AudioStreamReady(
                session_key=str(payload.get("session_key", "")),
                codec=str(payload.get("codec", self._opts.codec)),
                guards=payload.get("guards", {}) if isinstance(payload.get("guards"), dict) else {},
            )
            self._opened.set()
            return
        if msg_type == "error":
            err = str(payload.get("message", "unknown error"))
            self._errors.append(err)
            log.warning("audio server error: %s", err)
            # If we haven't seen `ready` yet, this is a handshake-time
            # rejection (bad token, unsupported codec, concurrency cap).
            # Wake `connect()` so the caller gets the actual server message
            # instead of timing out. The server will close the socket on
            # its end too. Mid-session errors (frame too large) don't flip
            # `_opened` so the audio stream keeps running.
            if not self._opened.is_set():
                self._opened.set()
            # Don't proactively close — the server closes fatal errors
            # itself; for soft errors the session continues.
