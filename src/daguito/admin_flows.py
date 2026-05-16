"""Flow resolution service.

`Daguito.flows.resolve_webhook(slug)` resolves a flow by slug (in the org
the API key belongs to) and returns its streaming webhook id + a usable
`sk_wh_…` token. This lets a client open AudioStreamSession /
WebhookStreamSession without anyone hardcoding webhook credentials —
they ask for the flow by its stable slug instead.

Backed by `GET /api/sdk/flows?slug=…`, auth = the org API key
(`sk_dgt_…`, scope `flow:run`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from ._admin_http import request_json
from ._url import join_http


@dataclass
class ResolvedFlowWebhook:
    flow_id: str
    slug: str
    name: str
    webhook_id: str
    webhook_token: str


class FlowsService:
    def __init__(self, api_url: str, client_factory: Any) -> None:
        self._api_url = api_url
        self._client_factory = client_factory

    async def resolve_webhook(self, slug: str) -> ResolvedFlowWebhook:
        async with self._client_factory() as client:
            url = join_http(
                self._api_url,
                f"/api/sdk/flows?slug={quote(slug, safe='')}",
            )
            data = await request_json(client, "GET", url)
        return ResolvedFlowWebhook(
            flow_id=str(data["flow_id"]),
            slug=str(data["slug"]),
            name=str(data["name"]),
            webhook_id=str(data["webhook_id"]),
            webhook_token=str(data["webhook_token"]),
        )
