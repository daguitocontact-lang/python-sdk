"""Audio bridge example — push PCM chunks to Daguito and consume flow events.

This is the shape you want for a thin "WebRTC → PCM → Daguito" service
(e.g. midulabs-ai). Two long-lived sessions run concurrently against the
same `session_id`:

  1) `AudioStreamSession`  → upstream, binary frames (PCM/opus/etc.).
  2) `WebhookStreamSession` → downstream, transcript + collect_data events
                              emitted by the flow's `a_transcribe_stream`
                              and `collect_data` (mode=streaming) nodes.

The flow on the server side is expected to look roughly like:

  trigger: webhook (streaming)
  ↓
  a_transcribe_stream  (memory_key="transcript", mode="await_final" or
                        "spawn" with spawn_per_final=True)
  ↓
  collect_data  (mode="streaming", streaming.source_field="transcript")

Run:

    DAGUITO_API_URL=https://ingest.daguito.com \\
    DAGUITO_WEBHOOK_ID=wh_… \\
    DAGUITO_TOKEN=sk_wh_… \\
    python examples/audio_bridge.py path/to/audio.pcm
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import daguito


CHUNK_SIZE = 3_200  # 100 ms of pcm16 mono @ 16kHz = 3200 bytes


async def pump_audio(audio: daguito.AudioStreamSession, source: Path) -> None:
    """Read 100 ms PCM chunks off disk and push them to Daguito. Replace
    this with your WebRTC track reader in production."""
    with source.open("rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            await audio.send_audio(chunk)
            # Real audio arrives at wall-clock pace; pretending to be live
            # keeps the STT provider's session healthy and avoids piling up
            # frames the server has to drain in a burst.
            await asyncio.sleep(0.1)


async def consume_events(stream: daguito.WebhookStreamSession) -> None:
    """Receive transcript + collect_data events and route them to your
    domain logic (DB write, websocket broadcast to a doctor's UI, etc.)."""
    async for event_type, payload in stream.events():
        if event_type == "node.emit":
            kind = getattr(payload, "kind", None) or payload.get("kind")  # type: ignore[union-attr]
            if kind == "transcript.partial":
                # live transcript chunk
                print(f"[partial] {getattr(payload, 'text', '') or payload.get('text', '')}")
            elif kind == "transcript.final":
                print(f"[final  ] {getattr(payload, 'text', '') or payload.get('text', '')}")
            elif kind == "collect_data.streaming_update":
                changes = (
                    getattr(payload, "changes", None)
                    or (payload.get("changes") if isinstance(payload, dict) else {})
                )
                version = (
                    getattr(payload, "version", None)
                    or (payload.get("version") if isinstance(payload, dict) else 0)
                )
                print(f"[extract v{version}] {changes}")
            elif kind == "collect_data.streaming_skip":
                # debounce skip — not an error
                pass
        elif event_type == "flow.completed":
            print("[done]")
            break


async def main() -> None:
    api_url = os.environ["DAGUITO_API_URL"]
    webhook_id = os.environ["DAGUITO_WEBHOOK_ID"]
    token = os.environ["DAGUITO_TOKEN"]
    session_id = os.environ.get("SESSION_ID") or f"bridge_{os.getpid()}"
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "consult.pcm16")
    if not source.exists():
        raise SystemExit(f"audio source not found: {source}")

    audio_opts = daguito.AudioStreamOptions(
        api_url=api_url,
        token=token,
        session_id=session_id,
        codec="pcm16",
        sample_rate=16_000,
    )
    stream_opts = daguito.WebhookStreamOptions(
        api_url=api_url,
        webhook_id=webhook_id,
        token=token,
        session_key=session_id,
        scope={"consultation_uuid": session_id},
    )

    async with (
        daguito.AudioStreamSession(audio_opts) as audio,
        daguito.WebhookStreamSession(stream_opts) as stream,
    ):
        await asyncio.gather(
            pump_audio(audio, source),
            consume_events(stream),
        )


if __name__ == "__main__":
    asyncio.run(main())
