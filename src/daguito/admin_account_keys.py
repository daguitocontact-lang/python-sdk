"""Account-key admin service.

`Client.account_keys` exposes list/create/revoke/set_budget against the
`/v1/account/api-keys` routes. Auth uses the same bearer token as the
parent client — typically a `dgsk_acc_…` account key.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from ._admin_http import DaguitoError, request_json
from ._client_headers import client_headers
from ._url import join_http
from .admin_types import (
    AccountKey,
    AccountKeyCreated,
    parse_account_key,
    parse_account_key_created,
)


class AccountKeysService:
    """Manage `dgsk_acc_…` keys for the caller's org."""

    def __init__(self, api_url: str, client_factory: Any) -> None:
        self._api_url = api_url
        self._client_factory = client_factory

    async def list(self) -> list[AccountKey]:
        async with self._client_factory() as client:
            url = join_http(self._api_url, "/v1/account/api-keys")
            data = await request_json(client, "GET", url)
        keys = _coerce_keys_array(data)
        return [parse_account_key(k) for k in keys]

    async def create(
        self,
        name: str,
        monthly_budget_micro_usd: int | None = None,
    ) -> AccountKeyCreated:
        body: dict[str, Any] = {"name": name}
        if monthly_budget_micro_usd is not None:
            body["monthly_budget_micro_usd"] = monthly_budget_micro_usd
        async with self._client_factory() as client:
            url = join_http(self._api_url, "/v1/account/api-keys")
            data = await request_json(client, "POST", url, body=body)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from POST /v1/account/api-keys")
        return parse_account_key_created(data)

    async def revoke(self, key_id: str) -> None:
        async with self._client_factory() as client:
            url = join_http(
                self._api_url,
                f"/v1/account/api-keys/{quote(key_id, safe='')}",
            )
            await request_json(client, "DELETE", url)

    async def set_budget(
        self,
        key_id: str,
        monthly_budget_micro_usd: int | None,
    ) -> AccountKey:
        body = {"monthly_budget_micro_usd": monthly_budget_micro_usd}
        async with self._client_factory() as client:
            url = join_http(
                self._api_url,
                f"/v1/account/api-keys/{quote(key_id, safe='')}/budget",
            )
            data = await request_json(client, "PATCH", url, body=body)
        # The PATCH /budget endpoint returns {id, monthly_budget_micro_usd}; we
        # refetch the canonical row from the list to surface the full shape.
        keys = await self.list()
        for key in keys:
            if key.id == key_id:
                return key
        # Fallback to a minimal projection if the list doesn't include it.
        if isinstance(data, dict):
            return parse_account_key(data)
        raise DaguitoError("key not found after budget update")


def _coerce_keys_array(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("keys"), list):
        return [k for k in data["keys"] if isinstance(k, dict)]
    if isinstance(data, list):
        return [k for k in data if isinstance(k, dict)]
    return []


def make_client_factory(api_key: str) -> Any:
    """Return a zero-arg factory that yields a fresh `httpx.AsyncClient`."""

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                **client_headers(),
            },
        )

    return factory
