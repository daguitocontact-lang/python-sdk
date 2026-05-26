"""Curated LLM picker — `client.models.list()` returns the model rows
the server exposes via `GET /v1/models` (the same set the dashboard's
flow-builder model picker uses).

Auth = account API key. The server filters out inactive rows and rows
whose `metadata.builder_visible` flag is false, so callers see only what
they can actually pass to `flows.upsert_agent`.

Wire shape from the server:

    {
      "org_id": "...",
      "models": [
        { "provider": "openrouter",
          "id": "deepseek/…",
          "displayName": "DeepSeek v4 Flash",
          "tier": "fast" }   // optional
      ]
    }

The SDK surfaces the same `id` field name (matches the wire), and
exposes `display_name` in snake_case as is Python convention — the
mapping happens in `from_wire`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ._admin_http import DaguitoError, request_json
from ._url import join_http


@dataclass(slots=True)
class Model:
    provider: str
    id: str
    display_name: str
    tier: str | None = None

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "Model":
        return cls(
            provider=str(data.get("provider") or ""),
            id=str(data.get("id") or ""),
            display_name=str(data.get("displayName") or data.get("id") or ""),
            tier=_optional_str(data.get("tier")),
        )


class ModelsService:
    def __init__(self, api_url: str, client_factory: Any) -> None:
        self._api_url = api_url
        self._client_factory = client_factory

    async def list(self) -> list[Model]:
        async with self._client_factory() as client:
            url = join_http(self._api_url, "/v1/models")
            data = await request_json(client, "GET", url)
        if isinstance(data, dict) and isinstance(data.get("models"), list):
            return [Model.from_wire(m) for m in data["models"] if isinstance(m, dict)]
        raise DaguitoError("expected models array from GET /v1/models")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
