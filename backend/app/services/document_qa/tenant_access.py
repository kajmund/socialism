"""Tenant Knowledge Owner selection for Document QA call sites.

Owner routes are explicit deployment config. When they are configured every
tenant graph access goes through the Owner; an empty config keeps the legacy
in-process path used by tests and local development until the cutover is
finished. There is no per-call fallback: a configured Owner that is missing or
unreachable fails loudly.
"""

from __future__ import annotations

from app.config import settings
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_registry import tenant_owner_client


def tenant_owners_enabled() -> bool:
    return bool(settings.overgraph_tenant_owner_sockets.strip())


def require_tenant_owner(customer_id: int) -> OwnerClient:
    if not tenant_owners_enabled():
        raise RuntimeError("tenant Knowledge Owner routes are not configured")
    return tenant_owner_client(customer_id)
