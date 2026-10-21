"""OverGraph graph records mapped to the documents the Tantivy index stores."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import tantivy

from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.labels import FACT, TEXT_UNIT
from app.services.overgraph.model import GraphRecord
from app.services.tantivy_subwords import SUBWORD_FIELD, subword_parts

KIND_TEXT_UNIT = "text_unit"
KIND_FACT = "fact"
SV_ANALYZER = "sv_v1"


@dataclass(frozen=True)
class TextUnitDoc:
    key: str
    tenant_id: str
    document_id: str
    document_version_id: str
    structure_id: str
    content_hash: str
    text: str


@dataclass(frozen=True)
class FactDoc:
    key: str
    tenant_id: str
    status: str
    valid_from_ms: int
    valid_to_ms: int
    content_hash: str
    text: str




def iter_text_units(catalog: Catalog, *, page_size: int = 1000):
    """Yield TextUnit documents from the OverGraph catalog, keyset-paginated."""
    after: int | None = None
    while True:
        rows, after = catalog.query_nodes(
            label_filter={"labels": [TEXT_UNIT], "mode": "all"},
            limit=page_size,
            after=after,
        )
        for row in rows:
            yield _unit(row)
        if after is None or not rows:
            return


def _unit(row: GraphRecord) -> TextUnitDoc:
    props = row.props
    return TextUnitDoc(
        key=row.key,
        tenant_id=str(props.get("scope_key") or ""),
        document_id=str(props.get("document_id") or ""),
        document_version_id=str(props.get("document_version_id") or ""),
        structure_id=str(props.get("section_id") or ""),
        content_hash=str(props.get("content_hash") or ""),
        text=str(props.get("text") or ""),
    )


def _document(unit: TextUnitDoc) -> tantivy.Document:
    document = tantivy.Document()
    document.add_text("kind", KIND_TEXT_UNIT)
    document.add_text("key", unit.key)
    document.add_text("tenant_id", unit.tenant_id)
    document.add_text("document_id", unit.document_id)
    document.add_text("document_version_id", unit.document_version_id)
    document.add_text("structure_id", unit.structure_id)
    document.add_text("content_hash", unit.content_hash)
    document.add_integer("valid_from_ms", 0)
    document.add_integer("valid_to_ms", 0)
    document.add_text("text", unit.text)
    return document


def _fact_document(fact: FactDoc) -> tantivy.Document:
    document = tantivy.Document()
    document.add_text("kind", KIND_FACT)
    document.add_text("key", fact.key)
    document.add_text("tenant_id", fact.tenant_id)
    document.add_text("status", fact.status)
    document.add_text("content_hash", fact.content_hash)
    document.add_integer("valid_from_ms", fact.valid_from_ms)
    document.add_integer("valid_to_ms", fact.valid_to_ms)
    document.add_text("text", fact.text)
    parts = subword_parts(fact.text)
    if parts:
        document.add_text(SUBWORD_FIELD, " ".join(parts))
    return document


def _fact(row: GraphRecord) -> FactDoc:
    props = row.props
    text = str(props.get("normalized_text") or "")
    return FactDoc(
        key=row.key,
        tenant_id=str(props.get("scope_key") or ""),
        status=str(props.get("status") or ""),
        valid_from_ms=int(props.get("valid_at_ms") or 0),
        valid_to_ms=int(props.get("invalid_at_ms") or 0),
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
    )


def iter_facts(catalog: Catalog, *, page_size: int = 1000):
    """Yield Fact documents from the OverGraph catalog, keyset-paginated."""
    after: int | None = None
    while True:
        rows, after = catalog.query_nodes(
            label_filter={"labels": [FACT], "mode": "all"},
            limit=page_size,
            after=after,
        )
        for row in rows:
            yield _fact(row)
        if after is None or not rows:
            return


