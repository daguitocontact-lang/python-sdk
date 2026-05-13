<p align="center">
  <a href="https://daguito.com" target="_blank">
    <img src="https://raw.githubusercontent.com/daguitocontact-lang/daguito-python/main/assets/logo.png" alt="Daguito" width="160" />
  </a>
</p>

<h1 align="center">daguito (Python SDK)</h1>

<p align="center">
  Official Python SDK for the
  <a href="https://daguito.com">Daguito</a>
  conversational AI platform —
  text, voice, image, and multimodal agent flows.
</p>

<p align="center">
  <a href="https://pypi.org/project/daguito-sdk/"><img src="https://img.shields.io/pypi/v/daguito-sdk.svg?style=flat-square&color=0a0a0a" alt="pypi version" /></a>
  <a href="https://pypi.org/project/daguito-sdk/"><img src="https://img.shields.io/pypi/dm/daguito-sdk.svg?style=flat-square&color=0a0a0a" alt="pypi downloads" /></a>
  <a href="https://github.com/daguitocontact-lang/daguito-python/blob/main/LICENSE"><img src="https://img.shields.io/pypi/l/daguito-sdk.svg?style=flat-square&color=0a0a0a" alt="license" /></a>
  <a href="https://pypi.org/project/daguito-sdk/"><img src="https://img.shields.io/pypi/pyversions/daguito-sdk.svg?style=flat-square&color=0a0a0a" alt="python versions" /></a>
</p>

---

Async-first. Python 3.10+. Built on `httpx` + `websockets`. Type-hinted everywhere. Mirrors the [TypeScript SDK](https://github.com/daguitocontact-lang/js-sdk) feature-for-feature.

```bash
uv add daguito-sdk
# or
pip install daguito-sdk
```

> Package name is `daguito-sdk`. Import name is `daguito` — same pattern as `scikit-learn` / `sklearn`.

## What you get

- **`run_webhook()`** — one-shot HTTP call to a webhook flow. Wait, get the result.
- **`WebhookStreamSession`** — long-lived WebSocket for streaming flows. Token streaming, node lifecycle, custom emits. `async with`-friendly, plus `async for event in session.events()`.
- **`@session.tool(...)`** — register OpenAI-style tools the LLM can invoke. Your handler runs locally, its return value is fed back to the model as the tool result.
- **`scope={...}` on the session** — server-enforced metadata filter for KB searches. Isolates a conversation to its own ingested files without trusting the LLM with UUIDs.
- **`KnowledgeSession`** — Knowledge Base ingest + search over the same `sk_dgt_...` API key as the dashboard.
- **Typed event payloads** — every WS event is a dataclass (`NodeTokenEvent`, `FlowCompletedEvent`, etc.) so editors autocomplete attributes.

## Authentication

| Surface                  | Auth                  | Best for                                            |
| ------------------------ | --------------------- | --------------------------------------------------- |
| Webhook (`sk_wh_...`)    | Token issued per-flow | Server-to-server, FastAPI/Django backends, scripts  |
| Knowledge (`sk_dgt_...`) | Org-scoped API key    | Ingest + search against your own KB                 |

Create webhooks and API keys from your Daguito dashboard.

## Quick start

### One-shot webhook

```python
import asyncio
from daguito import run_webhook, WebhookRunInput

async def main():
    result = await run_webhook(WebhookRunInput(
        api_url="https://api.daguito.com",
        token="sk_wh_...",
        input={"question": "What is the price of BTC?"},
    ))
    print(result.output)

asyncio.run(main())
```

Need a synchronous flavor for scripts that aren't in an event loop? Use `run_webhook_sync`:

```python
from daguito import run_webhook_sync, WebhookRunInput
result = run_webhook_sync(WebhookRunInput(api_url=..., token=..., input={...}))
```

### Streaming webhook (text agent)

```python
import asyncio
from daguito import (
    WebhookStreamSession,
    WebhookStreamOptions,
    text_message,
)

async def main():
    opts = WebhookStreamOptions(
        api_url="https://api.daguito.com",
        webhook_id="wh_abc123",
        token="sk_wh_...",
    )
    async with WebhookStreamSession(opts) as session:
        await session.send(text_message("Hola, ¿qué tal?"))

        async for event_type, payload in session.events():
            if event_type == "node.token":
                print(payload.text, end="", flush=True)
            elif event_type == "node.completed":
                print(f"\n✓ {payload.node_id} ({payload.duration_ms}ms)")
            elif event_type == "flow.completed":
                print(f"\nDone in {payload.elapsed_ms}ms")
                break
            elif event_type == "flow.failed":
                print(f"\nFlow failed: {payload.error}")
                break

asyncio.run(main())
```

Prefer callbacks? You can also `session.on("node.token", listener)` like the JS SDK — but async iteration is the idiomatic Python pattern and plays nicely with FastAPI's `StreamingResponse`.

### Streaming with images

```python
from daguito import image_url_message, image_multi_message, media_key_message

# Hosted on a public URL (works on streaming-webhook surface)
await session.send(image_url_message(image_url="https://...", text="Describe this"))

# Multiple images
await session.send(image_multi_message(image_urls=[url1, url2], text="Compare"))

# Pre-uploaded (you handled the upload elsewhere)
await session.send(media_key_message(
    kind="image",
    media_key="media/.../abc.jpg",
    mime_type="image/jpeg",
    size_bytes=234_567,
))
```

> Need to upload a `File` directly from Python? Upload it through your own backend's presigned URL endpoint, then pass the `media_key` to `media_key_message()`. The streaming surface does not mint presigned URLs.

### Per-conversation scope (server-enforced KB filter)

When you ingest documents that belong to a specific conversation, patient, or workspace, you usually want the chat to only see chunks that match. Pass a `scope` on the session and Daguito **forces** every `search_knowledge_base` call to apply it as a metadata filter — server-side, before Milvus runs the search. The LLM never sees the scope values, so it can't accidentally widen the search, hallucinate a UUID, or leak data across conversations.

```python
import uuid
from daguito import (
    WebhookStreamSession,
    WebhookStreamOptions,
    KnowledgeSession,
    KnowledgeSessionOptions,
    IngestTextInput,
    text_message,
)

consultation_uuid = str(uuid.uuid4())

# 1. Ingest tagged with the scope key
async with KnowledgeSession(KnowledgeSessionOptions(...)) as kb:
    await kb.ingest_text(IngestTextInput(
        text=lab_results_text,
        metadata={"consultation_uuid": consultation_uuid, "kind": "lab"},
    ))

# 2. Open the chat scoped to that consultation
opts = WebhookStreamOptions(
    api_url="https://api.daguito.com",
    webhook_id="wh_abc123",
    token="sk_wh_...",
    scope={"consultation_uuid": consultation_uuid},
)

async with WebhookStreamSession(opts) as session:
    await session.send(text_message("¿Cómo están las bilirrubinas?"))
    # → search_knowledge_base is forced to filter by consultation_uuid
    # → the LLM can't see chunks from other consultations
```

Scope values must be primitives (`str`, `int`, `float`, `bool`). You can stack multiple keys at once (`{"consultation_uuid": "...", "tenant_id": "..."}`) — every search is filtered by all of them.

The LLM can still pass its own `metadata_filter` (e.g. to narrow by `document_type`), but **server scope always wins on key conflict** — a hallucinated value can't widen the result set.

### Client-side tools (OpenAI-style function calling)

Register tools that the LLM can invoke during a session. Your Python handler
runs locally, and its return value is fed back to the model as the tool
result — so the LLM continues its reply with the actual data your code
produced, not a placeholder.

```python
import asyncio
from daguito import (
    WebhookStreamSession,
    WebhookStreamOptions,
    text_message,
)

async def main():
    opts = WebhookStreamOptions(
        api_url="https://api.daguito.com",
        webhook_id="wh_abc123",
        token="sk_wh_...",
    )
    async with WebhookStreamSession(opts) as session:

        @session.tool(
            name="update_soap_section",
            description="Updates a SOAP section with new clinical information.",
            parameters={
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": ["subjective", "objective", "assessment", "plan"],
                    },
                    "subsection": {"type": "string"},
                    "content": {"type": "string"},
                    "action": {
                        "type": "string",
                        "enum": ["add", "update", "append"],
                    },
                },
                "required": ["section", "subsection", "content", "action"],
            },
        )
        async def update_soap(args: dict) -> dict:
            # Run your business logic here — write to your DB, call an API,
            # whatever. The returned value goes back to the LLM as the
            # tool result.
            soap_id = await db.update_soap(args)
            return {"success": True, "soap_id": soap_id}

        await session.send(text_message(
            "Add this to the plan: paracetamol 500mg every 8 hours for 5 days."
        ))

        async for event_type, payload in session.events():
            if event_type == "node.token":
                print(payload.text, end="", flush=True)
            elif event_type == "flow.completed":
                break

asyncio.run(main())
```

Tools follow the **exact same shape as OpenAI function calling**
(`name`, `description`, `parameters` as a JSON Schema). They're sent to the
flow on every turn via `base_input.client_tools`, merged with whatever
tools the flow already declared statically, and the LLM picks the best
one for the job.

The handler can be sync or async. Throw an exception to surface a failure
to the LLM with a typed error.

### Knowledge Search

```python
from daguito import (
    KnowledgeSession,
    KnowledgeSessionOptions,
    IngestTextInput,
    SearchInput,
)

opts = KnowledgeSessionOptions(
    api_url="https://api.daguito.com",
    api_key="sk_dgt_...",
    default_source_id="src_abc123",
)

async with KnowledgeSession(opts) as kb:
    # Ingest text — chunks + embeds + indexes server-side
    await kb.ingest_text(IngestTextInput(
        text="MacBook Pro M4 Max with 64GB RAM...",
        metadata={"category": "laptop", "price_usd": 3499},
    ))

    # Search — vector + keyword hybrid
    result = await kb.search(SearchInput(query="laptops para video", top_k=3))
    for hit in result.hits:
        print(hit.score, hit.content, hit.metadata)
```

The `api_key` controls scopes. Mint one from the dashboard with `kb:read` and/or `kb:write` actions, optionally limited to specific KBs.

## FastAPI streaming example

Stream tokens from a Daguito flow straight to the browser via Server-Sent Events:

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from daguito import WebhookStreamSession, WebhookStreamOptions, text_message

app = FastAPI()

@app.post("/chat")
async def chat(message: str):
    async def event_stream():
        async with WebhookStreamSession(WebhookStreamOptions(
            api_url="https://api.daguito.com",
            webhook_id="wh_abc123",
            token="sk_wh_...",
        )) as session:
            await session.send(text_message(message))

            async for event_type, payload in session.events():
                if event_type == "node.token":
                    yield f"data: {payload.text}\n\n"
                elif event_type == "node.emit" and payload.kind == "tool_call":
                    # The agent invoked a tool the client owns. Forward it so
                    # the frontend (or this backend) can execute it locally.
                    yield f"event: tool_call\ndata: {payload.data}\n\n"
                elif event_type == "flow.completed":
                    yield "event: done\ndata: ok\n\n"
                    return

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

## Runtime support

| Module    | Python 3.10+ | asyncio | Notes                                       |
| --------- | ------------ | ------- | ------------------------------------------- |
| `daguito` | ✅           | ✅      | `httpx` + `websockets`. No native deps.     |

Works on **CPython** and **PyPy**. Plays well with FastAPI, Starlette, aiohttp, Django Channels, anyio-based stacks, and any async runtime. The synchronous `run_webhook_sync()` helper is provided for scripts and Jupyter notebooks that don't have a running event loop.

## Event reference

### `WebhookStreamSession` events

| Event            | Payload class         | When                          |
| ---------------- | --------------------- | ----------------------------- |
| `ready`          | `ReadyEvent`          | Socket authenticated          |
| `closed`         | `ClosedEvent`         | Transport closed              |
| `node.started`   | `NodeStartedEvent`    | Engine entered a node         |
| `node.token`     | `NodeTokenEvent`      | LLM streaming token           |
| `node.completed` | `NodeCompletedEvent`  | Node finished                 |
| `node.failed`    | `NodeFailedEvent`     | Node errored                  |
| `node.emit`      | `NodeEmitEvent`       | Custom telemetry from a node  |
| `flow.completed` | `FlowCompletedEvent`  | Engine finished               |
| `flow.failed`    | `FlowFailedEvent`     | Engine errored                |
| `error`          | `ErrorEvent`          | Protocol-level error          |

Each payload is a Python dataclass — fields are typed, so editors autocomplete and type checkers catch typos.

## Multimodal cheat sheet

| Modality                        | Webhook stream            | Knowledge ingest                |
| ------------------------------- | ------------------------- | ------------------------------- |
| `text`                          | ✅                        | ✅ (`ingest_text`)              |
| `image` (URL)                   | ✅ (`image_url_message`)  | extract OCR text first          |
| `image` (pre-uploaded mediaKey) | ✅ (`media_key_message`)  | —                               |
| `image-multi`                   | ✅                        | —                               |
| `audio` (mediaKey)              | ✅                        | transcribe first, ingest text   |
| `document` (mediaKey)           | ✅                        | extract text first, ingest text |
| `form-response`                 | ✅                        | —                               |
| Knowledge Base search           | ✅ via flow tool          | ✅ (`KnowledgeSession.search`)  |

The Python SDK does not handle file extraction (PDF → text, image → OCR, audio → transcript). Use whatever tool fits your stack (Azure Document Intelligence, AssemblyAI, Tesseract, etc.) and feed the resulting text into `KnowledgeSession.ingest_text()`. The Daguito flow's `search_knowledge_base` tool then surfaces it to the model.

## Testing from a script

The fastest way to verify your install works is to point the streaming session at any flow and dump events to stdout:

```python
import asyncio
import os
from daguito import WebhookStreamSession, WebhookStreamOptions, text_message

async def main():
    opts = WebhookStreamOptions(
        api_url=os.environ["DAGUITO_API_URL"],
        webhook_id=os.environ["DAGUITO_WEBHOOK_ID"],
        token=os.environ["DAGUITO_WEBHOOK_TOKEN"],
    )
    async with WebhookStreamSession(opts) as session:
        await session.send(text_message("ping"))
        async for event_type, payload in session.events():
            print(event_type, payload)
            if event_type in ("flow.completed", "flow.failed"):
                break

asyncio.run(main())
```

```bash
DAGUITO_API_URL=https://api.daguito.com \
DAGUITO_WEBHOOK_ID=wh_abc123 \
DAGUITO_WEBHOOK_TOKEN=sk_wh_... \
python smoke.py
```

## Typing

Every public symbol has full type hints, including the dataclass payloads emitted by streaming events. The package ships a `py.typed` marker so `mypy` / `pyright` pick the types up automatically.

```python
from daguito import (
    WebhookStreamSession,
    WebhookStreamOptions,
    NodeTokenEvent,
    FlowCompletedEvent,
)
```

## Resources

- 🌐 [daguito.com](https://daguito.com) — landing & dashboard
- 📚 [docs.daguito.com](https://docs.daguito.com) — full API and flow reference
- 💬 [TypeScript SDK](https://github.com/daguitocontact-lang/js-sdk) — same surface, different runtime
- 🐛 [Issues](https://github.com/daguitocontact-lang/daguito-python/issues) — bug reports & feature requests
- 📦 [Source](https://github.com/daguitocontact-lang/daguito-python) — Python SDK repo

## License

MIT © [Daguito, LLC](https://daguito.com)
