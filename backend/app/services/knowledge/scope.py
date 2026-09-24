"""Hard tenant boundary for knowledge objects.

Customer/private knowledge may consume shared/global knowledge.
Customer/private knowledge must never be promoted into shared/global.
Missing or ambiguous persist/reuse scope fails closed — never infer shared.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, event, or_
from sqlalchemy.sql.elements import ColumnElement

SCOPE_SHARED = "shared"
SCOPE_CUSTOMER = "customer"
SCOPE_TYPES = frozenset({SCOPE_SHARED, SCOPE_CUSTOMER})
ScopeType = Literal["shared", "customer"]
SHARED_SCOPE_KEY = "shared"


class KnowledgeScopeError(ValueError):
    """Persist/reuse scope is missing, ambiguous, or would leak across tenants."""


@dataclass(frozen=True)
class KnowledgeTenantScope:
    """Ownership of a persisted knowledge object.

    ``customer_id`` is null only when ``scope_type='shared'``.
    """

    scope_type: ScopeType
    customer_id: int | None = None

    def __post_init__(self) -> None:
        _validate_pair(self.scope_type, self.customer_id)

    @property
    def scope_key(self) -> str:
        if self.scope_type == SCOPE_SHARED:
            return SHARED_SCOPE_KEY
        return customer_scope_key(self.customer_id)


def shared_scope() -> KnowledgeTenantScope:
    return KnowledgeTenantScope(scope_type=SCOPE_SHARED, customer_id=None)


def customer_scope(customer_id: int) -> KnowledgeTenantScope:
    if customer_id is None:
        raise KnowledgeScopeError("customer scope requires customer_id")
    return KnowledgeTenantScope(scope_type=SCOPE_CUSTOMER, customer_id=int(customer_id))


def customer_scope_key(customer_id: int | None) -> str:
    if customer_id is None:
        raise KnowledgeScopeError("customer scope requires customer_id")
    return f"customer:{int(customer_id)}"


def object_scope(
    scope_type: str | None,
    customer_id: int | None,
) -> KnowledgeTenantScope:
    """Fail closed. Never infer shared from a missing customer_id."""
    if scope_type is None or not str(scope_type).strip():
        raise KnowledgeScopeError(
            "knowledge persist/reuse requires explicit scope_type; do not infer shared"
        )
    normalized = str(scope_type).strip()
    if normalized not in SCOPE_TYPES:
        raise KnowledgeScopeError(f"unknown knowledge scope_type: {scope_type!r}")
    return KnowledgeTenantScope(scope_type=normalized, customer_id=customer_id)  # type: ignore[arg-type]


def require_persist_scope(
    *,
    scope: KnowledgeTenantScope | None = None,
    customer_id: int | None = None,
    scope_type: str | None = None,
) -> KnowledgeTenantScope:
    """Resolve a write scope. ``customer_id`` alone means customer. Never infer shared."""
    if scope is not None:
        if customer_id is not None and scope.scope_type == SCOPE_CUSTOMER:
            if scope.customer_id != int(customer_id):
                raise KnowledgeScopeError("customer_id does not match persist scope")
        if customer_id is not None and scope.scope_type == SCOPE_SHARED:
            raise KnowledgeScopeError("shared scope cannot carry customer_id")
        if scope_type is not None and scope.scope_type != scope_type:
            raise KnowledgeScopeError("scope_type does not match persist scope")
        return scope
    if scope_type == SCOPE_SHARED:
        if customer_id is not None:
            raise KnowledgeScopeError("shared scope cannot carry customer_id")
        return shared_scope()
    if customer_id is None:
        raise KnowledgeScopeError(
            "knowledge persist/reuse requires explicit scope; do not infer shared"
        )
    return customer_scope(int(customer_id))


def persist_scope_fields(scope: KnowledgeTenantScope) -> dict[str, str | int | None]:
    return {
        "scope_type": scope.scope_type,
        "scope_key": scope.scope_key,
        "customer_id": scope.customer_id,
    }


def scope_from_row(row: object) -> KnowledgeTenantScope:
    scope_type = getattr(row, "scope_type", None)
    customer_id = getattr(row, "customer_id", None)
    scope_key = getattr(row, "scope_key", None)
    if scope_type in (None, "") and scope_key in (None, "") and customer_id is not None:
        return customer_scope(int(customer_id))
    resolved = object_scope(scope_type, customer_id)
    if scope_key not in (None, "") and scope_key != resolved.scope_key:
        raise KnowledgeScopeError(
            f"scope_key {scope_key!r} does not match {resolved.scope_key!r}"
        )
    return resolved


def fill_row_scope(target: object) -> KnowledgeTenantScope:
    """Complete customer scope from customer_id. Never invent shared."""
    scope_type = getattr(target, "scope_type", None)
    customer_id = getattr(target, "customer_id", None)
    scope_key = getattr(target, "scope_key", None)
    if scope_type in (None, "") and scope_key in (None, ""):
        visibility = getattr(target, "visibility", None)
        if visibility == "public" and customer_id is None:
            resolved = shared_scope()
        else:
            resolved = require_persist_scope(customer_id=customer_id)
    elif scope_key == SHARED_SCOPE_KEY and scope_type in (None, ""):
        resolved = shared_scope()
    elif isinstance(scope_key, str) and scope_key.startswith("customer:") and scope_type in (None, ""):
        resolved = object_scope(SCOPE_CUSTOMER, customer_id)
        if scope_key != resolved.scope_key:
            raise KnowledgeScopeError(
                f"scope_key {scope_key!r} does not match customer_id {customer_id!r}"
            )
    else:
        resolved = object_scope(scope_type, customer_id)
        if scope_key not in (None, "") and scope_key != resolved.scope_key:
            raise KnowledgeScopeError(
                f"scope_key {scope_key!r} does not match {resolved.scope_key!r}"
            )
    target.scope_type = resolved.scope_type
    target.scope_key = resolved.scope_key
    target.customer_id = resolved.customer_id
    return resolved


def visible_to(*, owned: KnowledgeTenantScope, reader_customer_id: int) -> bool:
    """Customer readers see their own objects plus shared. Never another customer."""
    if reader_customer_id is None:
        raise KnowledgeScopeError("knowledge read requires reader customer_id")
    if owned.scope_type == SCOPE_SHARED:
        return True
    return owned.customer_id == int(reader_customer_id)


def assert_not_promoted(
    *,
    source: KnowledgeTenantScope,
    target: KnowledgeTenantScope,
) -> None:
    if source.scope_type == SCOPE_CUSTOMER and target.scope_type == SCOPE_SHARED:
        raise KnowledgeScopeError(
            "customer knowledge cannot be promoted or reused as shared"
        )


def assert_same_scope(
    left: KnowledgeTenantScope,
    right: KnowledgeTenantScope,
    *,
    action: str,
) -> None:
    if left != right:
        raise KnowledgeScopeError(f"{action} cannot merge distinct knowledge scopes")


def assert_relationship_scopes(
    *,
    edge: KnowledgeTenantScope,
    from_scope: KnowledgeTenantScope | None,
    to_scope: KnowledgeTenantScope | None,
    relation: str,
) -> None:
    """Private attributes/edges stay tenant-scoped. SAME_AS cannot merge scopes."""
    for endpoint in (from_scope, to_scope):
        if endpoint is None:
            continue
        assert_not_promoted(source=endpoint, target=edge)
        if endpoint.scope_type == SCOPE_CUSTOMER and edge.scope_type == SCOPE_CUSTOMER:
            if endpoint.customer_id != edge.customer_id:
                raise KnowledgeScopeError("relationship customer does not match endpoint")
    if from_scope is None or to_scope is None:
        return
    if (
        from_scope.scope_type == SCOPE_CUSTOMER
        and to_scope.scope_type == SCOPE_CUSTOMER
        and from_scope.customer_id != to_scope.customer_id
    ):
        raise KnowledgeScopeError("cannot link two customer scopes")
    if relation == "SAME_AS":
        assert_same_scope(from_scope, to_scope, action="SAME_AS")
    if edge.scope_type == SCOPE_SHARED and (
        from_scope.scope_type != SCOPE_SHARED or to_scope.scope_type != SCOPE_SHARED
    ):
        raise KnowledgeScopeError("shared relationships may only connect shared nodes")


def visible_to_customer_clause(
    scope_type_col: ColumnElement[str],
    customer_id_col: ColumnElement[int | None],
    reader_customer_id: int,
) -> ColumnElement[bool]:
    if reader_customer_id is None:
        raise KnowledgeScopeError("knowledge read requires reader customer_id")
    return or_(
        scope_type_col == SCOPE_SHARED,
        and_(
            scope_type_col == SCOPE_CUSTOMER,
            customer_id_col == int(reader_customer_id),
        ),
    )


def knowledge_scope_check_sql() -> str:
    return (
        "(scope_type = 'shared' AND customer_id IS NULL AND scope_key = 'shared') OR "
        "(scope_type = 'customer' AND customer_id IS NOT NULL AND "
        "scope_key = 'customer:' || customer_id)"
    )


def bind_scoped_mapper(model: type[object]) -> None:
    event.listen(model, "before_insert", _enforce_row_scope)
    event.listen(model, "before_update", _enforce_row_scope)


def _enforce_row_scope(mapper: object, connection: object, target: object) -> None:
    del mapper, connection
    fill_row_scope(target)


def _validate_pair(scope_type: str, customer_id: int | None) -> None:
    if scope_type == SCOPE_SHARED:
        if customer_id is not None:
            raise KnowledgeScopeError("shared scope cannot have customer_id")
        return
    if scope_type == SCOPE_CUSTOMER:
        if customer_id is None:
            raise KnowledgeScopeError("customer scope requires customer_id")
        return
    raise KnowledgeScopeError(f"unknown knowledge scope_type: {scope_type!r}")
