"""Integration tests for the Daguito Python SDK.

These tests hit a real local API instance (`api-local.daguito.com` by
default) using a real account/dgsk_dgt key. If the env vars aren't set,
the suite is skipped so it doesn't break CI/contributors who only run
the offline tests.

Required env vars (also have safe defaults pointing at the local dev
stack):

    DAGUITO_API_URL   default: https://api-local.daguito.com
    DAGUITO_API_KEY   required — `sk_dgt_…` or `dgsk_acc_…`
    DAGUITO_KB_SOURCE_ID  optional — used to assert list_sources sees
                           a known row. Defaults to the dev seed
                           `a63fa3c1-63b1-4c09-92df-9599ba44f68c`.

Run with:

    cd sdks/python && uv run pytest tests/test_integration.py -v
"""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from daguito import (
    AgentFlowSpec,
    Daguito,
    DaguitoError,
)

DEFAULT_API_URL = "https://api-local.daguito.com"
DEFAULT_KB_SOURCE_ID = "a63fa3c1-63b1-4c09-92df-9599ba44f68c"


def _env_or_skip() -> tuple[str, str, str]:
    api_url = os.environ.get("DAGUITO_API_URL") or DEFAULT_API_URL
    api_key = os.environ.get("DAGUITO_API_KEY")
    kb_source = os.environ.get("DAGUITO_KB_SOURCE_ID") or DEFAULT_KB_SOURCE_ID
    if not api_key:
        pytest.skip("DAGUITO_API_KEY not set — integration suite needs a real key")
    return api_url, api_key, kb_source


@pytest_asyncio.fixture
async def client() -> AsyncIterator[Daguito]:
    api_url, api_key, _ = _env_or_skip()
    yield Daguito(api_url=api_url, api_key=api_key)


@pytest_asyncio.fixture
def kb_source_id() -> str:
    _, _, kb_source = _env_or_skip()
    return kb_source


@pytest.mark.asyncio
async def test_upsert_agent_is_idempotent_and_resolvable(client: Daguito) -> None:
    slug = f"sdk-py-test-agent-{int(time.time())}"
    spec = AgentFlowSpec(
        slug=slug,
        name="Python SDK integration agent",
        provider="openrouter",
        model="deepseek/deepseek-chat-v4-flash:nitro",
        system_prompt="You are a tiny test agent. Answer in one sentence.",
        temperature=0.7,
    )

    first = await client.flows.upsert_agent(spec)
    assert first.flow_id, "first upsert returned no flow_id"
    assert first.slug == slug
    assert first.created is True, "first upsert should report created=True"
    assert first.webhook_id

    try:
        second = await client.flows.upsert_agent(spec)
        assert second.flow_id == first.flow_id
        assert second.webhook_id == first.webhook_id
        assert second.created is False, "second upsert should report created=False"

        resolved = await client.flows.resolve_webhook(slug)
        assert resolved.flow_id == first.flow_id
        assert resolved.webhook_id == first.webhook_id
        assert resolved.webhook_token

        fetched = await client.flows.get(first.flow_id)
        assert fetched.id == first.flow_id
        assert fetched.name == first.name
    finally:
        await client.flows.delete(first.flow_id)


@pytest.mark.asyncio
async def test_knowledge_list_sources_contains_seed(
    client: Daguito, kb_source_id: str
) -> None:
    sources = await client.knowledge.list_sources()
    assert isinstance(sources, list)
    # Rolled-up list — the source id might be the latest sibling under
    # the same kb_id, so accept either an exact id or a kb_id match.
    ids = {s.id for s in sources}
    kbs = {s.kb_id for s in sources}
    assert kb_source_id in ids or kb_source_id in kbs, (
        f"expected seed source {kb_source_id} in {len(sources)} rolled sources"
    )


@pytest.mark.asyncio
async def test_analytics_get_org_returns_snapshot(client: Daguito) -> None:
    snapshot = await client.analytics.get_org()
    assert snapshot.org_id
    assert snapshot.llm_today.requests >= 0
    assert snapshot.messages_today.outbound_last_24h >= 0
    assert isinstance(snapshot.http_today.by_path, dict)


@pytest.mark.asyncio
async def test_nodes_catalog_is_non_empty(client: Daguito) -> None:
    catalog = await client.nodes.get_catalog()
    assert isinstance(catalog, dict)
    # The catalog has both `categories` and `nodes`. At least one of them
    # must carry rows for the dashboard to render anything.
    categories = catalog.get("categories") or []
    nodes = catalog.get("nodes") or []
    assert (isinstance(categories, list) and len(categories) > 0) or (
        isinstance(nodes, list) and len(nodes) > 0
    ), f"catalog is empty: keys={list(catalog.keys())}"


@pytest.mark.asyncio
async def test_templates_parse_and_example_round_trip(client: Daguito) -> None:
    body = "[[motivo de la consulta]] [[severidad reportada]]"
    parsed = await client.templates.parse(body)
    assert parsed.field_count >= 1
    assert parsed.body_hash
    assert isinstance(parsed.template_schema.schema, dict)

    # Example extraction. The server may opt out (returns example=None)
    # when the rate limit kicks in — accept either result, just confirm
    # the call succeeds.
    example_result = await client.templates.example(
        parsed.template_schema,
        transcript="Doctor, me duele la cabeza. Es leve.",
    )
    assert isinstance(example_result.cached, bool)


@pytest.mark.asyncio
async def test_models_list_returns_at_least_one_model(client: Daguito) -> None:
    models = await client.models.list()
    assert isinstance(models, list)
    assert len(models) > 0, "no active models returned — pricing table is empty?"
    sample = models[0]
    assert sample.provider
    assert sample.id
    assert sample.display_name


@pytest.mark.asyncio
async def test_knowledge_chunk_metadata_round_trip(
    client: Daguito, kb_source_id: str
) -> None:
    source_id = os.environ.get("DAGUITO_LAWYERS_SOURCE_ID") or kb_source_id
    stamp = int(time.time() * 1_000)
    id_a = f"test-delete-by-metadata-A-{stamp}"
    id_b = f"test-delete-by-metadata-B-{stamp}"

    await client.knowledge.ingest_text(
        source_id,
        f"Lawyer profile A {stamp}. Specializes in tax law.",
        metadata={"lawyer_id": id_a, "marker": "chunk-ops-suite"},
    )
    await client.knowledge.ingest_text(
        source_id,
        f"Lawyer profile B {stamp}. Specializes in maritime law.",
        metadata={"lawyer_id": id_b, "marker": "chunk-ops-suite"},
    )

    updated = await client.knowledge.update_chunks_metadata(
        source_id,
        match={"metadata_key": "lawyer_id", "metadata_value": id_a},
        patch={"city": "Bogota"},
    )
    assert updated >= 1, f"expected at least one updated chunk, got {updated}"

    deleted_b = await client.knowledge.delete_chunks_by_metadata(
        source_id, metadata_key="lawyer_id", metadata_value=id_b
    )
    assert deleted_b >= 1, f"expected at least one deleted chunk for B, got {deleted_b}"

    missing = await client.knowledge.delete_chunks_by_metadata(
        source_id,
        metadata_key="lawyer_id",
        metadata_value=f"does-not-exist-{stamp}",
    )
    assert missing == 0, f"expected idempotent 0 deletes, got {missing}"

    # Cleanup A so the seed source doesn't accumulate test rows.
    try:
        await client.knowledge.delete_chunks_by_metadata(
            source_id, metadata_key="lawyer_id", metadata_value=id_a
        )
    except DaguitoError:
        pass


@pytest.mark.asyncio
async def test_knowledge_get_ingest_job_404_is_typed(client: Daguito) -> None:
    """Sanity check on error mapping — a known-bad job id should raise
    `DaguitoError` with the upstream status code, not a generic Exception.
    """
    with pytest.raises(DaguitoError) as exc:
        await client.knowledge.get_ingest_job("does-not-exist-xyz")
    # Server returns 404 / 500 / etc; the SDK should preserve `status`.
    assert exc.value.status is not None
