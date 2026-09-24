"""Service re-export of the knowledge tenant scope model.

The source of truth lives in ``app.database.knowledge_scope`` so Alembic
and ORM models can import it without loading runtime Settings.
"""

from app.database.knowledge_scope import (
    SCOPE_CUSTOMER,
    SCOPE_SHARED,
    SCOPE_TYPES,
    SHARED_SCOPE_KEY,
    KnowledgeScopeError,
    KnowledgeTenantScope,
    ScopeType,
    assert_not_promoted,
    assert_relationship_scopes,
    assert_same_scope,
    bind_scoped_mapper,
    customer_scope,
    customer_scope_key,
    fill_row_scope,
    knowledge_scope_check_sql,
    object_scope,
    persist_scope_fields,
    require_persist_scope,
    scope_from_row,
    shared_scope,
    visible_to,
    visible_to_customer_clause,
)

__all__ = [
    "SCOPE_CUSTOMER",
    "SCOPE_SHARED",
    "SCOPE_TYPES",
    "SHARED_SCOPE_KEY",
    "KnowledgeScopeError",
    "KnowledgeTenantScope",
    "ScopeType",
    "assert_not_promoted",
    "assert_relationship_scopes",
    "assert_same_scope",
    "bind_scoped_mapper",
    "customer_scope",
    "customer_scope_key",
    "fill_row_scope",
    "knowledge_scope_check_sql",
    "object_scope",
    "persist_scope_fields",
    "require_persist_scope",
    "scope_from_row",
    "shared_scope",
    "visible_to",
    "visible_to_customer_clause",
]
