"""ClassificationDefinition persistence on OverGraph."""

from __future__ import annotations

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.model import GraphRecord

from app.services.clause_ssr.graph import (
    find_by_prop,
    list_visible,
    prop_bool,
    prop_int,
    prop_str,
    upsert_scoped,
)
from app.services.clause_ssr.keys import classification_key
from app.services.clause_ssr.labels import CLASSIFICATION
from app.services.clause_ssr.types import LEVELS, ClassificationDefinition, ClassificationLevel


def upsert_classification(
    catalog: Catalog,
    *,
    scope: KnowledgeTenantScope,
    slug: str,
    question: str,
    category: str,
    level: ClassificationLevel = "clause",
    version: int | None = None,
) -> ClassificationDefinition:
    if level not in LEVELS:
        raise ValueError(f"unknown classification level: {level}")
    slug = slug.strip()
    question = question.strip()
    category = category.strip()
    if not slug or not question or not category:
        raise ValueError("slug, question, and category are required")
    current = _active_for_slug(catalog, scope.scope_key, slug)
    if current is not None and current.question == question and current.level == level:
        if current.category == category:
            return current
    next_version = version or ((current.version + 1) if current is not None else 1)
    if current is not None and current.version != next_version:
        _set_active(catalog, current, False, scope)
    key = classification_key(scope.scope_key, slug, next_version)
    row = upsert_scoped(
        catalog,
        kind=CLASSIFICATION,
        key=key,
        scope=scope,
        props={
            "slug": slug,
            "version": next_version,
            "question": question,
            "level": level,
            "category": category,
            "active": True,
        },
    )
    return _from_row(row)


def get_classification(catalog: Catalog, classification_id: str) -> ClassificationDefinition:
    row = catalog.get_by_key(CLASSIFICATION, classification_id)
    if row is None:
        raise KeyError(f"unknown classification {classification_id}")
    return _from_row(row)


def list_classifications(
    catalog: Catalog,
    *,
    customer_id: int | None,
    active_only: bool = True,
) -> list[ClassificationDefinition]:
    items = [_from_row(row) for row in list_visible(catalog, CLASSIFICATION, customer_id)]
    if active_only:
        items = [item for item in items if item.active]
    items.sort(key=lambda item: (item.category, item.slug, item.version))
    return items


def set_classification_active(
    catalog: Catalog,
    classification: ClassificationDefinition,
    *,
    scope: KnowledgeTenantScope,
    active: bool,
) -> ClassificationDefinition:
    if classification.scope_key != scope.scope_key:
        raise PermissionError("classification is outside the caller tenant")
    return _set_active(catalog, classification, active, scope)


def _set_active(
    catalog: Catalog,
    classification: ClassificationDefinition,
    active: bool,
    scope: KnowledgeTenantScope,
) -> ClassificationDefinition:
    row = upsert_scoped(
        catalog,
        kind=CLASSIFICATION,
        key=classification.id,
        scope=scope,
        props={
            "slug": classification.slug,
            "version": classification.version,
            "question": classification.question,
            "level": classification.level,
            "category": classification.category,
            "active": active,
        },
    )
    return _from_row(row)


def _active_for_slug(
    catalog: Catalog, scope_key: str, slug: str,
) -> ClassificationDefinition | None:
    found: list[ClassificationDefinition] = []
    for row in find_by_prop(catalog, CLASSIFICATION, "slug", slug):
        item = _from_row(row)
        if item.scope_key == scope_key and item.active:
            found.append(item)
    found.sort(key=lambda item: item.version, reverse=True)
    return found[0] if found else None


def _from_row(row: GraphRecord) -> ClassificationDefinition:
    level = prop_str(row, "level") or "clause"
    if level not in LEVELS:
        raise ValueError(f"corrupt classification level: {level}")
    return ClassificationDefinition(
        id=row.key,
        slug=prop_str(row, "slug"),
        version=prop_int(row, "version", 1),
        question=prop_str(row, "question"),
        level=level,  # type: ignore[arg-type]
        category=prop_str(row, "category"),
        active=prop_bool(row, "active"),
        scope_key=prop_str(row, "scope_key"),
    )
