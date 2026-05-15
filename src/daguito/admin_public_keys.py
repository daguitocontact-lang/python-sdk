"""Public flow-key admin service.

`Client.public_keys` exposes list/create/revoke/set_budget against the
`/v1/flows/:flow_id/public-keys` routes.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ._admin_http import DaguitoError, request_json
from ._url import join_http
from .admin_types import (
    PublicKey,
    PublicKeyCreated,
    parse_public_key,
    parse_public_key_created,
)


class PublicKeysService:
    def __init__(self, api_url: str, client_factory: Any) -> None:
        self._api_url = api_url
        self._client_factory = client_factory

    async def list(self, flow_id: str) -> list[PublicKey]:
        async with self._client_factory() as client:
            url = join_http(
                self._api_url,
                f"/v1/flows/{quote(flow_id, safe='')}/public-keys",
            )
            data = await request_json(client, "GET", url)
        return [parse_public_key(k) for k in _coerce_keys_array(data)]

    async def create(
        self,
        flow_id: str,
        name: str,
        allowed_origins: list[str],
        monthly_budget_micro_usd: int | None = None,
    ) -> PublicKeyCreated:
        body: dict[str, Any] = {
            "name": name,
            "allowed_origins": allowed_origins,
        }
        if monthly_budget_micro_usd is not None:
            body["monthly_budget_micro_usd"] = monthly_budget_micro_usd
        async with self._client_factory() as client:
            url = join_http(
                self._api_url,
                f"/v1/flows/{quote(flow_id, safe='')}/public-keys",
            )
            data = await request_json(client, "POST", url, body=body)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from POST public-keys")
        return parse_public_key_created(data)

    async def revoke(self, flow_id: str, key_id: str) -> None:
        async with self._client_factory() as client:
            url = join_http(
                self._api_url,
                f"/v1/flows/{quote(flow_id, safe='')}/public-keys/{quote(key_id, safe='')}",
            )
            await request_json(client, "DELETE", url)

    async def set_budget(
        self,
        flow_id: str,
        key_id: str,
        monthly_budget_micro_usd: int | None,
    ) -> PublicKey:
        body = {"monthly_budget_micro_usd": monthly_budget_micro_usd}
        async with self._client_factory() as client:
            url = join_http(
                self._api_url,
                f"/v1/flows/{quote(flow_id, safe='')}/public-keys/{quote(key_id, safe='')}/budget",
            )
            data = await request_json(client, "PATCH", url, body=body)
        # Same refetch trick as account_keys.set_budget — the PATCH endpoint
        # only returns the changed field; the SDK promises the full shape.
        keys = await self.list(flow_id)
        for key in keys:
            if key.id == key_id:
                return key
        if isinstance(data, dict):
            return parse_public_key(data)
        raise DaguitoError("key not found after budget update")


def _coerce_keys_array(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and isinstance(data.get("keys"), list):
        return [k for k in data["keys"] if isinstance(k, dict)]
    if isinstance(data, list):
        return [k for k in data if isinstance(k, dict)]
    return []
