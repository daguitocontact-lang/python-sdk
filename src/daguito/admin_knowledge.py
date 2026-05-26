"""Knowledge-base management — list/create sources, list bases, ingest URLs,
poll ingest jobs.

The data-plane (text ingest + search via `sk_dgt_…`) stays on
`KnowledgeSession` (`daguito.knowledge_session`). This module is the
account-key management surface backed by `/api/public/knowledge/*` and
mirrors the MCP tools `daguito_list_knowledge_*` /
`daguito_create_knowledge_source` / `daguito_ingest_url` /
`daguito_get_ingest_job`.

Exposed as `client.knowledge`; the existing data-plane factory lives at
`client.knowledge_session` so both surfaces co-exist without name
collision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from ._admin_http import DaguitoError, request_json
from ._url import join_http


@dataclass(slots=True)
class KnowledgeBase:
    id: str
    name: str
    description: str | None
    dim: int
    tenancy_tier: str
    embedding_provider: str
    embedding_model: str

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "KnowledgeBase":
        desc = data.get("description")
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            description=str(desc) if isinstance(desc, str) else None,
            dim=int(data.get("dim") or 0),
            tenancy_tier=str(data.get("tenancy_tier") or ""),
            embedding_provider=str(data.get("embedding_provider") or ""),
            embedding_model=str(data.get("embedding_model") or ""),
        )


@dataclass(slots=True)
class KnowledgeSource:
    id: str
    org_id: str
    kb_id: str
    name: str
    description: str | None
    kind: str
    status: str
    chunk_count: int
    token_count: int
    source_count: int | None
    created_at: str | None
    updated_at: str | None

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "KnowledgeSource":
        desc = data.get("description")
        return cls(
            id=str(data.get("id") or ""),
            org_id=str(data.get("org_id") or ""),
            kb_id=str(data.get("kb_id") or ""),
            name=str(data.get("name") or ""),
            description=str(desc) if isinstance(desc, str) else None,
            kind=str(data.get("kind") or ""),
            status=str(data.get("status") or ""),
            chunk_count=int(data.get("chunk_count") or 0),
            token_count=int(data.get("token_count") or 0),
            source_count=(
                int(data["source_count"]) if isinstance(data.get("source_count"), int) else None
            ),
            created_at=_optional_str(data.get("created_at")),
            updated_at=_optional_str(data.get("updated_at")),
        )


@dataclass(slots=True)
class IngestJobStatus:
    """Status snapshot returned by `knowledge.get_ingest_job`.

    `status` lifecycle: `queued → processing → ready | failed`. `result`
    is populated on terminal states (`ready` carries chunk/token counts;
    `failed` carries the error message).
    """

    job_id: str
    status: str
    source_id: str | None
    org_id: str | None
    progress: float | None
    error: str | None
    result: dict[str, Any] | None
    raw: dict[str, Any]

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "IngestJobStatus":
        result = data.get("result")
        return cls(
            job_id=str(data.get("job_id") or ""),
            status=str(data.get("status") or "unknown"),
            source_id=_optional_str(data.get("source_id")),
            org_id=_optional_str(data.get("org_id")),
            progress=(
                float(data["progress"]) if isinstance(data.get("progress"), (int, float)) else None
            ),
            error=_optional_str(data.get("error")),
            result=result if isinstance(result, dict) else None,
            raw=data,
        )


class AdminKnowledgeService:
    def __init__(self, api_url: str, client_factory: Any) -> None:
        self._api_url = api_url
        self._client_factory = client_factory

    async def list_bases(self, org_id: str | None = None) -> list[KnowledgeBase]:
        suffix = _query_suffix({"org_id": org_id} if org_id else {})
        async with self._client_factory() as client:
            url = join_http(self._api_url, f"/api/public/knowledge/bases{suffix}")
            data = await request_json(client, "GET", url)
        if isinstance(data, dict) and isinstance(data.get("bases"), list):
            return [KnowledgeBase.from_wire(b) for b in data["bases"] if isinstance(b, dict)]
        return []

    async def list_sources(self, org_id: str | None = None) -> list[KnowledgeSource]:
        suffix = _query_suffix({"org_id": org_id} if org_id else {})
        async with self._client_factory() as client:
            url = join_http(self._api_url, f"/api/public/knowledge/sources{suffix}")
            data = await request_json(client, "GET", url)
        if isinstance(data, dict) and isinstance(data.get("sources"), list):
            return [KnowledgeSource.from_wire(s) for s in data["sources"] if isinstance(s, dict)]
        return []

    async def create_source(self, source: dict[str, Any]) -> KnowledgeSource:
        """Create a new KB + first source row. `source` body keys: `org_id`,
        `name`, optional `description`, optional `kind` (one of
        `url|file|text|sitemap`).
        """
        if not isinstance(source, dict):
            raise DaguitoError("create_source: source must be a dict")
        if not source.get("name"):
            raise DaguitoError("create_source: source.name is required")
        if not source.get("org_id"):
            raise DaguitoError("create_source: source.org_id is required")
        async with self._client_factory() as client:
            url = join_http(self._api_url, "/api/public/knowledge/sources")
            data = await request_json(client, "POST", url, body=source)
        if isinstance(data, dict) and isinstance(data.get("source"), dict):
            return KnowledgeSource.from_wire(data["source"])
        raise DaguitoError("expected source object in response")

    async def ingest_url(
        self,
        source_id: str,
        url: str,
        metadata: dict[str, Any] | None = None,
    ) -> IngestJobStatus:
        """Enqueue an ingest job that fetches `url`, parses it, and indexes
        the result into the given source. Poll the returned `job_id` with
        `get_ingest_job` until `status` is terminal.
        """
        if not source_id:
            raise DaguitoError("ingest_url: source_id is required")
        if not url:
            raise DaguitoError("ingest_url: url is required")
        body: dict[str, Any] = {"url": url}
        if metadata is not None:
            body["metadata"] = metadata
        async with self._client_factory() as client:
            req_url = join_http(
                self._api_url,
                f"/api/public/knowledge/sources/{quote(source_id, safe='')}/url",
            )
            data = await request_json(client, "POST", req_url, body=body)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from ingest_url")
        return IngestJobStatus.from_wire(data)

    async def ingest_text(
        self,
        source_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> IngestJobStatus:
        """Synchronously ingest raw text into the given source. Mirrors the
        data-plane `KnowledgeSession.ingest_text` shape but authenticates
        with the org account key.
        """
        if not source_id:
            raise DaguitoError("ingest_text: source_id is required")
        if not text:
            raise DaguitoError("ingest_text: text is required")
        body: dict[str, Any] = {"text": text}
        if metadata is not None:
            body["metadata"] = metadata
        async with self._client_factory() as client:
            req_url = join_http(
                self._api_url,
                f"/api/public/knowledge/sources/{quote(source_id, safe='')}/text",
            )
            data = await request_json(client, "POST", req_url, body=body)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from ingest_text")
        return IngestJobStatus.from_wire(data)

    async def get_ingest_job(self, job_id: str) -> IngestJobStatus:
        if not job_id:
            raise DaguitoError("get_ingest_job: job_id is required")
        async with self._client_factory() as client:
            url = join_http(
                self._api_url,
                f"/api/public/knowledge/ingest-jobs/{quote(job_id, safe='')}",
            )
            data = await request_json(client, "GET", url)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from get_ingest_job")
        return IngestJobStatus.from_wire(data)

    async def delete_chunks_by_metadata(
        self,
        source_id: str,
        metadata_key: str,
        metadata_value: str,
    ) -> int:
        """Delete every chunk in `source_id` whose `metadata[metadata_key]`
        equals `metadata_value`. Returns the count of deleted rows; 0 when
        nothing matched (idempotent).
        """
        if not source_id:
            raise DaguitoError("delete_chunks_by_metadata: source_id is required")
        if not metadata_key:
            raise DaguitoError("delete_chunks_by_metadata: metadata_key is required")
        query = urlencode(
            {"metadata_key": metadata_key, "metadata_value": str(metadata_value)}
        )
        async with self._client_factory() as client:
            url = join_http(
                self._api_url,
                f"/api/public/knowledge/sources/{quote(source_id, safe='')}/chunks?{query}",
            )
            data = await request_json(client, "DELETE", url)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from delete_chunks_by_metadata")
        raw_count = data.get("deleted_count")
        return int(raw_count) if isinstance(raw_count, int) else 0

    async def update_chunks_metadata(
        self,
        source_id: str,
        match: dict[str, Any],
        patch: dict[str, Any],
    ) -> int:
        """Shallow-merge `patch` into every chunk in `source_id` whose
        metadata matches `match`. `match` keys: `metadata_key`,
        `metadata_value`. Returns the count of updated rows.
        """
        if not source_id:
            raise DaguitoError("update_chunks_metadata: source_id is required")
        if not isinstance(match, dict) or not match.get("metadata_key"):
            raise DaguitoError("update_chunks_metadata: match.metadata_key is required")
        if not isinstance(patch, dict):
            raise DaguitoError("update_chunks_metadata: patch must be a dict")
        body = {
            "match": {
                "metadata_key": str(match.get("metadata_key")),
                "metadata_value": str(match.get("metadata_value", "")),
            },
            "patch": patch,
        }
        async with self._client_factory() as client:
            url = join_http(
                self._api_url,
                f"/api/public/knowledge/sources/{quote(source_id, safe='')}/chunks",
            )
            data = await request_json(client, "PATCH", url, body=body)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from update_chunks_metadata")
        raw_count = data.get("updated_count")
        return int(raw_count) if isinstance(raw_count, int) else 0


def _query_suffix(query: dict[str, str | None]) -> str:
    filtered = {k: v for k, v in query.items() if v}
    return f"?{urlencode(filtered)}" if filtered else ""


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
