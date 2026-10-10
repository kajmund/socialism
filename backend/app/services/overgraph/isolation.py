"""Tenant guards that run before ranking, not after a mixed top-k."""

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.labels import visible_scope_keys


def can_reference(owner: KnowledgeTenantScope, target_scope: str) -> bool:
    return target_scope == owner.scope_key or (
        owner.customer_id is not None and target_scope == "shared"
    )


def is_visible(scope_key: str, customer_id: int | None) -> bool:
    return scope_key in visible_scope_keys(customer_id)


def assert_visible(scope_key: str, customer_id: int | None) -> None:
    if not is_visible(scope_key, customer_id):
        raise PermissionError(f"graph node {scope_key} is outside the caller tenant")
