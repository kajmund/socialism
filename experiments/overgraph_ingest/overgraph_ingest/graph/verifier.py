"""Verify ingest against the extracted source, then against written nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from overgraph_ingest.extraction.model import ExtractedDocument
from overgraph_ingest.graph.builder import GraphDraft
from overgraph_ingest.graph.schema import DOCUMENT, STRUCTURE, TEXT_UNIT
from overgraph_ingest.segmentation.structural import SegmentedDocument, TextUnitDraft


@dataclass
class VerificationResult:
    ok: bool
    coverage: float
    errors: list[str] = field(default_factory=list)
    represented_chars: int = 0
    source_chars: int = 0
    reconstructed: bool = False
    reconstructed_text: str = ""


def reconstruct_canonical(units: list[TextUnitDraft]) -> str:
    """Join TextUnit.text in sequence order. Separators live inside the units."""
    return "".join(unit.text for unit in sorted(units, key=lambda item: item.sequence))


def verify_document(
    extracted: ExtractedDocument,
    segmented: SegmentedDocument,
    draft: GraphDraft,
    *,
    writer: Any | None = None,
    page_count: int | None = None,
) -> VerificationResult:
    errors: list[str] = []
    source = canonical_source(extracted)
    represented, cover_errors = _coverage_errors(source, segmented.units)
    errors.extend(cover_errors)
    reconstructed = reconstruct_canonical(segmented.units)
    reconstructed_ok = reconstructed == source == segmented.canonical_text
    if not reconstructed_ok:
        errors.append(
            "canonical text does not reconstruct character-for-character "
            "from TextUnits in sequence order"
        )
    errors.extend(_bound_errors(segmented, page_count if page_count is not None else len(extracted.pages)))
    errors.extend(_identity_errors(draft, segmented))
    if writer is not None:
        errors.extend(_graph_errors(writer, draft))
    source_chars = len(source)
    coverage = 1.0 if source_chars == 0 else represented / source_chars
    if source_chars and represented != source_chars:
        errors.append(
            f"text coverage {represented}/{source_chars} = {coverage:.4f}, expected 1.0"
        )
    return VerificationResult(
        ok=not errors,
        coverage=coverage,
        errors=errors,
        represented_chars=represented,
        source_chars=source_chars,
        reconstructed=reconstructed_ok,
        reconstructed_text=reconstructed,
    )


def canonical_source(extracted: ExtractedDocument) -> str:
    parts: list[str] = []
    for index, block in enumerate(extracted.included_blocks()):
        if index:
            parts.append("\n")
        parts.append(block.text)
    return "".join(parts)


def _coverage_errors(
    source: str,
    units: list[TextUnitDraft],
) -> tuple[int, list[str]]:
    errors: list[str] = []
    covered = [False] * len(source)
    for unit in units:
        if unit.char_start < 0 or unit.char_end > len(source) or unit.char_start >= unit.char_end:
            errors.append(
                f"unit {unit.text_unit_id} has invalid range "
                f"{unit.char_start}:{unit.char_end}"
            )
            continue
        if source[unit.char_start : unit.char_end] != unit.text:
            errors.append(f"unit {unit.text_unit_id} text does not match source slice")
            continue
        for index in range(unit.char_start, unit.char_end):
            if covered[index]:
                errors.append(f"overlapping coverage at char {index}")
                break
            covered[index] = True
    represented = sum(1 for flag in covered if flag)
    missing = [index for index, flag in enumerate(covered) if not flag]
    if missing:
        errors.append(f"uncovered source chars starting at {missing[0]}")
    return represented, errors


def _bound_errors(segmented: SegmentedDocument, page_count: int) -> list[str]:
    errors: list[str] = []
    limit = len(segmented.canonical_text)
    for unit in segmented.units:
        if unit.char_start < 0 or unit.char_end > limit:
            errors.append(f"unit {unit.text_unit_id} is outside document char bounds")
        if page_count <= 0:
            continue
        for page in (unit.page_start, unit.page_end):
            if page is not None and not 1 <= page <= page_count:
                errors.append(f"unit {unit.text_unit_id} page {page} is outside 1..{page_count}")
    return errors


def _identity_errors(draft: GraphDraft, segmented: SegmentedDocument) -> list[str]:
    errors: list[str] = []
    version = str(draft.document_props.get("document_version_id") or "")
    for unit in segmented.units:
        if unit.structure_id not in {item.structure_id for item in segmented.structures}:
            errors.append(f"unit {unit.text_unit_id} points at missing structure")
    for node in draft.nodes:
        if node.labels[0] != TEXT_UNIT:
            continue
        if node.props.get("document_version_id") != version:
            errors.append(f"text unit {node.key} has the wrong document_version_id")
    return errors


def _graph_errors(writer: Any, draft: GraphDraft) -> list[str]:
    errors: list[str] = []
    seen: dict[tuple[str, str], Any] = {}
    for node in draft.nodes:
        view = writer.get_node(node.labels[0], node.key)
        if view is None:
            errors.append(f"missing written node {node.labels[0]}:{node.key}")
            continue
        seen[(node.labels[0], node.key)] = view
        if node.labels[0] == DOCUMENT and view.props.get("document_version_id") != node.props.get(
            "document_version_id"
        ):
            errors.append("written document version does not match draft")
        if node.labels[0] == STRUCTURE and view.props.get("document_id") != draft.document_key:
            errors.append(f"structure {node.key} is not bound to the document")
    for edge in draft.edges:
        if (edge.from_label, edge.from_key) not in seen and writer.get_node(
            edge.from_label, edge.from_key
        ) is None:
            errors.append(f"edge {edge.label} missing from-node {edge.from_key}")
        if (edge.to_label, edge.to_key) not in seen and writer.get_node(
            edge.to_label, edge.to_key
        ) is None:
            errors.append(f"edge {edge.label} missing to-node {edge.to_key}")
    return errors
