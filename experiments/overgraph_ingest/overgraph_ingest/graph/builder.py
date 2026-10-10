"""Turn a segmented document into OverGraph node and edge drafts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from overgraph_ingest.extraction.model import ExtractedDocument
from overgraph_ingest.graph.schema import (
    COLLECTION,
    CONTAINS,
    DOCUMENT,
    HAS_SECTION,
    NEXT,
    PARENT_OF,
    PREVIOUS,
    STRUCTURE,
    TEXT_UNIT,
)
from overgraph_ingest.segmentation.structural import SegmentedDocument


@dataclass(frozen=True)
class NodeDraft:
    labels: list[str]
    key: str
    props: dict[str, object]


@dataclass(frozen=True)
class EdgeDraft:
    from_label: str
    from_key: str
    to_label: str
    to_key: str
    label: str


@dataclass
class GraphDraft:
    nodes: list[NodeDraft] = field(default_factory=list)
    edges: list[EdgeDraft] = field(default_factory=list)
    document_key: str = ""
    document_props: dict[str, object] = field(default_factory=dict)


def build_graph(
    *,
    collection_id: str,
    document_id: str,
    document_version_id: str,
    relative_path: str,
    source_hash: str,
    extracted: ExtractedDocument,
    segmented: SegmentedDocument,
    segmentation_version: str,
    status: str,
    extra_document_props: dict[str, object] | None = None,
) -> GraphDraft:
    exclusions = [
        {
            "text": block.text[:200],
            "page": block.page,
            "reason": block.exclude_reason,
        }
        for block in extracted.exclusions()
    ]
    document_props: dict[str, object] = {
        "document_id": document_id,
        "document_version_id": document_version_id,
        "collection_id": collection_id,
        "relative_path": relative_path,
        "source_hash": source_hash,
        "mime_type": extracted.mime_type,
        "status": status,
        "page_count": len(extracted.pages),
        "char_count": len(segmented.canonical_text),
        "expected_text_units": len(segmented.units),
        "extraction_version": extracted.extraction_version,
        "segmentation_version": segmentation_version,
        "exclusions_json": json.dumps(exclusions, ensure_ascii=False),
    }
    if extracted.error:
        document_props["error"] = extracted.error
    if extra_document_props:
        document_props.update(extra_document_props)

    nodes = [
        NodeDraft(["Collection"], collection_id, {"collection_id": collection_id}),
        NodeDraft(["Document"], document_id, document_props),
    ]
    edges = [
        EdgeDraft(COLLECTION, collection_id, DOCUMENT, document_id, CONTAINS),
    ]
    for structure in segmented.structures:
        nodes.append(
            NodeDraft(
                [STRUCTURE],
                structure.structure_id,
                _clean(
                    {
                        "structure_id": structure.structure_id,
                        "document_id": document_id,
                        "document_version_id": document_version_id,
                        "path": structure.path,
                        "title": structure.title,
                        "level": structure.level,
                        "ordinal": structure.ordinal,
                        "clause_number": structure.clause_number,
                        "page_start": structure.page_start,
                        "page_end": structure.page_end,
                        "char_start": structure.char_start,
                        "char_end": structure.char_end,
                    }
                ),
            )
        )
        edges.append(
            EdgeDraft(DOCUMENT, document_id, STRUCTURE, structure.structure_id, HAS_SECTION)
        )
        if structure.parent_id is not None:
            edges.append(
                EdgeDraft(
                    STRUCTURE,
                    structure.parent_id,
                    STRUCTURE,
                    structure.structure_id,
                    PARENT_OF,
                )
            )

    previous_unit: str | None = None
    for unit in segmented.units:
        nodes.append(
            NodeDraft(
                [TEXT_UNIT],
                unit.text_unit_id,
                _clean(
                    {
                        "document_id": document_id,
                        "document_version_id": document_version_id,
                        "structure_id": unit.structure_id,
                        "text": unit.text,
                        "normalized_text": unit.normalized_text,
                        "content_hash": unit.content_hash,
                        "page_start": unit.page_start,
                        "page_end": unit.page_end,
                        "char_start": unit.char_start,
                        "char_end": unit.char_end,
                        "sequence": unit.sequence,
                        "segmentation_version": segmentation_version,
                    }
                ),
            )
        )
        edges.append(
            EdgeDraft(STRUCTURE, unit.structure_id, TEXT_UNIT, unit.text_unit_id, CONTAINS)
        )
        if previous_unit is not None:
            edges.append(EdgeDraft(TEXT_UNIT, previous_unit, TEXT_UNIT, unit.text_unit_id, NEXT))
            edges.append(
                EdgeDraft(TEXT_UNIT, unit.text_unit_id, TEXT_UNIT, previous_unit, PREVIOUS)
            )
        previous_unit = unit.text_unit_id

    return GraphDraft(
        nodes=nodes,
        edges=edges,
        document_key=document_id,
        document_props=document_props,
    )


def _clean(props: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in props.items() if value is not None}
