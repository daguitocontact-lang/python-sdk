"""Dataclasses for the `client.flows.*` admin surface.

Wire-field names mirror the Go / JS SDKs and the server JSON exactly.
Inputs use plain `dict` shapes (callers handle the structure they want),
outputs are typed dataclasses with `from_wire` factories so callers get
autocompletion + mypy coverage.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class UpsertResult:
    """Return shape of `flows.upsert_agent` and `flows.upsert_flow`.

    `created` is True on first upsert, False on subsequent ones —
    callers use it to log "agent X provisioned" vs "agent X updated".
    `webhook_id` is the stable streaming webhook id for the flow;
    `flows.upsert_flow` may return an empty string when the flow
    doesn't need a streaming webhook.
    """

    flow_id: str
    slug: str
    name: str
    webhook_id: str
    created: bool

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "UpsertResult":
        return cls(
            flow_id=str(data.get("flow_id") or ""),
            slug=str(data.get("slug") or ""),
            name=str(data.get("name") or ""),
            webhook_id=str(data.get("webhook_id") or ""),
            created=bool(data.get("created")),
        )


@dataclass(slots=True)
class Flow:
    """Projection of a flow row from `/api/public/flows`.

    Mirrors `flattenFlowRow` in the server. `steps`/`edges` are the
    builder graph; `metadata` is freeform; `created_by` may be null
    when the flow was provisioned by an account key.
    """

    id: str
    org_id: str
    name: str
    description: str | None
    trigger_type: str
    trigger_config: dict[str, Any]
    steps: list[Any]
    edges: list[Any]
    metadata: dict[str, Any]
    status: str
    channel_bindings: list[str]
    is_default: bool
    webhook_token: str | None
    created_at: str | None
    updated_at: str | None
    created_by: str | None

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "Flow":
        metadata_raw = data.get("metadata")
        trigger_config_raw = data.get("trigger_config")
        return cls(
            id=str(data.get("id") or ""),
            org_id=str(data.get("org_id") or ""),
            name=str(data.get("name") or ""),
            description=_optional_str(data.get("description")),
            trigger_type=str(data.get("trigger_type") or ""),
            trigger_config=trigger_config_raw if isinstance(trigger_config_raw, dict) else {},
            steps=list(data.get("steps") or []),
            edges=list(data.get("edges") or []),
            metadata=metadata_raw if isinstance(metadata_raw, dict) else {},
            status=str(data.get("status") or ""),
            channel_bindings=[
                str(c) for c in (data.get("channel_bindings") or []) if isinstance(c, str)
            ],
            is_default=bool(data.get("is_default")),
            webhook_token=_optional_str(data.get("webhook_token")),
            created_at=_optional_str(data.get("created_at")),
            updated_at=_optional_str(data.get("updated_at")),
            created_by=_optional_str(data.get("created_by")),
        )


@dataclass(slots=True)
class FlowVersionSummary:
    """One row of `/api/public/flows/:id/versions`. Snapshot metadata only —
    use `restore_version` to bring its full graph back into the live flow.
    """

    id: str
    version: int
    name: str | None
    change_note: str | None
    created_at: str | None
    created_by: str | None

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> "FlowVersionSummary":
        return cls(
            id=str(data.get("id") or ""),
            version=int(data.get("version") or 0),
            name=_optional_str(data.get("name")),
            change_note=_optional_str(data.get("change_note")),
            created_at=_optional_str(data.get("created_at")),
            created_by=_optional_str(data.get("created_by")),
        )


@dataclass(slots=True)
class FlowToolRef:
    """One handler tool the agent may invoke. Only the `handler` kind is
    accepted by `upsert_agent` today — other kinds (mcp, http) are not
    wired through the public surface yet.
    """

    name: str
    config: dict[str, Any] | None = None
    kind: str = "handler"

    def to_wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "name": self.name}
        if self.config is not None:
            out["config"] = self.config
        return out


@dataclass(slots=True)
class AgentFlowSpec:
    """High-level spec for `flows.upsert_agent`. Identity is `(org, slug)`.

    `tools` accepts either typed `FlowToolRef` instances or plain dicts —
    plain dicts let callers pass raw JSON without importing the dataclass.
    """

    slug: str
    name: str
    provider: str
    model: str
    system_prompt: str
    temperature: float | None = None
    max_tokens: int | None = None
    history_turns: int | None = None
    recent_turns: int | None = None
    max_tool_iterations: int | None = None
    tools: list[FlowToolRef] | list[dict[str, Any]] | None = None
    memory_facts_schema: Any = None
    memory_summary_config: Any = None
    context_memory_keys: list[str] | None = None

    def to_wire(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "slug": self.slug,
            "name": self.name,
            "provider": self.provider,
            "model": self.model,
            "system_prompt": self.system_prompt,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        if self.history_turns is not None:
            body["history_turns"] = self.history_turns
        if self.recent_turns is not None:
            body["recent_turns"] = self.recent_turns
        if self.max_tool_iterations is not None:
            body["max_tool_iterations"] = self.max_tool_iterations
        if self.tools is not None:
            body["tools"] = [
                t.to_wire() if isinstance(t, FlowToolRef) else t for t in self.tools
            ]
        if self.memory_facts_schema is not None:
            body["memory_facts_schema"] = self.memory_facts_schema
        if self.memory_summary_config is not None:
            body["memory_summary_config"] = self.memory_summary_config
        if self.context_memory_keys is not None:
            body["context_memory_keys"] = list(self.context_memory_keys)
        return body


@dataclass(slots=True)
class FlowGraphNode:
    id: str
    type: str | None = None
    kind: str | None = None
    config: dict[str, Any] | None = None
    position: dict[str, float] | None = None

    def to_wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id}
        if self.type is not None:
            out["type"] = self.type
        if self.kind is not None:
            out["kind"] = self.kind
        if self.config is not None:
            out["config"] = self.config
        if self.position is not None:
            out["position"] = self.position
        return out


@dataclass(slots=True)
class FlowGraphEdge:
    id: str
    source: str
    target: str
    source_handle: str | None = None

    def to_wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "source": self.source, "target": self.target}
        if self.source_handle is not None:
            # Camel-case on the wire: matches the upsert-flow Elysia schema.
            out["sourceHandle"] = self.source_handle
        return out


@dataclass(slots=True)
class FlowGraph:
    nodes: list[FlowGraphNode] | list[dict[str, Any]] = field(default_factory=list)
    edges: list[FlowGraphEdge] | list[dict[str, Any]] = field(default_factory=list)

    def to_wire(self) -> dict[str, Any]:
        return {
            "nodes": [
                n.to_wire() if isinstance(n, FlowGraphNode) else n for n in self.nodes
            ],
            "edges": [
                e.to_wire() if isinstance(e, FlowGraphEdge) else e for e in self.edges
            ],
        }


@dataclass(slots=True)
class FlowSpec:
    """Spec for `flows.upsert_flow` — generic custom graph, not the agent
    preset. `trigger_type` defaults to "message" server-side.
    """

    slug: str
    name: str
    graph: FlowGraph | dict[str, Any]
    trigger_type: str | None = None

    def to_wire(self) -> dict[str, Any]:
        body: dict[str, Any] = {"slug": self.slug, "name": self.name}
        if self.trigger_type is not None:
            body["trigger_type"] = self.trigger_type
        body["graph"] = (
            self.graph.to_wire() if isinstance(self.graph, FlowGraph) else self.graph
        )
        return body


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
