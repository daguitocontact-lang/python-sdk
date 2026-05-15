"""Dataclasses for the admin client (account keys, public flow keys, budgets).

JSON wire-field names mirror the JS / Go SDKs exactly (`key_prefix`,
`monthly_budget_micro_usd`, etc). Field accessors stay snake_case on the
Python side — they map 1:1 with the wire shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AccountKey:
    id: str
    name: str
    key_prefix: str
    monthly_budget_micro_usd: int | None
    current_mtd_micro_usd: int
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


@dataclass
class AccountKeyCreated(AccountKey):
    """Returned exactly once by `account_keys.create`. The `plaintext` token
    is never re-readable — persist it now or revoke and recreate."""

    plaintext: str = ""


@dataclass
class PublicKey:
    id: str
    flow_id: str
    name: str
    key_prefix: str
    allowed_origins: list[str]
    monthly_budget_micro_usd: int | None
    current_mtd_micro_usd: int
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


@dataclass
class PublicKeyCreated(PublicKey):
    plaintext: str = ""


@dataclass
class OrgBudget:
    monthly_budget_micro_usd: int | None
    current_mtd_micro_usd: int
    mtd_reset_at: str | None


def parse_account_key(data: dict[str, Any]) -> AccountKey:
    return AccountKey(
        id=str(data.get("id", "")),
        name=str(data.get("name", "")),
        key_prefix=str(data.get("key_prefix", "")),
        monthly_budget_micro_usd=_optional_int(data.get("monthly_budget_micro_usd")),
        current_mtd_micro_usd=int(data.get("current_mtd_micro_usd") or 0),
        created_at=str(data.get("created_at") or ""),
        last_used_at=_optional_str(data.get("last_used_at")),
        revoked_at=_optional_str(data.get("revoked_at")),
    )


def parse_account_key_created(data: dict[str, Any]) -> AccountKeyCreated:
    base = parse_account_key(data)
    return AccountKeyCreated(
        id=base.id,
        name=base.name,
        key_prefix=base.key_prefix,
        monthly_budget_micro_usd=base.monthly_budget_micro_usd,
        current_mtd_micro_usd=base.current_mtd_micro_usd,
        created_at=base.created_at,
        last_used_at=base.last_used_at,
        revoked_at=base.revoked_at,
        plaintext=str(data.get("plaintext") or ""),
    )


def parse_public_key(data: dict[str, Any]) -> PublicKey:
    origins = data.get("allowed_origins") or []
    return PublicKey(
        id=str(data.get("id", "")),
        flow_id=str(data.get("flow_id", "")),
        name=str(data.get("name", "")),
        key_prefix=str(data.get("key_prefix", "")),
        allowed_origins=[str(o) for o in origins if isinstance(o, str)],
        monthly_budget_micro_usd=_optional_int(data.get("monthly_budget_micro_usd")),
        current_mtd_micro_usd=int(data.get("current_mtd_micro_usd") or 0),
        created_at=str(data.get("created_at") or ""),
        last_used_at=_optional_str(data.get("last_used_at")),
        revoked_at=_optional_str(data.get("revoked_at")),
    )


def parse_public_key_created(data: dict[str, Any]) -> PublicKeyCreated:
    base = parse_public_key(data)
    return PublicKeyCreated(
        id=base.id,
        flow_id=base.flow_id,
        name=base.name,
        key_prefix=base.key_prefix,
        allowed_origins=base.allowed_origins,
        monthly_budget_micro_usd=base.monthly_budget_micro_usd,
        current_mtd_micro_usd=base.current_mtd_micro_usd,
        created_at=base.created_at,
        last_used_at=base.last_used_at,
        revoked_at=base.revoked_at,
        plaintext=str(data.get("plaintext") or ""),
    )


def parse_org_budget(data: dict[str, Any]) -> OrgBudget:
    return OrgBudget(
        monthly_budget_micro_usd=_optional_int(data.get("monthly_budget_micro_usd")),
        current_mtd_micro_usd=int(data.get("current_mtd_micro_usd") or 0),
        mtd_reset_at=_optional_str(data.get("mtd_reset_at")),
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
