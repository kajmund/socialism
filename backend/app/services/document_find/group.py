"""Group TextUnit / KnowledgeHit results to unique document_ids without LLM."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.services.overgraph.model import KnowledgeHit


def document_ids_from_hits(hits: Sequence[KnowledgeHit]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for hit in hits:
        document_id = str(hit.props.get("document_id") or "")
        if not document_id or document_id in seen:
            continue
        seen.add(document_id)
        ordered.append(document_id)
    return ordered


def dedupe_document_ids(ids: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for document_id in ids:
        if not document_id or document_id in seen:
            continue
        seen.add(document_id)
        ordered.append(document_id)
    return ordered
