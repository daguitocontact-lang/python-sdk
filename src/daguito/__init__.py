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

from ._admin_http import DaguitoError
from .admin_account_keys import AccountKeysService
from .admin_budgets import BudgetsService
from .admin_flows import FlowsService, ResolvedFlowWebhook
from .admin_public_keys import PublicKeysService
from .admin_types import (
    AccountKey,
    AccountKeyCreated,
    OrgBudget,
    PublicKey,
    PublicKeyCreated,
)
from .client import Daguito
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
    ToolProgressEvent,
    ToolProgressResource,
    WebhookStreamOptions,
    form_response_message,
    image_multi_message,
    image_url_message,
    media_key_message,
    parse_tool_progress,
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
from .audio_stream_session import (
    AudioStreamError,
    AudioStreamOptions,
    AudioStreamReady,
    AudioStreamSession,
    SUPPORTED_CODECS,
)
from .upload import UploadError, UploadInput, UploadKind, UploadResult, upload_file

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
    # audio upstream (PCM/opus chunks → Daguito → STT internal)
    "AudioStreamSession",
    "AudioStreamOptions",
    "AudioStreamReady",
    "AudioStreamError",
    "SUPPORTED_CODECS",
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
    "ToolProgressEvent",
    "ToolProgressResource",
    "parse_tool_progress",
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
    # upload (presigned PUT for media attachments — mirrors run_webhook shape)
    "upload_file",
    "UploadInput",
    "UploadResult",
    "UploadError",
    "UploadKind",
    # event emitter
    "Emitter",
    "Listener",
    # admin client (programmatic key + budget management)
    "Daguito",
    "DaguitoError",
    "AccountKey",
    "AccountKeyCreated",
    "PublicKey",
    "PublicKeyCreated",
    "OrgBudget",
    "AccountKeysService",
    "PublicKeysService",
    "BudgetsService",
    "FlowsService",
    "ResolvedFlowWebhook",
]

__version__ = "0.3.11"
