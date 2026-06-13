<p align="center">
  <a href="https://daguito.com" target="_blank">
    <img src="https://raw.githubusercontent.com/daguitocontact-lang/python-sdk/main/assets/logo.png" alt="Daguito" width="160" />
  </a>
</p>

<h1 align="center">daguito (Python SDK)</h1>

<p align="center">
  Official Python SDK for the
  <a href="https://daguito.com">Daguito</a>
  conversational AI platform — text, voice, image, audio, document and video agent flows.
</p>

<p align="center">
  <a href="https://pypi.org/project/daguito-sdk/"><img src="https://img.shields.io/pypi/v/daguito-sdk.svg?style=flat-square&color=0a0a0a" alt="pypi version" /></a>
  <a href="https://pypi.org/project/daguito-sdk/"><img src="https://img.shields.io/pypi/dm/daguito-sdk.svg?style=flat-square&color=0a0a0a" alt="pypi downloads" /></a>
  <a href="https://github.com/daguitocontact-lang/python-sdk/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/daguito-sdk.svg?style=flat-square&color=0a0a0a" alt="license" /></a>
  <a href="https://pypi.org/project/daguito-sdk/"><img src="https://img.shields.io/pypi/pyversions/daguito-sdk.svg?style=flat-square&color=0a0a0a" alt="python versions" /></a>
</p>

---

Async-first, Python 3.10+, built on `httpx` + `websockets`. Fully type-hinted. Mirrors the [TypeScript SDK](https://github.com/daguitocontact-lang/js-sdk) feature-for-feature.

```bash
uv add daguito-sdk
# or
pip install daguito-sdk
```

> Package name is `daguito-sdk`. Import name is `daguito` (same pattern as `scikit-learn` / `sklearn`).

## What's in the box

| Symbol                      | Use it for                                                              |
| --------------------------- | ----------------------------------------------------------------------- |
| `run_webhook()`             | One-shot HTTP call to a flow. Wait, get the result.                     |
| `WebhookStreamSession`      | Long-lived WebSocket. Streams tokens, node lifecycle, custom emits.     |
| `upload_file()`             | Presigned upload for image / audio / document / video attachments.     |
| `@session.tool(...)`        | Register OpenAI-style function tools the LLM can invoke on your code.   |
| `session.scope = {...}`     | Server-enforced metadata filter for KB searches (data isolation).       |
| `KnowledgeSession`          | Ingest + search a Knowledge Base with a `sk_dgt_...` org key.           |

Every WebSocket event is a typed dataclass (`NodeTokenEvent`, `FlowCompletedEvent`, `ToolProgressEvent`, …) so editors autocomplete.

## Authentication

| Surface                  | Key shape       | Best for                                        |
| ------------------------ | --------------- | ----------------------------------------------- |
| Webhook                  | `sk_wh_...`     | Server-to-server, your own backend, scripts     |
| Knowledge Base           | `sk_dgt_...`    | Ingest + search against your own KB             |

Create both from the Daguito dashboard.

## Quick start

### One-shot webhook

```python
import asyncio
from daguito import run_webhook, WebhookRunInput

async def main():
    result = await run_webhook(WebhookRunInput(
        api_url="https://ingest.daguito.com",
        token="sk_wh_...",
        input={"question": "What is the capital of France?"},
    ))
    print(result.output)

asyncio.run(main())
```

Need a sync flavor (scripts, Jupyter)? `run_webhook_sync(...)` has the same signature.

### Streaming a chat agent

```python
import asyncio
from daguito import WebhookStreamSession, WebhookStreamOptions, text_message

async def main():
    opts = WebhookStreamOptions(
        api_url="https://ingest.daguito.com",
        webhook_id="wh_abc123",
        token="sk_wh_...",
    )
    async with WebhookStreamSession(opts) as session:
        await session.send(text_message("Hello!"))

        async for event_type, payload in session.events():
            if event_type == "node.token":
                print(payload.text, end="", flush=True)
            elif event_type == "flow.completed":
                break
            elif event_type == "flow.failed":
                print(f"\nfailed: {payload.error}")
                break

asyncio.run(main())
```

Prefer callbacks? `session.on("node.token", listener)` also works. Async iteration is the idiomatic Python pattern and slots into FastAPI's `StreamingResponse`.

### Sending attachments

Two paths — pick whichever fits your stack.

**Pre-uploaded media key** (you handle the upload yourself, or use `upload_file()`):

```python
from daguito import upload_file, UploadInput, media_key_message

uploaded = await upload_file(UploadInput(
    api_url="https://ingest.daguito.com",
    webhook_id="wh_abc123",
    token="sk_wh_...",
    kind="document",         # "image" | "audio" | "document" | "video"
    path="/tmp/report.pdf",
))

await session.send(media_key_message(
    kind="document",
    media_key=uploaded.media_key,
    mime_type="application/pdf",
    size_bytes=uploaded.size_bytes,
    text="Summarize this report",
))
```

**Public image URL** (no upload, fastest path):

```python
from daguito import image_url_message, image_multi_message

await session.send(image_url_message(
    image_url="https://example.com/photo.jpg",
    text="What's in this image?",
))

await session.send(image_multi_message(
    image_urls=["https://example.com/a.jpg", "https://example.com/b.jpg"],
    text="Compare these two",
))
```

Video and audio are handled the same way as document — upload, then `media_key_message(kind="video", ...)`. The backend extracts a transcript and visual highlights and surfaces them to the agent automatically.

### Per-session scope (server-enforced KB filter)

When your KB holds data for many users / workspaces / documents, you want each chat to only see chunks tagged with the right key. Set `scope` on the session — Daguito **forces** every KB search the agent makes to apply it as a metadata filter, server-side. The LLM never sees the values, so it can't widen the search or leak across tenants.

```python
from daguito import WebhookStreamOptions, WebhookStreamSession, text_message

opts = WebhookStreamOptions(
    api_url="https://ingest.daguito.com",
    webhook_id="wh_abc123",
    token="sk_wh_...",
    scope={"workspace_id": "ws_42", "document_id": "doc_abc"},
)

async with WebhookStreamSession(opts) as session:
    await session.send(text_message("What does the document say about X?"))
```

Make sure your ingest writes the same keys into `metadata` — that's the join. Scope values must be primitives (`str`, `int`, `float`, `bool`).

### Client-side tools (function calling)

Tools you register on the session run locally — Python code, in your process — and their return value is fed back to the LLM as the tool result. Same shape as OpenAI function calling.

```python
@session.tool(
    name="get_weather",
    description="Get the current weather for a city.",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string"},
            "units": {"type": "string", "enum": ["c", "f"]},
        },
        "required": ["city"],
    },
)
async def get_weather(args: dict) -> dict:
    data = await my_weather_api.fetch(args["city"], args.get("units", "c"))
    return {"temp": data.temp, "conditions": data.summary}
```

Handler can be sync or async. Raise an exception to surface a failure to the LLM. Tools are merged with whatever the flow already declares server-side — the LLM picks the best fit.

### Tool progress events (data-only)

When a server-side tool runs (KB search, media analysis, web search), the engine emits `tool_progress` events. They're **data-only** — no localized strings — so your client renders whatever copy/UI you want.

```python
from daguito import parse_tool_progress

async for event_type, payload in session.events():
    if event_type == "node.emit":
        progress = parse_tool_progress(payload)
        if progress:
            print(f"[{progress.tool}] {progress.stage}", progress.resource)
```

`progress.tool`, `progress.stage`, `progress.resource`, `progress.result`, `progress.trace_id`, `progress.attempt` — render however you like.

### Knowledge Base

```python
from daguito import (
    KnowledgeSession, KnowledgeSessionOptions, IngestTextInput, SearchInput,
)

opts = KnowledgeSessionOptions(
    api_url="https://ingest.daguito.com",
    api_key="sk_dgt_...",
    default_source_id="src_abc123",
)

async with KnowledgeSession(opts) as kb:
    await kb.ingest_text(IngestTextInput(
        text="Daguito is a conversational AI platform...",
        metadata={"workspace_id": "ws_42", "kind": "doc"},
    ))

    result = await kb.search(SearchInput(query="what is daguito", top_k=5))
    for hit in result.hits:
        print(hit.score, hit.content)
```

The `api_key` controls scopes (`kb:read`, `kb:write`). Mint one in the dashboard and optionally restrict to specific KBs.

## FastAPI streaming (SSE)

Stream tokens from a Daguito flow straight to the browser:

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from daguito import WebhookStreamSession, WebhookStreamOptions, text_message

app = FastAPI()

@app.post("/chat")
async def chat(message: str):
    async def event_stream():
        async with WebhookStreamSession(WebhookStreamOptions(
            api_url="https://ingest.daguito.com",
            webhook_id="wh_abc123",
            token="sk_wh_...",
        )) as session:
            await session.send(text_message(message))
            async for event_type, payload in session.events():
                if event_type == "node.token":
                    yield f"data: {payload.text}\n\n"
                elif event_type == "flow.completed":
                    yield "event: done\ndata: ok\n\n"
                    return

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

## Event reference

| Event            | Payload class         | When                          |
| ---------------- | --------------------- | ----------------------------- |
| `ready`          | `ReadyEvent`          | Socket authenticated          |
| `closed`         | `ClosedEvent`         | Transport closed              |
| `node.started`   | `NodeStartedEvent`    | Engine entered a node         |
| `node.token`     | `NodeTokenEvent`      | LLM streaming token           |
| `node.completed` | `NodeCompletedEvent`  | Node finished                 |
| `node.failed`    | `NodeFailedEvent`     | Node errored                  |
| `node.emit`      | `NodeEmitEvent`       | Custom telemetry (tool progress, intent emits, …) |
| `flow.completed` | `FlowCompletedEvent`  | Engine finished               |
| `flow.failed`    | `FlowFailedEvent`     | Engine errored                |
| `error`          | `ErrorEvent`          | Protocol-level error          |

Every payload is a dataclass — fields are typed, so `mypy` / `pyright` catch typos.

## Modality support

| Modality                       | Streaming session                       | Knowledge ingest                 |
| ------------------------------ | --------------------------------------- | -------------------------------- |
| Text                           | `text_message(...)`                     | `ingest_text(...)`               |
| Image (public URL)             | `image_url_message(...)`                | extract text first               |
| Image (uploaded)               | `media_key_message(kind="image", ...)`  | extract text first               |
| Audio                          | `media_key_message(kind="audio", ...)`  | transcribe first, ingest text    |
| Document                       | `media_key_message(kind="document", ...)`| extract text first, ingest text |
| Video                          | `media_key_message(kind="video", ...)`  | extract transcript + scenes      |
| Form response                  | `form_response_message(...)`            | —                                |
| Knowledge Base search          | server-side tool the LLM calls          | `KnowledgeSession.search(...)`   |

## Runtime support

| Module    | Python 3.10+ | asyncio | Notes                                  |
| --------- | ------------ | ------- | -------------------------------------- |
| `daguito` | ✅           | ✅      | `httpx` + `websockets`. No native deps |

Works on CPython and PyPy. Plays well with FastAPI, Starlette, aiohttp, Django Channels, anyio-based stacks. The `run_webhook_sync()` helper covers scripts and notebooks without an event loop.

## Typing

Every public symbol has full type hints. The package ships a `py.typed` marker so `mypy` and `pyright` pick everything up automatically.

```python
from daguito import (
    WebhookStreamSession, WebhookStreamOptions,
    NodeTokenEvent, FlowCompletedEvent, ToolProgressEvent,
)
```

## Resources

- 🌐 [daguito.com](https://daguito.com) — landing & dashboard
- 📚 [docs.daguito.com](https://docs.daguito.com) — full API + flow reference
- 💬 [TypeScript SDK](https://github.com/daguitocontact-lang/js-sdk) — same surface, different runtime
- 🐛 [Issues](https://github.com/daguitocontact-lang/python-sdk/issues)
- 📦 [Source](https://github.com/daguitocontact-lang/python-sdk)

## License

MIT © [Daguito, LLC](https://daguito.com)
