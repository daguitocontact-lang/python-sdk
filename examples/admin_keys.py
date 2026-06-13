"""Administer API keys + budgets programmatically with `Daguito`.

End-to-end flow:

    1. Connect with a `dgsk_acc_…` org-admin key.
    2. List existing account keys.
    3. Create a public flow key bound to `flow_id=$DAGUITO_FLOW_ID`,
       allowed_origins=["https://example.com"].
    4. Patch its budget to $50/month (50_000_000 micro-USD).
    5. List public keys to confirm the change.
    6. Revoke it.

Run:

    DAGUITO_API_URL=https://ingest.daguito.com \\
    DAGUITO_API_KEY=dgsk_acc_xxxxxxxxxxxx \\
    DAGUITO_FLOW_ID=flow_abc123 \\
    python examples/admin_keys.py
"""

from __future__ import annotations

import asyncio
import os

from daguito import Daguito


def env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"missing env var: {name}")
    return value


async def main() -> None:
    api_url = os.environ.get("DAGUITO_API_URL", "https://ingest.daguito.com")
    api_key = env("DAGUITO_API_KEY")
    flow_id = env("DAGUITO_FLOW_ID")

    # 1. Single client, three sub-services.
    client = Daguito(api_url=api_url, api_key=api_key)

    # 2. List existing org-wide account keys.
    keys = await client.account_keys.list()
    print(f"[account-keys] {len(keys)} key(s) active")
    for key in keys:
        print(f"  - {key.key_prefix}  name={key.name!r}  mtd={key.current_mtd_micro_usd}μ$")

    # 3. Mint a public flow key for embedding in a browser.
    created = await client.public_keys.create(
        flow_id=flow_id,
        name="example-com integration",
        allowed_origins=["https://example.com"],
    )
    print(f"[public-key]  created {created.key_prefix}")
    print(f"               plaintext (shown ONCE): {created.plaintext}")

    # 4. Cap the new key at $50/month (5e7 micro-USD).
    updated = await client.public_keys.set_budget(
        flow_id=flow_id,
        key_id=created.id,
        monthly_budget_micro_usd=50_000_000,
    )
    print(f"[public-key]  budget set to {updated.monthly_budget_micro_usd}μ$")

    # 5. Confirm via list.
    listing = await client.public_keys.list(flow_id)
    for key in listing:
        if key.id == created.id:
            print(f"[verify]     {key.key_prefix} budget={key.monthly_budget_micro_usd}μ$")

    # 6. Revoke (soft delete — never deleted in the DB).
    await client.public_keys.revoke(flow_id=flow_id, key_id=created.id)
    print(f"[public-key]  revoked {created.key_prefix}")


if __name__ == "__main__":
    asyncio.run(main())
