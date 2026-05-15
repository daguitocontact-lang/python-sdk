"""Contract tests for the admin `Daguito` client.

Stubs `httpx.AsyncClient` via `httpx.MockTransport` so the suite is fully
offline. Covers list / create / revoke / set_budget for the three
services + the 401/403 error mapping.

Runs under stdlib `unittest`:

    cd sdks/python && python -m unittest tests.test_admin_client
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

import httpx

from daguito import Daguito, DaguitoError
from daguito._client_headers import (
    SDK_LANG,
    SDK_VERSION,
    append_client_query_params,
    client_headers,
)
from daguito.admin_account_keys import make_client_factory


def _build_factory(handler: Any) -> Any:
    transport = httpx.MockTransport(handler)

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=transport,
            base_url="https://api.example.com",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer dgsk_acc_test",
            },
        )

    return factory


def _wire_client(client: Daguito, factory: Any) -> None:
    """Replace the client's per-service factories with a mocked one."""
    client.account_keys._client_factory = factory
    client.public_keys._client_factory = factory
    client.budgets._client_factory = factory


def _ok_key(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "ak_1",
        "name": "prod",
        "key_prefix": "dgsk_acc_abc12",
        "monthly_budget_micro_usd": None,
        "current_mtd_micro_usd": 0,
        "created_at": "2026-05-14T00:00:00.000Z",
        "last_used_at": None,
        "revoked_at": None,
    }
    base.update(overrides)
    return base


def _ok_pub_key(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "pk_1",
        "flow_id": "flow_abc",
        "name": "browser",
        "key_prefix": "dgpk_flow_x9",
        "allowed_origins": ["https://example.com"],
        "monthly_budget_micro_usd": None,
        "current_mtd_micro_usd": 0,
        "created_at": "2026-05-14T00:00:00.000Z",
        "last_used_at": None,
        "revoked_at": None,
    }
    base.update(overrides)
    return base


class AccountKeysServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def _make(self, response_factory: Any) -> Daguito:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else None
            self.calls.append((request.method, str(request.url), body))
            return response_factory(request)

        client = Daguito(api_url="https://api.example.com", api_key="dgsk_acc_test")
        _wire_client(client, _build_factory(handler))
        return client

    def test_list_returns_account_keys(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"keys": [_ok_key(), _ok_key(id="ak_2")]})

        client = self._make(respond)
        keys = asyncio.run(client.account_keys.list())
        self.assertEqual(len(keys), 2)
        self.assertEqual(keys[0].id, "ak_1")
        self.assertEqual(keys[0].key_prefix, "dgsk_acc_abc12")
        self.assertEqual(self.calls[0][0], "GET")
        self.assertIn("/v1/account/api-keys", self.calls[0][1])

    def test_create_returns_plaintext(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(201, json={**_ok_key(), "plaintext": "dgsk_acc_FULL"})

        client = self._make(respond)
        created = asyncio.run(
            client.account_keys.create(name="prod", monthly_budget_micro_usd=5_000_000)
        )
        self.assertEqual(created.plaintext, "dgsk_acc_FULL")
        self.assertEqual(created.id, "ak_1")
        method, _, body = self.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(body, {"name": "prod", "monthly_budget_micro_usd": 5_000_000})

    def test_revoke_handles_204(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        client = self._make(respond)
        result = asyncio.run(client.account_keys.revoke("ak_1"))
        self.assertIsNone(result)
        self.assertEqual(self.calls[0][0], "DELETE")
        self.assertIn("/v1/account/api-keys/ak_1", self.calls[0][1])

    def test_set_budget_refetches_full_shape(self) -> None:
        seq: list[httpx.Response] = [
            httpx.Response(200, json={"id": "ak_1", "monthly_budget_micro_usd": 1_000_000}),
            httpx.Response(
                200,
                json={"keys": [_ok_key(monthly_budget_micro_usd=1_000_000)]},
            ),
        ]

        def respond(_: httpx.Request) -> httpx.Response:
            return seq.pop(0)

        client = self._make(respond)
        updated = asyncio.run(
            client.account_keys.set_budget("ak_1", 1_000_000)
        )
        self.assertEqual(updated.monthly_budget_micro_usd, 1_000_000)
        self.assertEqual(self.calls[0][0], "PATCH")
        self.assertEqual(self.calls[1][0], "GET")

    def test_unauthorized_maps_to_daguito_error(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "missing bearer"})

        client = self._make(respond)
        with self.assertRaises(DaguitoError) as cm:
            asyncio.run(client.account_keys.list())
        self.assertEqual(cm.exception.status, 401)
        self.assertIn("missing bearer", str(cm.exception))

    def test_forbidden_maps_to_daguito_error(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "not an admin"})

        client = self._make(respond)
        with self.assertRaises(DaguitoError) as cm:
            asyncio.run(client.account_keys.list())
        self.assertEqual(cm.exception.status, 403)


class PublicKeysServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def _make(self, response_factory: Any) -> Daguito:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else None
            self.calls.append((request.method, str(request.url), body))
            return response_factory(request)

        client = Daguito(api_url="https://api.example.com", api_key="dgsk_acc_test")
        _wire_client(client, _build_factory(handler))
        return client

    def test_list_for_flow(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"keys": [_ok_pub_key()]})

        client = self._make(respond)
        keys = asyncio.run(client.public_keys.list("flow_abc"))
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0].flow_id, "flow_abc")
        self.assertIn("/v1/flows/flow_abc/public-keys", self.calls[0][1])

    def test_create_requires_origins(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                201,
                json={**_ok_pub_key(), "plaintext": "dgpk_flow_FULL"},
            )

        client = self._make(respond)
        created = asyncio.run(
            client.public_keys.create(
                flow_id="flow_abc",
                name="browser",
                allowed_origins=["https://example.com"],
                monthly_budget_micro_usd=None,
            )
        )
        self.assertEqual(created.plaintext, "dgpk_flow_FULL")
        body = self.calls[0][2]
        self.assertEqual(body["allowed_origins"], ["https://example.com"])
        self.assertEqual(body["name"], "browser")
        # monthly_budget_micro_usd is None → omitted from the wire body so
        # server defaults apply (mirrors JS/Go shape).
        self.assertNotIn("monthly_budget_micro_usd", body)

    def test_revoke(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(204)

        client = self._make(respond)
        asyncio.run(client.public_keys.revoke("flow_abc", "pk_1"))
        self.assertEqual(self.calls[0][0], "DELETE")
        self.assertIn("/v1/flows/flow_abc/public-keys/pk_1", self.calls[0][1])


class BudgetsServiceTest(unittest.TestCase):
    def _make(self, response_factory: Any) -> Daguito:
        def handler(request: httpx.Request) -> httpx.Response:
            return response_factory(request)

        client = Daguito(api_url="https://api.example.com", api_key="dgsk_acc_test")
        _wire_client(client, _build_factory(handler))
        return client

    def test_get_org(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "monthly_budget_micro_usd": 100_000_000,
                    "current_mtd_micro_usd": 25_000_000,
                    "mtd_reset_at": "2026-06-01T00:00:00.000Z",
                },
            )

        client = self._make(respond)
        budget = asyncio.run(client.budgets.get_org())
        self.assertEqual(budget.monthly_budget_micro_usd, 100_000_000)
        self.assertEqual(budget.current_mtd_micro_usd, 25_000_000)
        self.assertEqual(budget.mtd_reset_at, "2026-06-01T00:00:00.000Z")

    def test_set_org_with_null_clears(self) -> None:
        captured: dict[str, Any] = {}

        def respond(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "monthly_budget_micro_usd": None,
                    "current_mtd_micro_usd": 0,
                    "mtd_reset_at": "2026-06-01T00:00:00.000Z",
                },
            )

        client = self._make(respond)
        budget = asyncio.run(client.budgets.set_org(None))
        self.assertIsNone(budget.monthly_budget_micro_usd)
        self.assertEqual(captured["body"], {"monthly_budget_micro_usd": None})


class FactoryTest(unittest.TestCase):
    def test_factory_yields_bearer_header(self) -> None:
        factory = make_client_factory("dgsk_acc_xyz")
        client = factory()
        self.assertEqual(client.headers["Authorization"], "Bearer dgsk_acc_xyz")

    def test_factory_yields_sdk_tracking_headers(self) -> None:
        factory = make_client_factory("dgsk_acc_xyz")
        client = factory()
        self.assertEqual(
            client.headers["X-Daguito-Client"], f"daguito-sdk-python/{SDK_VERSION}"
        )
        self.assertEqual(client.headers["X-Daguito-Client-Lang"], "python")
        self.assertEqual(client.headers["X-Daguito-Client-Version"], SDK_VERSION)


class ClientHeadersTest(unittest.TestCase):
    def test_client_headers_shape(self) -> None:
        headers = client_headers()
        self.assertEqual(headers["X-Daguito-Client"], f"daguito-sdk-python/{SDK_VERSION}")
        self.assertEqual(headers["X-Daguito-Client-Lang"], SDK_LANG)
        self.assertEqual(headers["X-Daguito-Client-Version"], SDK_VERSION)

    def test_append_to_url_without_query(self) -> None:
        result = append_client_query_params("wss://api.example.com/v1/webhooks/wh_1/stream")
        self.assertIn("x_daguito_client_lang=python", result)
        self.assertIn(f"x_daguito_client_version={SDK_VERSION}", result)
        self.assertTrue(result.startswith("wss://api.example.com/v1/webhooks/wh_1/stream?"))

    def test_append_preserves_existing_query(self) -> None:
        result = append_client_query_params(
            "wss://api.example.com/v1/webhooks/wh_1/stream?token=abc"
        )
        self.assertIn("token=abc", result)
        self.assertIn("x_daguito_client_lang=python", result)
        self.assertIn(f"x_daguito_client_version={SDK_VERSION}", result)
        self.assertIn("&", result)


if __name__ == "__main__":
    unittest.main()
