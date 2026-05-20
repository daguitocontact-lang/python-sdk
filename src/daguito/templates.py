"""Template preview service.

`Daguito.templates.preview(...)` wraps `POST /v1/templates/preview`. Given a
markdown / text body with `[[natural-language description]]` placeholders,
returns the inferred JSON schema, the typed field list, optional warnings,
a stable `body_hash`, and (when the server decides to run the extractor) a
model-extracted example payload. The placeholder body is plain description
— there is no `| type` syntax, the model infers the field type downstream.

Auth is the same bearer account key used by `flows.upsert_agent` on the
Go / JS SDKs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ._admin_http import DaguitoError, request_json
from ._url import join_http

TemplateFieldType = Literal[
    "string", "number", "integer", "boolean", "date", "array", "enum"
]
TranscriptOrigin = Literal["caller", "default"]


@dataclass
class TemplateFieldDetail:
    name: str
    description: str
    type: TemplateFieldType
    enum_values: list[str] | None = None


@dataclass
class TemplateSchema:
    name: str
    schema: dict[str, Any]


@dataclass
class TemplatePreviewExample:
    transcript: str
    transcript_origin: TranscriptOrigin
    extracted: dict[str, Any] | None
    model: str


@dataclass
class TemplatePreviewWarning:
    code: str
    message: str
    field: str | None = None
    hint: str | None = None


@dataclass
class TemplatePreviewResult:
    template_schema: TemplateSchema
    field_names: list[str]
    field_count: int
    fields_detail: list[TemplateFieldDetail]
    example: TemplatePreviewExample | None
    body_hash: str
    warnings: list[TemplatePreviewWarning] = field(default_factory=list)


class TemplatesService:
    def __init__(self, api_url: str, client_factory: Any) -> None:
        self._api_url = api_url
        self._client_factory = client_factory

    async def preview(
        self,
        template_body: str,
        *,
        vertical: str | None = None,
        model: str | None = None,
        force_regenerate: bool | None = None,
    ) -> TemplatePreviewResult:
        if not template_body:
            raise DaguitoError("preview: template_body is required")
        body: dict[str, Any] = {"template_body": template_body}
        if vertical is not None:
            body["vertical"] = vertical
        if model is not None:
            body["model"] = model
        if force_regenerate is not None:
            body["force_regenerate"] = force_regenerate
        async with self._client_factory() as client:
            url = join_http(self._api_url, "/v1/templates/preview")
            data = await request_json(client, "POST", url, body=body)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from POST /v1/templates/preview")
        return _parse_preview_result(data)


def _parse_preview_result(data: dict[str, Any]) -> TemplatePreviewResult:
    schema_wire = data.get("template_schema") or {}
    body_hash_raw = data.get("body_hash")
    return TemplatePreviewResult(
        template_schema=TemplateSchema(
            name=str(schema_wire.get("name") or ""),
            schema=dict(schema_wire.get("schema") or {}),
        ),
        field_names=[
            str(n) for n in (data.get("field_names") or []) if isinstance(n, str)
        ],
        field_count=int(data.get("field_count") or 0),
        fields_detail=[
            _parse_field_detail(f)
            for f in (data.get("fields_detail") or [])
            if isinstance(f, dict)
        ],
        example=_parse_example(data.get("example")),
        body_hash=body_hash_raw if isinstance(body_hash_raw, str) else "",
        warnings=[
            _parse_warning(w)
            for w in (data.get("warnings") or [])
            if isinstance(w, dict)
        ],
    )


def _parse_field_detail(wire: dict[str, Any]) -> TemplateFieldDetail:
    enum_values_raw = wire.get("enum_values")
    enum_values: list[str] | None = None
    if isinstance(enum_values_raw, list):
        enum_values = [str(v) for v in enum_values_raw if isinstance(v, str)]
    return TemplateFieldDetail(
        name=str(wire.get("name") or ""),
        description=str(wire.get("description") or ""),
        type=_coerce_field_type(wire.get("type")),
        enum_values=enum_values,
    )


def _coerce_field_type(value: Any) -> TemplateFieldType:
    valid: tuple[TemplateFieldType, ...] = (
        "string", "number", "integer", "boolean", "date", "array", "enum",
    )
    for candidate in valid:
        if value == candidate:
            return candidate
    return "string"


def _parse_example(wire: Any) -> TemplatePreviewExample | None:
    if not isinstance(wire, dict):
        return None
    origin = wire.get("transcript_origin")
    transcript_origin: TranscriptOrigin = "caller" if origin == "caller" else "default"
    extracted_raw = wire.get("extracted")
    extracted = extracted_raw if isinstance(extracted_raw, dict) else None
    return TemplatePreviewExample(
        transcript=str(wire.get("transcript") or ""),
        transcript_origin=transcript_origin,
        extracted=extracted,
        model=str(wire.get("model") or ""),
    )


def _parse_warning(wire: dict[str, Any]) -> TemplatePreviewWarning:
    field_value = wire.get("field")
    hint_value = wire.get("hint")
    return TemplatePreviewWarning(
        code=str(wire.get("code") or ""),
        message=str(wire.get("message") or ""),
        field=str(field_value) if isinstance(field_value, str) else None,
        hint=str(hint_value) if isinstance(hint_value, str) else None,
    )
