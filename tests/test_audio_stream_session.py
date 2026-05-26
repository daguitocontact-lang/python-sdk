"""Contract tests for `AudioStreamSession`.

We replace `daguito.audio_stream_session.connect` (the `websockets` client
constructor) with a fake that:
  - records the URL + headers the SDK opened with,
  - lets the test drive what frames the "server" sends back,
  - captures the binary frames the SDK sends.

The real socket / network is never touched. Runs under stdlib `unittest`:

    cd sdks/python && python -m unittest tests.test_audio_stream_session
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

from daguito import (
    AudioStreamError,
    AudioStreamOptions,
    AudioStreamSession,
    SUPPORTED_CODECS,
)
import daguito.audio_stream_session as audio_mod


class _FakeWS:
    """Minimal stand-in for `websockets.asyncio.client.ClientConnection`.

    Yields whatever JSON frames the test put in `incoming`, captures binary
    sends to `sent_binary`, and stays open until `close()` is awaited.
    """

    def __init__(self, incoming: list[str]) -> None:
        self._incoming: asyncio.Queue[str | None] = asyncio.Queue()
        for frame in incoming:
            self._incoming.put_nowait(frame)
        self.sent_binary: list[bytes] = []
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
            raise audio_mod.websockets.ConnectionClosed(None, None)
        if isinstance(data, (bytes, bytearray, memoryview)):
            self.sent_binary.append(bytes(data))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._incoming.put_nowait(None)


def _patch_connect(handler: Any) -> None:
    """Replace `audio_mod.connect` for the duration of a test. `handler` is
    an async function `(url, **kwargs) -> _FakeWS` that the test provides.
    """
    audio_mod.connect = handler  # type: ignore[assignment]


def _restore_connect(real: Any) -> None:
    audio_mod.connect = real


class CodecValidationTest(unittest.TestCase):
    def test_rejects_unsupported_codec(self) -> None:
        with self.assertRaises(ValueError):
            AudioStreamSession(
                AudioStreamOptions(api_url="https://api.example.com", token="sk_wh_x", codec="mp3"),
            )

    def test_requires_sample_rate_for_pcm16(self) -> None:
        with self.assertRaises(ValueError):
            AudioStreamSession(
                AudioStreamOptions(api_url="https://api.example.com", token="sk_wh_x"),
            )

    def test_accepts_supported_codecs(self) -> None:
        for codec in SUPPORTED_CODECS:
            kwargs: dict[str, Any] = {
                "api_url": "https://api.example.com",
                "token": "sk_wh_x",
                "codec": codec,
            }
            if codec == "pcm16":
                kwargs["sample_rate"] = 16_000
            AudioStreamSession(AudioStreamOptions(**kwargs))


class ConnectHandshakeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._real_connect = audio_mod.connect

    def tearDown(self) -> None:
        _restore_connect(self._real_connect)

    def test_connect_builds_url_with_codec_sr_and_token(self) -> None:
        captured: dict[str, Any] = {}

        async def fake_connect(url: str, **kwargs: Any) -> _FakeWS:
            captured["url"] = url
            captured["headers"] = kwargs.get("additional_headers")
            return _FakeWS(incoming=[json.dumps({"type": "ready", "session_key": "k", "codec": "pcm16"})])

        _patch_connect(fake_connect)

        async def run() -> None:
            opts = AudioStreamOptions(
                api_url="https://api.example.com",
                token="sk_wh_TEST",
                session_id="sess123",
                codec="pcm16",
                sample_rate=16_000,
            )
            async with AudioStreamSession(opts) as audio:
                self.assertEqual(audio.session_id, "sess123")
                self.assertIsNotNone(audio.ready)
                self.assertEqual(audio.ready.codec, "pcm16")  # type: ignore[union-attr]

        asyncio.run(run())
        url = captured["url"]
        self.assertIn("wss://api.example.com/v1/audio/sess123", url)
        self.assertIn("token=sk_wh_TEST", url)
        self.assertIn("codec=pcm16", url)
        self.assertIn("sr=16000", url)
        # SDK tracking headers must be present even on the audio socket.
        headers = captured["headers"]
        self.assertIsNotNone(headers)
        self.assertEqual(headers["X-Daguito-Client-Lang"], "python")  # type: ignore[index]

    def test_connect_times_out_when_no_ready_frame(self) -> None:
        async def fake_connect(url: str, **kwargs: Any) -> _FakeWS:
            return _FakeWS(incoming=[])  # server never sends `ready`

        _patch_connect(fake_connect)

        async def run() -> None:
            opts = AudioStreamOptions(
                api_url="https://api.example.com",
                token="sk_wh_x",
                codec="pcm16",
                sample_rate=16_000,
                ready_timeout_s=0.05,
            )
            with self.assertRaises(AudioStreamError) as cm:
                async with AudioStreamSession(opts):
                    pass
            self.assertIn("timed out", str(cm.exception))

        asyncio.run(run())

    def test_connect_surfaces_server_error_frame(self) -> None:
        async def fake_connect(url: str, **kwargs: Any) -> _FakeWS:
            return _FakeWS(
                incoming=[json.dumps({"type": "error", "message": "unsupported codec: mp3"})],
            )

        _patch_connect(fake_connect)

        async def run() -> None:
            opts = AudioStreamOptions(
                api_url="https://api.example.com",
                token="sk_wh_x",
                codec="pcm16",
                sample_rate=16_000,
                ready_timeout_s=0.5,
            )
            with self.assertRaises(AudioStreamError) as cm:
                async with AudioStreamSession(opts):
                    pass
            self.assertIn("unsupported codec", str(cm.exception))

        asyncio.run(run())


class SendAudioTest(unittest.TestCase):
    def setUp(self) -> None:
        self._real_connect = audio_mod.connect

    def tearDown(self) -> None:
        _restore_connect(self._real_connect)

    def test_send_audio_pushes_binary_chunk(self) -> None:
        socket_holder: dict[str, _FakeWS] = {}

        async def fake_connect(url: str, **kwargs: Any) -> _FakeWS:
            ws = _FakeWS(
                incoming=[json.dumps({"type": "ready", "session_key": "k", "codec": "pcm16"})],
            )
            socket_holder["ws"] = ws
            return ws

        _patch_connect(fake_connect)

        async def run() -> None:
            opts = AudioStreamOptions(
                api_url="https://api.example.com",
                token="sk_wh_x",
                codec="pcm16",
                sample_rate=16_000,
            )
            async with AudioStreamSession(opts) as audio:
                await audio.send_audio(b"\x00\x01\x02\x03")
                await audio.send_audio(bytearray([4, 5, 6, 7]))

        asyncio.run(run())
        ws = socket_holder["ws"]
        self.assertEqual(len(ws.sent_binary), 2)
        self.assertEqual(ws.sent_binary[0], b"\x00\x01\x02\x03")
        self.assertEqual(ws.sent_binary[1], b"\x04\x05\x06\x07")

    def test_send_audio_before_connect_raises(self) -> None:
        async def run() -> None:
            opts = AudioStreamOptions(
                api_url="https://api.example.com",
                token="sk_wh_x",
                codec="pcm16",
                sample_rate=16_000,
            )
            audio = AudioStreamSession(opts)
            with self.assertRaises(AudioStreamError):
                await audio.send_audio(b"\x00")

        asyncio.run(run())


class AutoReconnectTest(unittest.TestCase):
    """Server drops the socket mid-session — the SDK must reopen it
    transparently, reusing the same session_id so the server-side Redis
    stream key stays consistent. send_audio() during the gap drops chunks
    silently instead of throwing."""

    def setUp(self) -> None:
        self._real_connect = audio_mod.connect

    def tearDown(self) -> None:
        _restore_connect(self._real_connect)

    def test_reconnects_after_unexpected_drop(self) -> None:
        # Two fake sockets — the first one drops after one chunk, the
        # second one accepts the rest. We assert both saw the same
        # session_id in the URL.
        urls: list[str] = []
        sockets: list[_FakeWS] = []

        async def fake_connect(url: str, **kwargs: Any) -> _FakeWS:
            urls.append(url)
            ws = _FakeWS(incoming=[json.dumps({"type": "ready", "session_key": "k", "codec": "pcm16"})])
            sockets.append(ws)
            return ws

        _patch_connect(fake_connect)

        async def run() -> None:
            opts = AudioStreamOptions(
                api_url="https://api.example.com",
                token="sk_wh_x",
                session_id="resume-me",
                codec="pcm16",
                sample_rate=16_000,
                auto_reconnect=True,
            )
            audio = AudioStreamSession(opts)
            await audio.connect()
            await audio.send_audio(b"\x01")
            # Simulate the server going down: close the live socket. The
            # SDK control loop sees ConnectionClosed → reconnect kicks in.
            await sockets[0].close()
            # Give the reconnect task time to run + handshake.
            for _ in range(50):
                if len(sockets) >= 2 and audio.ready is not None:
                    break
                await asyncio.sleep(0.02)
            self.assertEqual(len(sockets), 2, "reconnect did not happen")
            await audio.send_audio(b"\x02")
            await audio.close()

        asyncio.run(run())
        # Both connect calls should have reused the same session_id.
        self.assertEqual(len(urls), 2)
        for u in urls:
            self.assertIn("/v1/audio/resume-me", u)
        # First socket got chunk \x01, second one got \x02. The drop
        # between them did not surface as an exception.
        self.assertEqual(sockets[0].sent_binary, [b"\x01"])
        self.assertEqual(sockets[1].sent_binary, [b"\x02"])

    def test_send_audio_during_outage_does_not_raise(self) -> None:
        sockets: list[_FakeWS] = []
        slow_second: asyncio.Event = asyncio.Event()

        async def fake_connect(url: str, **kwargs: Any) -> _FakeWS:
            if len(sockets) == 1:
                # Hold the second handshake until the test releases it,
                # so we can prove send_audio doesn't throw during the gap.
                await slow_second.wait()
            ws = _FakeWS(incoming=[json.dumps({"type": "ready", "session_key": "k", "codec": "pcm16"})])
            sockets.append(ws)
            return ws

        _patch_connect(fake_connect)

        async def run() -> None:
            opts = AudioStreamOptions(
                api_url="https://api.example.com",
                token="sk_wh_x",
                session_id="resume-me",
                codec="pcm16",
                sample_rate=16_000,
                auto_reconnect=True,
            )
            audio = AudioStreamSession(opts)
            await audio.connect()
            await sockets[0].close()
            # We're now in the reconnect gap (second connect is blocked).
            # send_audio must NOT raise — the caller's mic-pump loop has to
            # survive a transient outage.
            for _ in range(5):
                await audio.send_audio(b"\x00")
            slow_second.set()
            for _ in range(50):
                if len(sockets) >= 2 and audio.ready is not None:
                    break
                await asyncio.sleep(0.02)
            await audio.close()

        asyncio.run(run())
        # The 5 chunks during the outage must have been dropped — none of
        # them landed on the closed socket, and the second socket was not
        # yet open when they were sent.
        self.assertEqual(sockets[0].sent_binary, [])
        self.assertEqual(sockets[1].sent_binary, [])

    def test_close_during_reconnect_stops_loop(self) -> None:
        sockets: list[_FakeWS] = []
        attempt_count = 0
        keep_failing: asyncio.Event = asyncio.Event()

        async def fake_connect(url: str, **kwargs: Any) -> _FakeWS:
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count >= 2:
                # Make every reconnect attempt fail so the loop spins
                # until close() trips it.
                if not keep_failing.is_set():
                    raise audio_mod.AudioStreamError("simulated outage")
            ws = _FakeWS(incoming=[json.dumps({"type": "ready", "session_key": "k", "codec": "pcm16"})])
            sockets.append(ws)
            return ws

        _patch_connect(fake_connect)

        async def run() -> None:
            opts = AudioStreamOptions(
                api_url="https://api.example.com",
                token="sk_wh_x",
                session_id="resume-me",
                codec="pcm16",
                sample_rate=16_000,
                auto_reconnect=True,
            )
            audio = AudioStreamSession(opts)
            await audio.connect()
            await sockets[0].close()
            await asyncio.sleep(0.05)
            # Calling close() while reconnect is looping must not raise
            # and must stop further attempts. (We don't assert the exact
            # attempt count because backoff timing is sensitive to host load.)
            await audio.close()

        asyncio.run(run())
        self.assertGreaterEqual(attempt_count, 2)


if __name__ == "__main__":
    unittest.main()
