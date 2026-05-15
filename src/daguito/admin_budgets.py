"""Org-level budget admin service.

`Client.budgets` exposes the GET/PATCH `/v1/account/budget` pair. Per-key
budgets live on `account_keys.set_budget` / `public_keys.set_budget`.
"""

from __future__ import annotations

from typing import Any

from ._admin_http import DaguitoError, request_json
from ._url import join_http
from .admin_types import OrgBudget, parse_org_budget


class BudgetsService:
    def __init__(self, api_url: str, client_factory: Any) -> None:
        self._api_url = api_url
        self._client_factory = client_factory

    async def get_org(self) -> OrgBudget:
        async with self._client_factory() as client:
            url = join_http(self._api_url, "/v1/account/budget")
            data = await request_json(client, "GET", url)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from GET /v1/account/budget")
        return parse_org_budget(data)

    async def set_org(self, monthly_budget_micro_usd: int | None) -> OrgBudget:
        body = {"monthly_budget_micro_usd": monthly_budget_micro_usd}
        async with self._client_factory() as client:
            url = join_http(self._api_url, "/v1/account/budget")
            data = await request_json(client, "PATCH", url, body=body)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from PATCH /v1/account/budget")
        return parse_org_budget(data)
