"""TextUnit fixtures backed by OverGraph (the authoritative store)."""

from __future__ import annotations

from app.services.knowledge.persistence import get_current_document_version
from app.services.knowledge.scope import customer_scope, shared_scope
from app.services.knowledge.units import hash_text
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.model import TextUnitView, TextUnitWrite
from app.services.overgraph.research import load_text_units as load_text_unit_views
from app.services.overgraph.text_units import (
    load_all_domain_text_units,
    load_domain_text_units,
)
from app.services.overgraph.write import upsert_text_unit


def _scope(fields: dict[str, object]) -> tuple[str, str, int | None]:
    customer_id = fields.get("customer_id")
    scope_key = fields.get("scope_key")
    if scope_key is None:
        scope_key = "shared" if customer_id is None else f"customer:{customer_id}"
    scope_type = str(fields.get("scope_type") or ("shared" if scope_key == "shared" else "customer"))
    if customer_id is None and scope_type == "customer":
        customer_id = int(str(scope_key).split(":", 1)[1])
    return scope_type, str(scope_key), customer_id if isinstance(customer_id, int) else None


def text_unit_view(*, text: str, **fields: object) -> TextUnitView:
    """In-memory TextUnitView with a real content hash. Nothing is persisted."""
    digest = hash_text(text)
    scope_type, scope_key, customer_id = _scope(fields)
    extra = fields.get("extra") or fields.get("metadata") or {}
    return TextUnitView(
        id=str(fields.get("id") or digest),
        document_id=str(fields.get("document_id") or ""),
        document_version_id=str(fields.get("document_version_id") or ""),
        scope_key=scope_key,
        scope_type=scope_type,
        text=text,
        content_hash=digest,
        ordinal=int(fields.get("ordinal") or 0),  # type: ignore[arg-type]
        section_id=fields.get("section_id"),  # type: ignore[arg-type]
        customer_id=customer_id,
        locator=fields.get("locator"),  # type: ignore[arg-type]
        page_start=fields.get("page_start"),  # type: ignore[arg-type]
        page_end=fields.get("page_end"),  # type: ignore[arg-type]
        valid_from=fields.get("valid_from"),  # type: ignore[arg-type]
        valid_to=fields.get("valid_to"),  # type: ignore[arg-type]
        extra=dict(extra),  # type: ignore[arg-type]
    )


def text_unit_write(view: TextUnitView) -> TextUnitWrite:
    scope = customer_scope(view.customer_id) if view.scope_type == "customer" else shared_scope()
    return TextUnitWrite(
        unit_id=view.id,
        scope=scope,
        document_id=view.document_id,
        document_version_id=view.document_version_id,
        text=view.text,
        content_hash=view.content_hash,
        ordinal=view.ordinal,
        section_id=view.section_id,
        locator=view.locator,
        page_start=view.page_start,
        page_end=view.page_end,
        valid_from=view.valid_from,
        valid_to=view.valid_to,
        metadata=dict(view.extra),
    )


async def persisted_text_unit(session, *, text: str, **fields: object) -> TextUnitView:
    """Persist a TextUnit node in OverGraph and return its view."""
    view = text_unit_view(text=text, **fields)
    upsert_text_unit(require_knowledge(), text_unit_write(view))
    return view


async def current_graph_units(session, document_id):
    """Current domain TextUnits for a document, read from OverGraph."""
    version = await get_current_document_version(session, document_id)
    if version is None:
        return []
    return load_domain_text_units(require_knowledge(), document_version_id=version.id)


def version_graph_units(version_id):
    """Domain TextUnits for a specific version, read from OverGraph."""
    return load_domain_text_units(require_knowledge(), document_version_id=version_id)


async def current_graph_views(session, document_id):
    """Current TextUnitViews (with scope) for a document, read from OverGraph."""
    version = await get_current_document_version(session, document_id)
    if version is None:
        return []
    return version_graph_views(version.id)


def all_graph_views() -> list[TextUnitView]:
    """Every TextUnit node in the catalog as a TextUnitView."""
    catalog = require_knowledge()
    ids = [unit.id for unit in load_all_domain_text_units(catalog)]
    return [view for view in load_text_unit_views(catalog, ids) if view is not None]


def version_graph_views(version_id):
    """TextUnitViews (with scope) for a specific version, read from OverGraph."""
    catalog = require_knowledge()
    ids = [unit.id for unit in load_domain_text_units(catalog, document_version_id=version_id)]
    return [view for view in load_text_unit_views(catalog, ids) if view is not None]
