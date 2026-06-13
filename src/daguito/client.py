"""Top-level admin client — `Daguito(api_url, api_key)`.

Holds the three admin sub-services. Existing top-level helpers
(`run_webhook`, `WebhookStreamSession`, `KnowledgeSession`, `upload_file`)
are unchanged — this client is purely additive for the admin path.

Usage:

    from daguito import Daguito

    client = Daguito(api_url="https://ingest.daguito.com", api_key="dgsk_acc_…")
    keys = await client.account_keys.list()
    new = await client.account_keys.create(name="prod", monthly_budget_micro_usd=5_000_000)
    print(new.plaintext)  # shown ONCE
"""

from __future__ import annotations

from .admin_account_keys import AccountKeysService, make_client_factory
from .admin_budgets import BudgetsService
from .admin_flows import FlowsService
from .admin_public_keys import PublicKeysService
from .templates import TemplatesService


class Daguito:
    """Programmatic admin client for API keys + budgets.

    `api_url` is the Daguito ingest root and defaults to
    https://ingest.daguito.com when omitted. `api_key` is typically a
    `dgsk_acc_…` account key; the dashboard session JWT is also accepted
    on the wire.
    """

    def __init__(self, api_url: str | None = None, api_key: str = "") -> None:
        api_url = api_url or "https://ingest.daguito.com"
        if not api_key:
            raise ValueError("api_key is required")
        self.api_url = api_url
        self.api_key = api_key
        factory = make_client_factory(api_key)
        self.account_keys = AccountKeysService(api_url, factory)
        self.public_keys = PublicKeysService(api_url, factory)
        self.budgets = BudgetsService(api_url, factory)
        self.flows = FlowsService(api_url, factory)
        self.templates = TemplatesService(api_url, factory)
