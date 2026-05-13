# daguito

Official Python SDK for the **Daguito** conversational AI platform — streaming webhooks, one-shot flows, and Knowledge Base (RAG) ingest/search.

Async-first (built on `httpx` + `websockets`). Mirrors `@daguito/sdk` (TypeScript) feature-for-feature.

## Install

```bash
uv add daguito
# or
pip install daguito
```

## Quick start

### 1. Streaming chatbot (WebSocket)

```python
from daguito import WebhookStreamSession, WebhookStreamOptions, text_message

async with WebhookStreamSession(
    WebhookStreamOptions(
        api_url="https://api.daguito.com",
        webhook_id="wh_xxx",
        token="sk_wh_xxx",
    )
) as session:
    await session.send(text_message("¿Cómo bajo la presión arterial?"))

    async for event_type, payload in session.events():
        if event_type == "node.token":
            print(payload.text, end="", flush=True)
        elif event_type == "flow.completed":
            break
```

### 2. One-shot HTTP webhook

```python
from daguito import run_webhook, WebhookRunInput

result = await run_webhook(WebhookRunInput(
    api_url="https://api.daguito.com",
    token="sk_wh_xxx",
    input={"text": "necesito un abogado de familia en Bogotá"},
    timeout_seconds=90,
))

print(result.output)
```

### 3. Knowledge Base ingest + search

```python
from daguito import (
    KnowledgeSession,
    KnowledgeSessionOptions,
    IngestTextInput,
    SearchInput,
)

opts = KnowledgeSessionOptions(
    api_url="https://api.daguito.com",
    api_key="sk_dgt_xxx",
    default_source_id="src_xxx",
)

async with KnowledgeSession(opts) as kb:
    await kb.ingest_text(IngestTextInput(
        text="El paracetamol es un analgésico común…",
        metadata={"category": "medications"},
    ))

    result = await kb.search(SearchInput(query="dolor de cabeza", top_k=5))
    for hit in result.hits:
        print(hit.score, hit.content[:80])
```

## FastAPI streaming example

Stream tokens from Daguito to the browser via Server-Sent Events:

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
            webhook_id="wh_xxx",
            token="sk_wh_xxx",
        )) as session:
            await session.send(text_message(message))
            async for event_type, payload in session.events():
                if event_type == "node.token":
                    yield f"data: {payload.text}\n\n"
                elif event_type == "flow.completed":
                    yield "data: [DONE]\n\n"
                    return

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

## Event types

`WebhookStreamSession.events()` yields tuples of `(event_type, payload)`:

| Event             | Payload class           | Description                                     |
|-------------------|------------------------|-------------------------------------------------|
| `ready`           | `ReadyEvent`           | Socket opened and authenticated                  |
| `node.started`    | `NodeStartedEvent`     | A flow node started executing                    |
| `node.token`      | `NodeTokenEvent`       | LLM produced a token — append `payload.text`     |
| `node.completed`  | `NodeCompletedEvent`   | A node finished (with optional `duration_ms`)    |
| `node.failed`     | `NodeFailedEvent`      | A node failed (`payload.error` describes why)    |
| `node.emit`       | `NodeEmitEvent`        | Custom node telemetry                            |
| `flow.completed`  | `FlowCompletedEvent`   | The whole flow finished                          |
| `flow.failed`     | `FlowFailedEvent`      | The flow failed at top level                     |
| `closed`          | `ClosedEvent`          | Socket closed                                    |
| `error`           | `ErrorEvent`           | Auth/protocol error                              |

## License

MIT — see `LICENSE` file.
