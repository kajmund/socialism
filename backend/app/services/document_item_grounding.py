"""Validate Q&A source links at the mutation boundary."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import DocumentKnowledgeItem, StoredObject
from app.services.knowledge.persistence import current_text_units


async def validated_unit_ids(
    session: AsyncSession, item: DocumentKnowledgeItem, unit_ids: Sequence[str]
) -> list[str]:
    from app.services.document_knowledge import supporting_text_unit_ids

    source = await session.get(StoredObject, item.source_object_id)
    if source is None or source.customer_id != item.customer_id:
        raise ValueError("Document knowledge source is outside customer scope")
    units = await current_text_units(session, item.source_object_id)
    linked = set()
    for anchor in item.anchors:
        linked.update(supporting_text_unit_ids(
            locator=anchor.locator, exact_quote=anchor.exact_text, units=units,
        ))
    supplied = list(dict.fromkeys(unit_ids))
    valid = {unit.id for unit in units if unit.customer_id == item.customer_id}
    if supplied and not set(supplied).issubset(valid & linked):
        raise ValueError("TextUnit links must ground the quote in the current source document")
    if not supplied:
        return [unit.id for unit in units if unit.id in linked]
    return supplied
