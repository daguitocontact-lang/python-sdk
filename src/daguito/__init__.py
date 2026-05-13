"""daguito — Official Python SDK for the Daguito conversational AI platform.

Quick start:

    # One-shot HTTP webhook
    from daguito import run_webhook, WebhookRunInput
    result = await run_webhook(WebhookRunInput(api_url="...", token="sk_wh_..."))

    # Streaming WebSocket webhook
    from daguito import WebhookStreamSession, WebhookStreamOptions, text_message
    async with WebhookStreamSession(WebhookStreamOptions(...)) as session:
        await session.send(text_message("hola"))
        async for event_type, payload in session.events():
            if event_type == "node.token":
                print(payload.text, end="")
            elif event_type == "flow.completed":
                break

    # Knowledge base ingest + search
    from daguito import KnowledgeSession, KnowledgeSessionOptions, IngestTextInput
    async with KnowledgeSession(KnowledgeSessionOptions(...)) as kb:
        await kb.ingest_text(IngestTextInput(text="..."))

Public surface mirrors @daguito/sdk (TypeScript). See README.md for details.
"""

from __future__ import annotations

from .emitter import Emitter, Listener
from .knowledge_session import (
    IngestTextInput,
    IngestTextResult,
    KnowledgeError,
    KnowledgeSession,
    KnowledgeSessionOptions,
    SearchHit,
    SearchInput,
    SearchResult,
)
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
    form_response_message,
    image_multi_message,
    image_url_message,
    media_key_message,
    text_message,
)
from .webhook_session import (
    WebhookError,
    WebhookRunInput,
    WebhookRunResult,
    run_webhook,
    run_webhook_sync,
)
from .webhook_stream_session import WebhookStreamSession

__all__ = [
    # one-shot
    "run_webhook",
    "run_webhook_sync",
    "WebhookRunInput",
    "WebhookRunResult",
    "WebhookError",
    # streaming
    "WebhookStreamSession",
    "WebhookStreamOptions",
    # messages
    "text_message",
    "image_url_message",
    "image_multi_message",
    "media_key_message",
    "form_response_message",
    # event payloads
    "ReadyEvent",
    "ClosedEvent",
    "NodeTokenEvent",
    "NodeStartedEvent",
    "NodeCompletedEvent",
    "NodeFailedEvent",
    "NodeEmitEvent",
    "FlowCompletedEvent",
    "FlowFailedEvent",
    "ErrorEvent",
    # knowledge
    "KnowledgeSession",
    "KnowledgeSessionOptions",
    "IngestTextInput",
    "IngestTextResult",
    "SearchInput",
    "SearchHit",
    "SearchResult",
    "KnowledgeError",
    # event emitter
    "Emitter",
    "Listener",
]

__version__ = "0.3.2"
