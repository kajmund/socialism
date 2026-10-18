"""Document view for classification. Title, opening, headings, stored metadata."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.graph.schema import DOCUMENT, STRUCTURE
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.retrieval.index import StoredUnit, load_published_units

OPENING_CHARS = 400
EXTRA_TOKEN_BUDGET = 1500
VARIANT_A = "A"
VARIANT_B = "B"
VARIANT_C = "C"


@dataclass(frozen=True)
class DocumentView:
    document_id: str
    relative_path: str
    title: str
    opening: str
    headings: tuple[str, ...]
    mime_type: str
    page_count: int | None
    char_count: int | None
    extra_text: str

    def a_state(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "title": self.title,
            "opening": self.opening,
            "headings": list(self.headings),
            "mime_type": self.mime_type,
            "page_count": self.page_count,
            "char_count": self.char_count,
        }

    def c_state(self) -> dict[str, object]:
        state = self.a_state()
        state["document_text"] = self.extra_text
        return state


def load_document_views(
    *,
    db_path: Path | None = None,
    dense_dimension: int | None = None,
    writer: GraphWriter | None = None,
    units: list[StoredUnit] | None = None,
    documents: list[dict[str, object]] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    opening_chars: int = OPENING_CHARS,
    extra_token_budget: int = EXTRA_TOKEN_BUDGET,
) -> list[DocumentView]:
    if writer is not None or (units is not None and documents is not None):
        return views_from_graph(
            writer=writer,
            units=units,
            documents=documents,
            structures=structures,
            opening_chars=opening_chars,
            extra_token_budget=extra_token_budget,
        )
    if db_path is None:
        raise ValueError("document views need a database or an injected graph")
    dimension = resolve_dimension(db_path, dense_dimension)
    db = open_database(db_path, dimension)
    try:
        return views_from_graph(
            writer=GraphWriter(db, batch_size=500),
            opening_chars=opening_chars,
            extra_token_budget=extra_token_budget,
        )
    finally:
        db.close()


def views_from_graph(
    *,
    writer: GraphWriter | None = None,
    units: list[StoredUnit] | None = None,
    documents: list[dict[str, object]] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    opening_chars: int = OPENING_CHARS,
    extra_token_budget: int = EXTRA_TOKEN_BUDGET,
) -> list[DocumentView]:
    docs = documents if documents is not None else _documents(writer)
    stored_units = units if units is not None else _units(writer)
    stored_structures = structures if structures is not None else _structures(writer)
    units_by_doc: dict[str, list[StoredUnit]] = {}
    for unit in stored_units:
        units_by_doc.setdefault(unit.document_id, []).append(unit)
    headings_by_doc = _headings(stored_structures)
    views = []
    for doc in docs:
        document_id = str(doc["document_id"])
        local = sorted(
            units_by_doc.get(document_id, []),
            key=lambda item: item.sequence or 0,
        )
        body = "".join(unit.text for unit in local)
        opening = body[:opening_chars]
        headings = headings_by_doc.get(document_id, ())
        title = headings[0] if headings else str(doc.get("relative_path") or document_id)
        views.append(
            DocumentView(
                document_id=document_id,
                relative_path=str(doc.get("relative_path") or ""),
                title=title,
                opening=opening,
                headings=headings,
                mime_type=str(doc.get("mime_type") or ""),
                page_count=_optional_int(doc.get("page_count")),
                char_count=_optional_int(doc.get("char_count")),
                extra_text=_extra_text(body, opening, extra_token_budget),
            )
        )
    return sorted(views, key=lambda view: view.relative_path)


def _documents(writer: GraphWriter | None) -> list[dict[str, object]]:
    if writer is None:
        raise ValueError("document views need documents or a writer")
    rows = []
    for node in writer.iter_nodes(DOCUMENT):
        props = dict(node.props)
        status = str(props.get("status") or "")
        if status and status != "PUBLISHED":
            continue
        rows.append(
            {
                "document_id": str(props.get("document_id") or node.key),
                "relative_path": str(props.get("relative_path") or ""),
                "mime_type": str(props.get("mime_type") or ""),
                "page_count": props.get("page_count"),
                "char_count": props.get("char_count"),
                "status": props.get("status"),
            }
        )
    return rows


def _units(writer: GraphWriter | None) -> list[StoredUnit]:
    if writer is None:
        return []
    return load_published_units(writer)


def _structures(writer: GraphWriter | None) -> dict[str, dict[str, object]]:
    if writer is None:
        return {}
    rows: dict[str, dict[str, object]] = {}
    for node in writer.iter_nodes(STRUCTURE):
        rows[str(node.key)] = dict(node.props)
    return rows


def _headings(structures: dict[str, dict[str, object]]) -> dict[str, tuple[str, ...]]:
    by_doc: dict[str, list[tuple[int, str]]] = {}
    for props in structures.values():
        title = str(props.get("title") or "").strip()
        if not title:
            continue
        document_id = str(props.get("document_id") or "")
        by_doc.setdefault(document_id, []).append((int(props.get("ordinal") or 0), title))
    return {
        document_id: tuple(title for _, title in sorted(rows))
        for document_id, rows in by_doc.items()
    }


def _extra_text(body: str, opening: str, token_budget: int) -> str:
    rest = body[len(opening) :] if body.startswith(opening) else body[len(opening) :]
    tokens = rest.split()
    return " ".join(tokens[:token_budget])


def _optional_int(raw: object) -> int | None:
    if raw is None or raw == "":
        return None
    return int(raw)
