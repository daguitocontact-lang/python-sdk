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


if __name__ == "__main__":
    unittest.main()
