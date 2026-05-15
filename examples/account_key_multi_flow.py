"""Drive three different flows from one `dgsk_acc_` account key.

Before this rollout, each flow needed its own `sk_wh_*` token, so a
real backend ended up juggling N env vars. With an account key the
SDK accepts the same string for every flow — the server routes by
`webhook_id` (or `source_id` for KB calls).

Run:

    DAGUITO_API_URL=https://api.daguito.com \\
    DAGUITO_API_KEY=dgsk_acc_xxxxxxxxxxxx \\
    DAGUITO_FLOW_CHATBOT=wh_chatbot_123 \\
    DAGUITO_FLOW_TRANSCRIBE=wh_transcribe_456 \\
    DAGUITO_KB_SOURCE=src_docs_789 \\
    python examples/account_key_multi_flow.py
"""

from __future__ import annotations

import asyncio
import os

from daguito import (
    IngestTextInput,
    KnowledgeSession,
    KnowledgeSessionOptions,
    WebhookRunInput,
    WebhookStreamOptions,
    WebhookStreamSession,
    run_webhook,
    text_message,
)


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"missing env var: {name}")
    return value


async def one_shot(api_url: str, api_key: str, flow_id: str) -> None:
    print(f"[one-shot] flow={flow_id}")
    result = await run_webhook(WebhookRunInput(
        api_url=api_url,
        token=api_key,
        input={"webhook_id": flow_id, "question": "Summarize the latest release notes."},
    ))
    print(f"           status={result.status} output={result.output}\n")


async def streaming(api_url: str, api_key: str, flow_id: str) -> None:
    print(f"[stream]   flow={flow_id}")
    opts = WebhookStreamOptions(api_url=api_url, webhook_id=flow_id, token=api_key)
    async with WebhookStreamSession(opts) as session:
        await session.send(text_message("Transcribe and tag the meeting."))
        async for event_type, payload in session.events():
            if event_type == "node.token":
                print(payload.text, end="", flush=True)
            elif event_type in ("flow.completed", "flow.failed"):
                print()
                break
    print()


async def kb_ingest(api_url: str, api_key: str, source_id: str) -> None:
    print(f"[kb]       source={source_id}")
    opts = KnowledgeSessionOptions(api_url=api_url, api_key=api_key, default_source_id=source_id)
    async with KnowledgeSession(opts) as kb:
        result = await kb.ingest_text(IngestTextInput(
            text="Daguito account keys grant access to every flow in the org.",
            metadata={"topic": "auth"},
        ))
        print(f"           chunks={result.chunk_count} tokens={result.token_count}\n")


async def main() -> None:
    api_url = os.environ.get("DAGUITO_API_URL", "https://api.daguito.com")
    api_key = env("DAGUITO_API_KEY")
    chatbot = env("DAGUITO_FLOW_CHATBOT")
    transcribe = env("DAGUITO_FLOW_TRANSCRIBE")
    kb_source = env("DAGUITO_KB_SOURCE")

    await one_shot(api_url, api_key, chatbot)
    await streaming(api_url, api_key, transcribe)
    await kb_ingest(api_url, api_key, kb_source)


if __name__ == "__main__":
    asyncio.run(main())
