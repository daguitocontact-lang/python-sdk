"""Contract tests for `WebhookStreamSession`.

Mirrors the pattern from test_audio_stream_session: we replace the
`webhook_stream_session.connect` factory with a fake that lets the test
drive frames the "server" sends and capture frames the SDK sends.

Runs under stdlib unittest:

    cd sdks/python && PYTHONPATH=src python -m unittest tests.test_webhook_stream_session
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from daguito import (
    WebhookStreamOptions,
    WebhookStreamSession,
)
import daguito.webhook_stream_session as stream_mod


class _FakeWS:
    """Minimal stand-in for `websockets.asyncio.client.ClientConnection`."""

    def __init__(self, incoming: list[str]) -> None:
        self._incoming: asyncio.Queue[str | None] = asyncio.Queue()
        for frame in incoming:
            self._incoming.put_nowait(frame)
        self.sent: list[str] = []
        self._closed = False

    def __aiter__(self) -> "_FakeWS":
        return self

    async def __anext__(self) -> str:
        item = await self._incoming.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def send(self, data: Any) -> None:
        if self._closed:
            raise stream_mod.websockets.exceptions.ConnectionClosed(None, None)
        if isinstance(data, str):
            self.sent.append(data)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._incoming.put_nowait(None)

    def push_frame(self, frame: str) -> None:
        self._incoming.put_nowait(frame)


def _patch_connect(handler: Any) -> None:
    stream_mod.connect = handler  # type: ignore[assignment]


def _restore_connect(real: Any) -> None:
    stream_mod.connect = real


class AutoReconnectTest(unittest.TestCase):
    """When the server drops the socket mid-session, the SDK must reopen
    it transparently, reusing the same session_key so the server resumes
    the same Redis pubsub channel. Listeners stay subscribed."""

    def setUp(self) -> None:
        self._real_connect = stream_mod.connect

    def tearDown(self) -> None:
        _restore_connect(self._real_connect)

    def test_reconnects_after_unexpected_drop(self) -> None:
        urls: list[str] = []
        sockets: list[_FakeWS] = []

        async def fake_connect(url: str, **kwargs: Any) -> _FakeWS:
            urls.append(url)
            ws = _FakeWS(incoming=[
                json.dumps({"type": "ready", "webhook_id": "wh_1"}),
                json.dumps({"type": "session.started"}),
            ])
            sockets.append(ws)
            return ws

        _patch_connect(fake_connect)

        closed_events: list[dict[str, Any]] = []

        async def run() -> None:
            opts = WebhookStreamOptions(
                api_url="https://api.example.com",
                webhook_id="wh_1",
                token="sk_wh_TEST",
                session_key="resume-me",
                auto_reconnect=True,
            )
            session = WebhookStreamSession(opts)
            session.on("closed", lambda ev: closed_events.append({"code": ev.code, "reason": ev.reason}))
            await session.connect()
            # Let the first handshake settle.
            for _ in range(50):
                if session._opened.is_set():  # noqa: SLF001 — test inspecting state
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(session._opened.is_set())  # noqa: SLF001
            # Server drops the socket. SDK must reconnect silently.
            await sockets[0].close()
            for _ in range(100):
                if len(sockets) >= 2 and session._opened.is_set():  # noqa: SLF001
                    break
                await asyncio.sleep(0.02)
            self.assertEqual(len(sockets), 2, "reconnect did not happen")
            await session.close()

        asyncio.run(run())
        # Same session_key reused on both connects.
        self.assertEqual(len(urls), 2)
        for u in urls:
            self.assertIn("/v1/webhooks/wh_1/stream", u)
            self.assertIn("token=sk_wh_TEST", u)
        # The second socket received a fresh `session.start` with the
        # original session_key so the server resumes the channel.
        start_frames = [json.loads(s) for s in sockets[1].sent if "session.start" in s]
        self.assertTrue(
            any(f.get("session_key") == "resume-me" for f in start_frames),
            f"expected session.start with same key on reconnect; sent={sockets[1].sent}",
        )
        # `closed` MUST NOT have been dispatched — consumers expect the
        # session to stay alive across a reconnect.
        self.assertEqual(closed_events, [])

    def test_dispatches_closed_when_auto_reconnect_off(self) -> None:
        sockets: list[_FakeWS] = []

        async def fake_connect(url: str, **kwargs: Any) -> _FakeWS:
            ws = _FakeWS(incoming=[
                json.dumps({"type": "ready", "webhook_id": "wh_1"}),
                json.dumps({"type": "session.started"}),
            ])
            sockets.append(ws)
            return ws

        _patch_connect(fake_connect)

        closed_events: list[Any] = []

        async def run() -> None:
            opts = WebhookStreamOptions(
                api_url="https://api.example.com",
                webhook_id="wh_1",
                token="sk_wh_TEST",
                session_key="one-shot",
                auto_reconnect=False,
            )
            session = WebhookStreamSession(opts)
            session.on("closed", lambda ev: closed_events.append(ev))
            await session.connect()
            for _ in range(50):
                if session._opened.is_set():  # noqa: SLF001
                    break
                await asyncio.sleep(0.01)
            await sockets[0].close()
            for _ in range(50):
                if closed_events:
                    break
                await asyncio.sleep(0.01)
            await session.close()

        asyncio.run(run())
        self.assertEqual(len(sockets), 1, "no reconnect expected")
        self.assertEqual(len(closed_events), 1, "closed event should fire when not reconnecting")


if __name__ == "__main__":
    unittest.main()
