"""Flow-node catalog — `client.nodes.get_catalog()` returns every flow
node type available, grouped by category. Use it to discover valid node
`step_type` values before assembling a flow graph with
`flows.upsert_flow`.

Backed by `GET /api/public/nodes/catalog`, no auth required by the
catalog route itself — but the SDK threads the configured account key
through anyway so logs attribute the call.
"""

from __future__ import annotations

from typing import Any

from ._admin_http import DaguitoError, request_json
from ._url import join_http


class NodesService:
    def __init__(self, api_url: str, client_factory: Any) -> None:
        self._api_url = api_url
        self._client_factory = client_factory

    async def get_catalog(self) -> dict[str, Any]:
        """Return the raw catalog dict — `{ categories, nodes }`.

        Surfaced as a plain dict so callers don't have to track schema
        churn in the catalog (the server side adds new node kinds
        frequently). See the dashboard's flow-builder for how to render
        it; the MCP tool ships it verbatim too.
        """
        async with self._client_factory() as client:
            url = join_http(self._api_url, "/api/public/nodes/catalog")
            data = await request_json(client, "GET", url)
        if not isinstance(data, dict):
            raise DaguitoError(
                "expected JSON object from GET /api/public/nodes/catalog"
            )
        return data
