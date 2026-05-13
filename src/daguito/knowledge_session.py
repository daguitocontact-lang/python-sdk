"""Knowledge session — mirrors sdks/js/src/knowledge-session.ts.

HTTP client for ingest + search against the Daguito Knowledge Base. Auth
uses an `sk_dgt_...` API key sent via `Authorization: Bearer ...`. The key's
scopes (`kb:write`, `kb:read`) govern which methods succeed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from ._url import join_http


@dataclass
class KnowledgeSessionOptions:
    api_url: str
    api_key: str
    """Default sourceId for all ingest_text calls (can override per call)."""
    default_source_id: str | None = None


@dataclass
class IngestTextInput:
    text: str
    metadata: dict[str, Any] | None = None
    source_id: str | None = None


@dataclass
class IngestTextResult:
    source_id: str
    chunk_count: int
    token_count: int


@dataclass
class SearchInput:
    query: str
    top_k: int | None = None
    source_ids: list[str] | None = None
    enable_rewrite: bool | None = None
    enable_rerank: bool | None = None
    enable_cache: bool | None = None


@dataclass
class SearchHit:
    id: str
    source_id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    hits: list[SearchHit]
    query_original: str
    query_rewritten: str | None = None
    """Raw response from server — kept for advanced inspection."""
    raw: Any = None


class KnowledgeError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class KnowledgeSession:
    """Async client for the KB ingest + search endpoints.

    Usage:
        async with KnowledgeSession(KnowledgeSessionOptions(...)) as kb:
            await kb.ingest_text(IngestTextInput(text='...'))
            res = await kb.search(SearchInput(query='...'))
    """

    def __init__(self, opts: KnowledgeSessionOptions) -> None:
        self._opts = opts
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> KnowledgeSession:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._opts.api_key}",
            },
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def ingest_text(self, input: IngestTextInput) -> IngestTextResult:
        source_id = input.source_id or self._opts.default_source_id
        if not source_id:
            raise KnowledgeError(
                "source_id required (pass to method or set default_source_id on the session)"
            )

        url = join_http(
            self._opts.api_url,
            f"/api/sdk/knowledge/sources/{quote(source_id, safe='')}/text",
        )
        body: dict[str, Any] = {"text": input.text}
        if input.metadata is not None:
            body["metadata"] = input.metadata

        data = await self._post(url, body)
        return IngestTextResult(
            source_id=str(data.get("source_id", source_id)),
            chunk_count=int(data.get("chunk_count", 0)),
            token_count=int(data.get("token_count", 0)),
        )

    async def search(self, input: SearchInput) -> SearchResult:
        url = join_http(self._opts.api_url, "/api/sdk/knowledge/search")
        body: dict[str, Any] = {"query": input.query}
        if input.top_k is not None:
            body["top_k"] = input.top_k
        if input.source_ids is not None:
            body["source_ids"] = input.source_ids
        if input.enable_rewrite is not None:
            body["enable_rewrite"] = input.enable_rewrite
        if input.enable_rerank is not None:
            body["enable_rerank"] = input.enable_rerank
        if input.enable_cache is not None:
            body["enable_cache"] = input.enable_cache

        data = await self._post(url, body)
        raw_chunks = data.get("chunks") if isinstance(data, dict) else None
        chunks = raw_chunks if isinstance(raw_chunks, list) else []
        hits = [
            SearchHit(
                id=str(c.get("id", "")),
                source_id=str(c.get("source_id", "")),
                content=str(c.get("content", "")),
                score=float(c.get("score", 0.0)),
                metadata=c.get("metadata") if isinstance(c.get("metadata"), dict) else {},
            )
            for c in chunks
            if isinstance(c, dict)
        ]
        return SearchResult(
            hits=hits,
            query_original=str(data.get("query_original", input.query)),
            query_rewritten=data.get("query_rewritten"),
            raw=data,
        )

    async def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            # Allow ad-hoc use without context manager — autocreate a one-shot client.
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(60.0),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._opts.api_key}",
                },
            ) as client:
                return await self._do_post(client, url, body)
        return await self._do_post(self._client, url, body)

    async def _do_post(
        self, client: httpx.AsyncClient, url: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            response = await client.post(url, json=body)
        except httpx.HTTPError as err:
            raise KnowledgeError(str(err) or "network error") from err

        if response.status_code >= 400:
            text = response.text
            message: str
            try:
                parsed = response.json()
                if isinstance(parsed, dict) and isinstance(parsed.get("error"), str):
                    message = parsed["error"]
                else:
                    message = text or response.reason_phrase or f"HTTP {response.status_code}"
            except ValueError:
                message = text or response.reason_phrase or f"HTTP {response.status_code}"
            raise KnowledgeError(message, response.status_code)

        try:
            parsed = response.json()
        except ValueError as err:
            raise KnowledgeError(
                f"invalid JSON response: {err}", response.status_code
            ) from err

        if not isinstance(parsed, dict):
            raise KnowledgeError("expected JSON object response", response.status_code)
        return parsed
