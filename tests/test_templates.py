"""Contract tests for `client.templates.preview`.

Stubs `httpx.AsyncClient` via `httpx.MockTransport`, mirroring the
admin-client test conventions. Run with:

    cd sdks/python && python -m unittest tests.test_templates
"""

from __future__ import annotations

import asyncio
import json
import unittest
from typing import Any

import httpx

from daguito import (
    Daguito,
    DaguitoError,
)


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


def _ok_response() -> dict[str, Any]:
    return {
        "template_schema": {
            "name": "SOAP_27",
            "schema": {"type": "object", "properties": {"motivo": {"type": "string"}}},
        },
        "field_names": ["motivo", "alergias"],
        "field_count": 2,
        "fields_detail": [
            {"name": "motivo", "description": "razón de la consulta", "type": "string"},
            {
                "name": "severidad",
                "description": "severidad reportada",
                "type": "enum",
                "enum_values": ["leve", "moderada", "grave"],
            },
        ],
        "example": {
            "transcript": "Doctor, me duele la cabeza",
            "transcript_origin": "default",
            "extracted": {"motivo": "cefalea", "alergias": None},
            "model": "deepseek-v4-flash",
        },
        "warnings": [
            {
                "code": "placeholder_empty",
                "field": "extra",
                "message": "placeholder has no body",
            }
        ],
        "body_hash": "sha256:abc123",
    }


class TemplatesPreviewTest(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def _make(self, response_factory: Any) -> Daguito:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content) if request.content else None
            self.calls.append((request.method, str(request.url), body))
            return response_factory(request)

        client = Daguito(api_url="https://api.example.com", api_key="dgsk_acc_test")
        client.templates._client_factory = _build_factory(handler)
        return client

    def test_preview_posts_json_and_parses_result(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_response())

        client = self._make(respond)
        result = asyncio.run(
            client.templates.preview(
                "[[razón de la consulta]] [[alergias del paciente]]",
                vertical="medical",
                model="deepseek-v4-flash",
                force_regenerate=True,
            )
        )
        method, url, body = self.calls[0]
        self.assertEqual(method, "POST")
        self.assertIn("/v1/templates/preview", url)
        self.assertEqual(
            body,
            {
                "template_body": "[[razón de la consulta]] [[alergias del paciente]]",
                "vertical": "medical",
                "model": "deepseek-v4-flash",
                "force_regenerate": True,
            },
        )
        self.assertEqual(result.field_count, 2)
        self.assertEqual(result.field_names, ["motivo", "alergias"])
        self.assertEqual(result.template_schema.name, "SOAP_27")
        self.assertEqual(result.fields_detail[1].type, "enum")
        self.assertEqual(
            result.fields_detail[1].enum_values, ["leve", "moderada", "grave"]
        )
        assert result.example is not None
        self.assertEqual(result.example.transcript_origin, "default")
        self.assertEqual(result.example.extracted, {"motivo": "cefalea", "alergias": None})
        self.assertEqual(result.warnings[0].code, "placeholder_empty")
        self.assertEqual(result.body_hash, "sha256:abc123")

    def test_preview_omits_optional_fields(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_response())

        client = self._make(respond)
        asyncio.run(client.templates.preview("[[motivo]]"))
        _, _, body = self.calls[0]
        self.assertEqual(body, {"template_body": "[[motivo]]"})

    def test_preview_rejects_empty_body(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_ok_response())

        client = self._make(respond)
        with self.assertRaises(DaguitoError):
            asyncio.run(client.templates.preview(""))
        self.assertEqual(self.calls, [])

    def test_preview_surfaces_400(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "template_body required"})

        client = self._make(respond)
        with self.assertRaises(DaguitoError) as cm:
            asyncio.run(client.templates.preview("[[a]]"))
        self.assertEqual(cm.exception.status, 400)

    def test_preview_handles_null_example(self) -> None:
        def respond(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "template_schema": {"name": "X", "schema": {}},
                    "field_names": [],
                    "field_count": 0,
                    "fields_detail": [],
                    "example": None,
                    "body_hash": "sha256:empty",
                },
            )

        client = self._make(respond)
        result = asyncio.run(client.templates.preview("no placeholders"))
        self.assertIsNone(result.example)
        self.assertEqual(result.warnings, [])
        self.assertEqual(result.body_hash, "sha256:empty")


if __name__ == "__main__":
    unittest.main()
