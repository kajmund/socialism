"""Track A document-property discovery: deterministic structure + lexicon.

Model-free. Reuses the stored OverGraph Structure titles and TextUnits plus a
frozen, versioned relation taxonomy. It ranks documents, supports paginated
property lookup (never truncated to top-k), and keeps grounding (citation
exists), rule support, and gold support separate.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.candidates import load_graph_context
from overgraph_ingest.retrieval.evidence_gold import inventory_groups
from overgraph_ingest.retrieval.gold import RetrievalGold, load_gold_suite
from overgraph_ingest.retrieval.gold_map import locate_contains
from overgraph_ingest.retrieval.index import StoredUnit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
DEFAULT_TAXONOMY = DEFAULT_GOLD_DIR / "document_properties" / "taxonomy-v1.json"
DEFAULT_MAPPING = DEFAULT_GOLD_DIR / "document_properties" / "gold-mapping-v1.json"
DEFAULT_BM25_RUN = ROOT / "data" / "tantivy-bm25-v1" / "run.json"

GROUNDED = "GROUNDED"
SUPPORTED = "SUPPORTED"
SUPPORTED_NEGATIVE = "SUPPORTED_NEGATIVE"
UNDECIDED = "UNDECIDED"
POSITIVE = "positive"
NEGATIVE = "negative"


@dataclass(frozen=True)
class PropertyClass:
    class_id: str
    label: str
    definition: str
    value_type: str
    positive_markers: tuple[str, ...]
    negative_markers: tuple[str, ...]
    composite_requires: tuple[str, ...]


@dataclass(frozen=True)
class DocumentProperty:
    relative_path: str
    class_id: str
    value: str
    polarity: str | None
    support: str
    source_unit_keys: tuple[str, ...]
    excerpts: tuple[str, ...]


@dataclass(frozen=True)
class PropertyReport:
    payload: dict[str, object]


def load_taxonomy(path: Path | None = None) -> dict[str, PropertyClass]:
    target = path or DEFAULT_TAXONOMY
    payload = json.loads(target.read_text(encoding="utf-8"))
    classes: dict[str, PropertyClass] = {}
    for row in payload["properties"]:
        classes[str(row["class_id"])] = PropertyClass(
            class_id=str(row["class_id"]),
            label=str(row["label"]),
            definition=str(row["definition"]),
            value_type=str(row["value_type"]),
            positive_markers=tuple(str(item) for item in row["positive_markers"]),
            negative_markers=tuple(str(item) for item in row["negative_markers"]),
            composite_requires=tuple(str(item) for item in row["composite_requires"]),
        )
    return classes


def load_gold_mapping(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    target = path or DEFAULT_MAPPING
    payload = json.loads(target.read_text(encoding="utf-8"))
    return {
        str(gold_id): tuple(str(item) for item in row["class_ids"])
        for gold_id, row in payload["golds"].items()
    }


def data_file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_document_properties(
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
    taxonomy: dict[str, PropertyClass],
) -> dict[str, list[DocumentProperty]]:
    by_doc: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        by_doc[unit.relative_path].append(unit)
    headings_by_doc: dict[str, set[str]] = defaultdict(set)
    for props in structures.values():
        title = _normalize(str(props.get("title") or ""))
        if title:
            document = str(props.get("document_id") or "")
            headings_by_doc[document].add(title)
    by_id: dict[str, str] = {unit.document_id: unit.relative_path for unit in units}
    headings_by_path: dict[str, set[str]] = {
        by_id.get(document, ""): titles
        for document, titles in headings_by_doc.items()
        if document in by_id
    }

    results: dict[str, list[DocumentProperty]] = {}
    for path, local in by_doc.items():
        headings = headings_by_path.get(path, set())
        heading_text = " ".join(sorted(headings))
        properties: list[DocumentProperty] = []
        for class_id, spec in taxonomy.items():
            body_hits, negative_hits = _match_units(local, spec)
            if body_hits:
                properties.append(
                    _property(
                        path,
                        spec,
                        polarity=POSITIVE,
                        support=SUPPORTED,
                        matched_units=body_hits,
                    )
                )
            elif negative_hits:
                properties.append(
                    _property(
                        path,
                        spec,
                        polarity=NEGATIVE,
                        support=SUPPORTED_NEGATIVE,
                        matched_units=negative_hits,
                    )
                )
            elif _matches(heading_text, spec.positive_markers):
                properties.append(
                    DocumentProperty(
                        relative_path=path,
                        class_id=class_id,
                        value="",
                        polarity=None,
                        support=UNDECIDED,
                        source_unit_keys=(),
                        excerpts=(),
                    )
                )
        results[path] = _apply_composites(properties, taxonomy)
    return results


def ranked_documents(
    properties_by_doc: dict[str, list[DocumentProperty]],
    class_id: str,
) -> list[str]:
    scored: list[tuple[int, str]] = []
    for path, properties in properties_by_doc.items():
        positive = [
            item for item in properties if item.class_id == class_id and item.support == SUPPORTED
        ]
        if positive:
            scored.append((sum(len(item.source_unit_keys) for item in positive), path))
    return [path for _score, path in sorted(scored, key=lambda item: (-item[0], item[1]))]


def lookup_documents(
    properties_by_doc: dict[str, list[DocumentProperty]],
    class_id: str,
) -> list[str]:
    return sorted(
        path
        for path, properties in properties_by_doc.items()
        if any(
            item.class_id == class_id and item.support == SUPPORTED for item in properties
        )
    )


def run_document_properties(
    config: RetrievalConfig,
    *,
    taxonomy_path: Path | None = None,
    mapping_path: Path | None = None,
    bm25_run_path: Path | None = None,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    golds: list[RetrievalGold] | None = None,
) -> PropertyReport:
    taxonomy = load_taxonomy(taxonomy_path)
    mapping = load_gold_mapping(mapping_path)
    gold_rows = golds if golds is not None else load_gold_suite(DEFAULT_GOLD_DIR)
    if units is None or structures is None:
        context = _load_context(config)
        units = units if units is not None else context.units
        structures = structures if structures is not None else context.structures
    properties_by_doc = extract_document_properties(units, structures, taxonomy)
    hybrid_found = _hybrid_found(bm25_run_path)
    rows = [
        _gold_row(
            gold,
            mapping.get(gold.id, ()),
            properties_by_doc,
            taxonomy,
            units,
            hybrid_found.get(gold.id, set()),
        )
        for gold in gold_rows
    ]
    macro = _macro(rows)
    payload = {
        "operation": "document_properties",
        "experiment": "document_properties_v1",
        "track": "structure",
        "status": "completed",
        "production_changed": False,
        "default_retriever_unchanged": True,
        "taxonomy_hash": data_file_hash(taxonomy_path or DEFAULT_TAXONOMY),
        "mapping_hash": data_file_hash(mapping_path or DEFAULT_MAPPING),
        "taxonomy_id": "document-properties-taxonomy-v1",
        "rows": rows,
        "macro": macro,
        "manifest": _manifest(config, units, gold_rows),
        "limitations": [
            "Capability test for nine pre-registered properties, not a generalization test.",
            "SUPPORTED here is rule-level plus a gold-anchored check; it is not an independent legal verification.",
            "Property lookup is not truncated to top-k and can be paginated through all matches.",
        ],
    }
    return PropertyReport(payload=payload)


def _gold_row(
    gold: RetrievalGold,
    class_ids: tuple[str, ...],
    properties_by_doc: dict[str, list[DocumentProperty]],
    taxonomy: dict[str, PropertyClass],
    units: list[StoredUnit],
    hybrid_found: set[str],
) -> dict[str, object]:
    groups = inventory_groups(gold)
    gold_pos = set(groups)
    gold_neg = {span.relative_path for span in gold.hard_negatives}
    extracted = set()
    if class_ids:
        extracted = {
            path
            for path, properties in properties_by_doc.items()
            if all(
                any(
                    item.class_id == class_id and item.support == SUPPORTED
                    for item in properties
                )
                for class_id in class_ids
            )
        }
    recall = len(extracted & gold_pos) / len(gold_pos) if gold_pos else 0.0
    precision = len(extracted & gold_pos) / len(extracted) if extracted else 0.0
    missing = sorted(gold_pos - extracted)
    false_positives = sorted(extracted - gold_pos)
    missed = sorted(gold_pos - hybrid_found)
    recovered = sorted((extracted & gold_pos) & set(missed))
    verification = _verification(extracted, gold, units, class_ids)
    return {
        "gold_id": gold.id,
        "split": gold.split,
        "class_ids": list(class_ids),
        "gold_positives": len(gold_pos),
        "gold_negatives": sorted(gold_neg),
        "extracted_positives": len(extracted),
        "property_recall": recall,
        "property_precision": precision,
        "false_positives": false_positives,
        "missing_properties": missing,
        "previously_missed": missed,
        "recovered_missed": recovered,
        "recovered_missed_count": len(recovered),
        "lookup_completeness": recall,
        "verification": verification,
        "ranked_recall": _ranked_recall(
            ranked_documents(properties_by_doc, class_ids[0] if class_ids else ""),
            gold_pos,
        ),
    }


def _verification(
    extracted: set[str],
    gold: RetrievalGold,
    units: list[StoredUnit],
    class_ids: tuple[str, ...],
) -> dict[str, object]:
    by_path: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        by_path[unit.relative_path].append(unit)
    gold_spans = {span.relative_path: span.contains for span in gold.relevant_units}
    grounded = 0
    gold_supported = 0
    for path in extracted:
        local = by_path.get(path, [])
        span = gold_spans.get(path)
        if span is not None and any(locate_contains(unit.text, span) for unit in local):
            gold_supported += 1
            grounded += 1
        elif local:
            grounded += 1
    return {
        "grounded": grounded,
        "gold_supported": gold_supported,
        "gold_grounded_only": grounded - gold_supported,
        "total_extracted": len(extracted),
        "note": (
            "GROUNDED = a body TextUnit was cited; gold_supported = that text "
            "contains the gold evidence span for the mapped question."
        ),
    }


def _ranked_recall(ranked: list[str], gold_pos: set[str]) -> dict[str, float]:
    if not gold_pos:
        return {"10": 0.0, "20": 0.0, "50": 0.0}
    return {
        str(k): len(set(ranked[:k]) & gold_pos) / len(gold_pos) for k in (10, 20, 50)
    }


def _macro(rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "property_recall": mean(row["property_recall"] for row in rows),
        "property_precision": mean(row["property_precision"] for row in rows),
        "recovered_missed_total": sum(row["recovered_missed_count"] for row in rows),
        "missing_total": sum(len(row["missing_properties"]) for row in rows),
        "false_positive_total": sum(len(row["false_positives"]) for row in rows),
        "lookup_completeness": mean(row["lookup_completeness"] for row in rows),
        "ranked_recall_20": mean(row["ranked_recall"]["20"] for row in rows),
        "ranked_recall_50": mean(row["ranked_recall"]["50"] for row in rows),
    }


def _match_units(
    local: list[StoredUnit],
    spec: PropertyClass,
) -> tuple[list[StoredUnit], list[StoredUnit]]:
    body: list[StoredUnit] = []
    negative: list[StoredUnit] = []
    for unit in local:
        if _matches(unit.text, spec.negative_markers):
            negative.append(unit)
        elif _matches(unit.text, spec.positive_markers):
            body.append(unit)
    return body, negative


def _property(
    path: str,
    spec: PropertyClass,
    *,
    polarity: str,
    support: str,
    matched_units: list[StoredUnit],
) -> DocumentProperty:
    markers = spec.negative_markers if polarity == NEGATIVE else spec.positive_markers
    excerpts = []
    keys = []
    for unit in matched_units:
        marker = _first_marker(unit.text, markers)
        if marker is None:
            continue
        excerpts.append(marker)
        keys.append(unit.key)
    value = ""
    if spec.value_type == "jurisdiction":
        value = "Sweden" if any("svensk" in marker for marker in excerpts) else "Other"
    elif spec.value_type == "boolean":
        value = "true" if polarity == POSITIVE else "false"
    return DocumentProperty(
        relative_path=path,
        class_id=spec.class_id,
        value=value,
        polarity=polarity,
        support=support,
        source_unit_keys=tuple(keys),
        excerpts=tuple(excerpts),
    )


def _apply_composites(
    properties: list[DocumentProperty],
    taxonomy: dict[str, PropertyClass],
) -> list[DocumentProperty]:
    positives = {
        item.class_id
        for item in properties
        if item.support == SUPPORTED
    }
    output = []
    for item in properties:
        spec = taxonomy.get(item.class_id)
        if (
            spec
            and spec.composite_requires
            and item.support == SUPPORTED
            and not set(spec.composite_requires).issubset(positives)
        ):
            item = DocumentProperty(
                relative_path=item.relative_path,
                class_id=item.class_id,
                value=item.value,
                polarity=None,
                support=UNDECIDED,
                source_unit_keys=(),
                excerpts=(),
            )
        output.append(item)
    return output


def _hybrid_found(path: Path | None) -> dict[str, set[str]]:
    target = path or DEFAULT_BM25_RUN
    if target is None or not target.is_file():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    profiles = payload.get("profiles") or {}
    first = next(iter(profiles.values()), {})
    rows = (first.get("global") or {}).get("rows") or []
    found: dict[str, set[str]] = {}
    for row in rows:
        arms = row.get("arms") or {}
        hybrid = arms.get("hybrid_current") or {}
        found[str(row["gold_id"])] = {
            str(candidate.get("relative_path") or "")
            for candidate in hybrid.get("candidates") or []
            if candidate.get("label") == "relevant"
        }
    return found


def _load_context(config: RetrievalConfig):
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    db = open_database(config.db_path, dimension)
    try:
        return load_graph_context(GraphWriter(db, batch_size=config.write_batch_size))
    finally:
        db.close()


def _manifest(
    config: RetrievalConfig,
    units: list[StoredUnit],
    golds: list[RetrievalGold],
) -> dict[str, object]:
    return {
        "run_id": "phase2-document-properties-v1",
        "track": "structure",
        "code_revision": _code_revision(),
        "created_at": datetime.now(UTC).isoformat(),
        "db": str(config.db_path),
        "units": len(units),
        "documents": len({unit.relative_path for unit in units}),
        "golds": [gold.id for gold in golds],
    }


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()


def _matches(text: str, markers: tuple[str, ...]) -> bool:
    folded = _normalize(text)
    return any(marker.casefold() in folded for marker in markers)


def _first_marker(text: str, markers: tuple[str, ...]) -> str | None:
    folded = text.casefold()
    positions = []
    for marker in markers:
        index = folded.find(marker.casefold())
        if index >= 0:
            positions.append((index, index + len(marker)))
    if not positions:
        return None
    start, end = min(positions)
    return text[start:end]


def _code_revision() -> dict[str, object]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        return {"head": revision, "dirty": dirty}
    except (subprocess.CalledProcessError, OSError):
        return {"head": "unknown", "dirty": None}


REVIEW_SET_ID = "review-false-positives-v1"
REVIEW_SET_PATH = (
    DEFAULT_GOLD_DIR / "document_properties" / f"{REVIEW_SET_ID}.json"
)
REVIEW_CLASSIFICATIONS = (
    "wrong_property",
    "gold_gap",
    "wrong_relation_or_polarity",
)


def build_false_positive_review_set(
    config: RetrievalConfig,
    *,
    taxonomy_path: Path | None = None,
    mapping_path: Path | None = None,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    golds: list[RetrievalGold] | None = None,
) -> dict[str, object]:
    """Collect every property-level false positive with full review context.

    This does not judge anything; it produces the review set. Judgments are
    filled in by an independent reviewer. Jev must never create the gold it is
    later evaluated against.
    """
    taxonomy = load_taxonomy(taxonomy_path)
    mapping = load_gold_mapping(mapping_path)
    gold_rows = golds if golds is not None else load_gold_suite(DEFAULT_GOLD_DIR)
    if units is None or structures is None:
        context = _load_context(config)
        units = units if units is not None else context.units
        structures = structures if structures is not None else context.structures
    properties_by_doc = extract_document_properties(units, structures, taxonomy)
    by_key = {unit.key: unit for unit in units}
    by_path: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        by_path[unit.relative_path].append(unit)
    neighbors = _neighbors(units)
    structure_titles = {
        structure_id: str(props.get("title") or "")
        for structure_id, props in structures.items()
    }

    entries: list[dict[str, object]] = []
    for gold in gold_rows:
        class_ids = mapping.get(gold.id, ())
        if not class_ids:
            continue
        gold_pos = set(inventory_groups(gold))
        for path in sorted(properties_by_doc):
            if path in gold_pos:
                continue
            for class_id in class_ids:
                positives = [
                    item
                    for item in properties_by_doc[path]
                    if item.class_id == class_id and item.support == SUPPORTED
                ]
                if not positives:
                    continue
                evidence = []
                for item in positives:
                    for key, excerpt in zip(item.source_unit_keys, item.excerpts):
                        unit = by_key.get(key)
                        if unit is None:
                            continue
                        previous_text, next_text = neighbors.get(key, ("", ""))
                        evidence.append(
                            {
                                "unit_key": key,
                                "excerpt": excerpt,
                                "unit_text": unit.text,
                                "clause_title": structure_titles.get(
                                    unit.structure_id, ""
                                ),
                                "previous_text": previous_text[:600],
                                "next_text": next_text[:600],
                            }
                        )
                if not evidence:
                    continue
                entries.append(
                    {
                        "gold_id": gold.id,
                        "property_class": class_id,
                        "relative_path": path,
                        "polarity": positives[0].polarity,
                        "value": positives[0].value,
                        "evidence": evidence,
                        "review": {
                            "property_judgment": None,
                            "citation_judgment": None,
                            "classification": None,
                            "note": "",
                        },
                    }
                )
    return {
        "id": REVIEW_SET_ID,
        "version": "v1",
        "status": "pending_review",
        "description": (
            "Property-level false positives from Track A document-property "
            "discovery, with exact excerpts, source TextUnits, clause titles, "
            "and neighbors. Judgments are added by an independent reviewer; "
            "Jev must never create the gold it is later evaluated against."
        ),
        "classifications": list(REVIEW_CLASSIFICATIONS),
        "judgment_fields": {
            "property_judgment": "does the document actually have the property? yes/no/unknown",
            "citation_judgment": "does the cited excerpt actually prove the property? supported/unsupported/unknown",
            "classification": "wrong_property | gold_gap | wrong_relation_or_polarity",
        },
        "taxonomy_hash": data_file_hash(taxonomy_path or DEFAULT_TAXONOMY),
        "mapping_hash": data_file_hash(mapping_path or DEFAULT_MAPPING),
        "created_at": datetime.now(UTC).isoformat(),
        "count": len(entries),
        "entries": entries,
    }


def write_false_positive_review_set(
    review: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or REVIEW_SET_PATH
    if target.exists():
        raise FileExistsError(f"review set already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(review, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _neighbors(units: list[StoredUnit]) -> dict[str, tuple[str, str]]:
    by_document: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        by_document.setdefault(unit.document_id, []).append(unit)
    result: dict[str, tuple[str, str]] = {}
    for group in by_document.values():
        ordered = sorted(group, key=lambda item: item.sequence or 0)
        for index, unit in enumerate(ordered):
            previous_text = ordered[index - 1].text if index else ""
            next_text = ordered[index + 1].text if index + 1 < len(ordered) else ""
            result[unit.key] = (previous_text, next_text)
    return result


PROPERTY_BASELINE_ID = "phase2-document-properties-v1"
PROPERTY_BASELINE_PATH = ROOT / "baselines" / f"{PROPERTY_BASELINE_ID}.json"


def freeze_document_properties_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": PROPERTY_BASELINE_ID,
        "label": (
            "Frozen Track A document-property discovery: deterministic structure "
            "plus a frozen relation taxonomy. Model-free. Production and default "
            "retriever unchanged."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "default_retriever_unchanged": True,
        "production_changed": False,
        "track": payload.get("track"),
        "taxonomy_hash": payload.get("taxonomy_hash"),
        "mapping_hash": payload.get("mapping_hash"),
        "macro": payload.get("macro"),
        "manifest": payload.get("manifest"),
        "limitations": payload.get("limitations"),
        "rows": payload.get("rows"),
    }


def write_document_properties_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or PROPERTY_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            freeze_document_properties_baseline(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def write_document_properties_report(payload: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_report_markdown(payload), encoding="utf-8")
    return path


def _report_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Document properties v1 (Track A, deterministic structure)",
        "",
        (
            "Model-free. Deterministic structure + a frozen relation taxonomy. "
            "Production is unchanged."
        ),
        "",
        (
            "| Gold | Split | Pos | Extracted | PropertyRecall | PropertyPrecision | "
            "LookupCompleteness | RecoveredMissed | Missing | FP |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['gold_id']} | {row['split']} | {row['gold_positives']} | "
            f"{row['extracted_positives']} | {row['property_recall']:.4f} | "
            f"{row['property_precision']:.4f} | {row['lookup_completeness']:.4f} | "
            f"{row['recovered_missed_count']} | {len(row['missing_properties'])} | "
            f"{len(row['false_positives'])} |"
        )
    lines.extend(
        [
            "",
            "## Macro",
            "",
            "```json",
            json.dumps(payload["macro"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Verification (GROUNDED vs gold_supported)",
            "",
            "| Gold | Extracted | GROUNDED | gold_supported | grounded-only |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in payload["rows"]:
        verification = row["verification"]
        lines.append(
            f"| {row['gold_id']} | {verification['total_extracted']} | "
            f"{verification['grounded']} | {verification['gold_supported']} | "
            f"{verification['gold_grounded_only']} |"
        )
    lines.extend(["", "## Limitations", ""])
    for limitation in payload["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)
