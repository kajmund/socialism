"""Inventory API: exact, paginated document-property lookup from OverGraph.

D1: the authoritative exact lookup runs in OverGraph's secondary indexes; the
response separates supported claims from unverified candidates and pages each
list with a keyset cursor.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import require_admin
from app.services.document_properties.graph_persistence import (
    LookupPagination,
    lookup_document_properties,
)
from app.services.document_properties.model import DocumentPropertyHit
from app.services.overgraph.catalogs import get_runtime

router = APIRouter(
    prefix="/document-properties",
    tags=["document-properties"],
    dependencies=[Depends(require_admin)],
)


def _parse_value(raw: str | None) -> bool | str | None:
    if raw is None:
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    return raw


def _hit(item: DocumentPropertyHit) -> dict:
    return {
        "document_id": item.document_id,
        "class_id": item.class_id,
        "value": item.value,
        "polarity": item.polarity,
        "taxonomy_version": item.taxonomy_version,
        "status": item.status,
        "source_unit_keys": list(item.source_unit_keys),
    }


def _page(items: list[DocumentPropertyHit], after: int | None) -> dict:
    return {"items": [_hit(item) for item in items], "after": after}


@router.get("/lookup")
async def document_properties_lookup(
    *,
    customer_id: int = Query(ge=1),
    class_id: str = Query(min_length=1, max_length=200),
    value: str | None = Query(default=None, max_length=200),
    include_candidates: bool = True,
    limit: int = Query(default=100, ge=1, le=1000),
    supported_after: int | None = Query(default=None, ge=0),
    candidate_after: int | None = Query(default=None, ge=0),
) -> dict:
    runtime = get_runtime()
    if runtime is None:
        raise HTTPException(status_code=503, detail="overgraph_unavailable")
    page = await lookup_document_properties(
        runtime.knowledge,
        customer_id=customer_id,
        class_id=class_id,
        value=_parse_value(value),
        include_candidates=include_candidates,
        page=LookupPagination(
            limit=limit,
            supported_after=supported_after,
            candidate_after=candidate_after,
        ),
    )
    return {
        "supported": _page(page.supported.items, page.supported.after),
        "candidates": _page(page.candidates.items, page.candidates.after),
    }
