"""Score extraction and segmentation against a gold fixture."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from overgraph_ingest.config import IngestConfig
from overgraph_ingest.extraction import extract_file
from overgraph_ingest.extraction.model import ExtractedDocument
from overgraph_ingest.graph.verifier import canonical_source, reconstruct_canonical
from overgraph_ingest.ids import hash_file
from overgraph_ingest.quality.gold import GoldFixture, load_gold_dir
from overgraph_ingest.segmentation.headings import parse_clause_label
from overgraph_ingest.segmentation.structural import SegmentedDocument, segment_document


@dataclass
class QualityIssue:
    kind: str
    metric: str
    message: str


@dataclass
class CaseScore:
    name: str
    relative_path: str
    origin: str
    kind: str
    extraction_status: str
    reconstruction_ok: bool
    coverage: float
    reading_order_ok: bool
    clause_recall: float | None
    clause_boundary_ok: bool | None
    hierarchy_ok: bool | None
    table_ok: bool | None
    position_ok: bool | None
    exclusion_ok: bool
    split_ok: bool | None
    extraction_errors: int
    segmentation_errors: int
    issues: list[QualityIssue] = field(default_factory=list)


def evaluate_gold_dir(directory: Path, config: IngestConfig, *, origin: str) -> list[CaseScore]:
    scores: list[CaseScore] = []
    for path, fixture in load_gold_dir(directory, origin=origin):
        extracted = extract_file(
            path.read_bytes(),
            fixture.relative_path,
            hash_file(path),
            extraction_version=config.extraction_version,
        )
        segmented = None
        if extracted.status == "ok":
            segmented = segment_document(
                extracted,
                document_version_id="gold",
                segmentation_version=config.segmentation_version,
                target_chars=config.target_chars,
                max_chars=config.max_chars,
            )
        scores.append(evaluate_prepared(extracted, segmented, fixture))
    return scores


def evaluate_prepared(
    extracted: ExtractedDocument,
    segmented: SegmentedDocument | None,
    fixture: GoldFixture,
) -> CaseScore:
    issues: list[QualityIssue] = []
    if extracted.status != fixture.expect_status:
        issues.append(
            QualityIssue(
                "extraction",
                "status",
                f"status {extracted.status}, expected {fixture.expect_status}",
            )
        )
    included_text = "\n".join(block.text for block in extracted.included_blocks())
    excluded_text = "\n".join(block.text for block in extracted.exclusions())
    source = canonical_source(extracted) if extracted.included_blocks() else ""
    reconstructed = ""
    reconstruction_ok = False
    coverage = 0.0
    if segmented is not None:
        reconstructed = reconstruct_canonical(segmented.units)
        reconstruction_ok = reconstructed == source == segmented.canonical_text
        covered = sum(len(unit.text) for unit in segmented.units)
        coverage = 1.0 if not source else covered / len(source)
        if not reconstruction_ok:
            issues.append(
                QualityIssue(
                    "segmentation",
                    "reconstruction",
                    "TextUnits do not reconstruct the extracted canonical text",
                )
            )
    reading_ok = _reading_order(reconstructed or included_text, fixture.reading_order, issues)
    clause_recall, boundary_ok, hierarchy_ok = _clause_metrics(
        extracted, segmented, fixture, issues
    )
    table_ok = _table_metric(included_text, fixture, issues)
    position_ok = _position_metric(segmented, fixture, issues)
    exclusion_ok = _exclusion_metric(included_text, excluded_text, fixture, issues)
    split_ok = _split_metric(segmented, fixture, issues)
    return CaseScore(
        name=fixture.name,
        relative_path=fixture.relative_path,
        origin=fixture.origin,
        kind=fixture.kind,
        extraction_status=extracted.status,
        reconstruction_ok=reconstruction_ok or fixture.expect_status != "ok",
        coverage=coverage,
        reading_order_ok=reading_ok,
        clause_recall=clause_recall,
        clause_boundary_ok=boundary_ok,
        hierarchy_ok=hierarchy_ok,
        table_ok=table_ok,
        position_ok=position_ok,
        exclusion_ok=exclusion_ok,
        split_ok=split_ok,
        extraction_errors=sum(1 for issue in issues if issue.kind == "extraction"),
        segmentation_errors=sum(1 for issue in issues if issue.kind == "segmentation"),
        issues=issues,
    )


def summarize_scores(scores: list[CaseScore]) -> dict[str, object]:
    if not scores:
        return {"cases": 0}
    scored = [score for score in scores if score.kind != "unscored"]
    recalls = [score.clause_recall for score in scored if score.clause_recall is not None]
    return {
        "case_count": len(scores),
        "scored_cases": len(scored),
        "structure_errors": sum(
            score.extraction_errors + score.segmentation_errors for score in scores
        ),
        "extraction_errors": sum(score.extraction_errors for score in scores),
        "segmentation_errors": sum(score.segmentation_errors for score in scores),
        "reconstruction_ok": sum(1 for score in scored if score.reconstruction_ok),
        "reading_order_ok": sum(1 for score in scored if score.reading_order_ok),
        "exclusion_ok": sum(1 for score in scored if score.exclusion_ok),
        "mean_clause_recall": sum(recalls) / len(recalls) if recalls else None,
        "perfect_cases": sum(1 for score in scored if not score.issues),
        "cases": [
            {
                "name": score.name,
                "origin": score.origin,
                "kind": score.kind,
                "extraction_status": score.extraction_status,
                "reconstruction_ok": score.reconstruction_ok,
                "coverage": score.coverage,
                "reading_order_ok": score.reading_order_ok,
                "clause_recall": score.clause_recall,
                "clause_boundary_ok": score.clause_boundary_ok,
                "hierarchy_ok": score.hierarchy_ok,
                "table_ok": score.table_ok,
                "position_ok": score.position_ok,
                "exclusion_ok": score.exclusion_ok,
                "split_ok": score.split_ok,
                "extraction_errors": score.extraction_errors,
                "segmentation_errors": score.segmentation_errors,
                "issues": [
                    {"kind": issue.kind, "metric": issue.metric, "message": issue.message}
                    for issue in score.issues
                ],
            }
            for score in scores
        ],
    }


def _reading_order(text: str, tokens: list[str], issues: list[QualityIssue]) -> bool:
    if not tokens:
        return True
    cursor = 0
    for token in tokens:
        index = text.find(token, cursor)
        if index < 0:
            issues.append(
                QualityIssue("segmentation", "reading_order", f"missing or out of order: {token}")
            )
            return False
        cursor = index + len(token)
    return True


def _clause_metrics(
    extracted: ExtractedDocument,
    segmented: SegmentedDocument | None,
    fixture: GoldFixture,
    issues: list[QualityIssue],
) -> tuple[float | None, bool | None, bool | None]:
    if not fixture.clauses:
        return None, None, None
    if segmented is None:
        issues.append(QualityIssue("extraction", "clauses", "no segmentation because extraction failed"))
        return 0.0, False, False
    found = {
        structure.clause_number
        for structure in segmented.structures
        if structure.clause_number
    }
    expected = set(fixture.clauses)
    missing = expected - found
    recall = len(expected - missing) / len(expected)
    for clause in sorted(missing):
        issues.append(_missing_clause_issue(extracted, clause))
    boundary_ok = True
    by_number = {
        structure.clause_number: structure
        for structure in segmented.structures
        if structure.clause_number
    }
    for clause in fixture.clauses:
        structure = by_number.get(clause)
        if structure is None:
            boundary_ok = False
            continue
        if not structure.title.replace(" ", "").startswith(clause.replace(" ", "")):
            if clause not in structure.title:
                issues.append(
                    QualityIssue(
                        "segmentation",
                        "clause_boundary",
                        f"{clause} does not start structure title {structure.title!r}",
                    )
                )
                boundary_ok = False
    hierarchy_ok = True
    for child, parent in fixture.parents.items():
        child_node = by_number.get(child)
        parent_node = by_number.get(parent)
        if child_node is None or parent_node is None:
            hierarchy_ok = False
            continue
        if child_node.parent_id != parent_node.structure_id:
            issues.append(
                QualityIssue(
                    "segmentation",
                    "hierarchy",
                    f"{child} is not under {parent}",
                )
            )
            hierarchy_ok = False
    return recall, boundary_ok, hierarchy_ok


def _missing_clause_issue(extracted: ExtractedDocument, clause: str) -> QualityIssue:
    for block in extracted.included_blocks():
        if _clause_number(block.text) == clause:
            return QualityIssue(
                "segmentation",
                "clause_recall",
                f"extracted {clause} but did not create a structure",
            )
    for block in extracted.exclusions():
        if _clause_number(block.text) == clause:
            return QualityIssue(
                "extraction",
                "exclusion",
                f"clause {clause} was excluded as {block.exclude_reason}",
            )
    return QualityIssue(
        "extraction",
        "clause_recall",
        f"clause {clause} was not extracted as its own block",
    )


def _clause_number(text: str) -> str | None:
    return parse_clause_label(text)


def _table_metric(included_text: str, fixture: GoldFixture, issues: list[QualityIssue]) -> bool | None:
    if not fixture.table_cells:
        return None
    missing = [cell for cell in fixture.table_cells if cell not in included_text]
    if missing:
        issues.append(
            QualityIssue("extraction", "table", f"missing table cells: {', '.join(missing)}")
        )
        return False
    return True


def _position_metric(
    segmented: SegmentedDocument | None,
    fixture: GoldFixture,
    issues: list[QualityIssue],
) -> bool | None:
    if not fixture.spanning_clauses:
        return None
    if segmented is None:
        issues.append(QualityIssue("extraction", "position", "cannot check page span"))
        return False
    by_number = {
        structure.clause_number: structure
        for structure in segmented.structures
        if structure.clause_number
    }
    ok = True
    for clause in fixture.spanning_clauses:
        structure = by_number.get(clause)
        if structure is None or structure.page_start is None or structure.page_end is None:
            issues.append(
                QualityIssue("segmentation", "position", f"{clause} is missing page span")
            )
            ok = False
            continue
        if structure.page_start >= structure.page_end:
            issues.append(
                QualityIssue(
                    "segmentation",
                    "position",
                    f"{clause} should span pages, got {structure.page_start}-{structure.page_end}",
                )
            )
            ok = False
    return ok


def _exclusion_metric(
    included_text: str,
    excluded_text: str,
    fixture: GoldFixture,
    issues: list[QualityIssue],
) -> bool:
    ok = True
    for token in fixture.must_exclude:
        if token in included_text:
            issues.append(
                QualityIssue("extraction", "exclusion", f"should have excluded {token!r}")
            )
            ok = False
        elif token not in excluded_text:
            issues.append(
                QualityIssue("extraction", "exclusion", f"expected exclusion {token!r} was missing")
            )
            ok = False
    for token in fixture.must_include:
        if token not in included_text:
            kind = "extraction"
            if token in excluded_text:
                kind = "extraction"
            issues.append(QualityIssue(kind, "exclusion", f"must-include text missing: {token!r}"))
            ok = False
    return ok


def _split_metric(
    segmented: SegmentedDocument | None,
    fixture: GoldFixture,
    issues: list[QualityIssue],
) -> bool | None:
    if not fixture.expect_split:
        return None
    if segmented is None:
        return False
    counts: dict[str, int] = {}
    for unit in segmented.units:
        counts[unit.structure_id] = counts.get(unit.structure_id, 0) + 1
    if any(count > 1 for count in counts.values()):
        return True
    issues.append(
        QualityIssue("segmentation", "split", "expected an oversized clause to be split")
    )
    return False
