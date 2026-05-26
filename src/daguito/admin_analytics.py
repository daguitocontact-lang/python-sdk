"""Org analytics — `client.analytics.get_org()` returns the calling org's
own usage snapshot (today's LLM + message + HTTP volume + budget state).

Backed by `GET /v1/org/analytics`, auth = account API key. Every number
is an O(1) Redis read (plus one indexed Postgres count for outbound
message totals), so the call is cheap enough to drive dashboards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._admin_http import DaguitoError, request_json
from ._url import join_http


@dataclass(slots=True)
class LlmUsage:
    requests: int
    tokens: int
    cost_usd: float


@dataclass(slots=True)
class MessagesUsage:
    inbound: dict[str, int]
    outbound_last_24h: int


@dataclass(slots=True)
class HttpUsage:
    total: int
    by_path: dict[str, int]


@dataclass(slots=True)
class OrgBudgetSnapshot:
    org_cap_micro_usd: int | None
    org_mtd_micro_usd: int
    key_cap_micro_usd: int | None
    key_mtd_micro_usd: int


@dataclass(slots=True)
class OrgAnalytics:
    org_id: str
    llm_today: LlmUsage
    messages_today: MessagesUsage
    http_today: HttpUsage
    budget: OrgBudgetSnapshot
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "OrgAnalytics":
        llm = data.get("llm_today") or {}
        msgs = data.get("messages_today") or {}
        http = data.get("http_today") or {}
        budget = data.get("budget") or {}
        return cls(
            org_id=str(data.get("org_id") or ""),
            llm_today=LlmUsage(
                requests=int(llm.get("requests") or 0),
                tokens=int(llm.get("tokens") or 0),
                cost_usd=float(llm.get("cost_usd") or 0.0),
            ),
            messages_today=MessagesUsage(
                inbound=_coerce_int_map(msgs.get("inbound")),
                outbound_last_24h=int(msgs.get("outbound_last_24h") or 0),
            ),
            http_today=HttpUsage(
                total=int(http.get("total") or 0),
                by_path=_coerce_int_map(http.get("by_path")),
            ),
            budget=OrgBudgetSnapshot(
                org_cap_micro_usd=_optional_int(budget.get("org_cap_micro_usd")),
                org_mtd_micro_usd=int(budget.get("org_mtd_micro_usd") or 0),
                key_cap_micro_usd=_optional_int(budget.get("key_cap_micro_usd")),
                key_mtd_micro_usd=int(budget.get("key_mtd_micro_usd") or 0),
            ),
            raw=data,
        )


class AnalyticsService:
    def __init__(self, api_url: str, client_factory: Any) -> None:
        self._api_url = api_url
        self._client_factory = client_factory

    async def get_org(self) -> OrgAnalytics:
        async with self._client_factory() as client:
            url = join_http(self._api_url, "/v1/org/analytics")
            data = await request_json(client, "GET", url)
        if not isinstance(data, dict):
            raise DaguitoError("expected JSON object from GET /v1/org/analytics")
        return OrgAnalytics.from_wire(data)


def _coerce_int_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(k): int(v) for k, v in value.items() if isinstance(v, (int, float))}


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
