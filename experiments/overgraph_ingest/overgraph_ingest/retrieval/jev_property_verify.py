"""Jev verification of deterministic document properties.

Isolated experiment. Jev is a non-hard verifier: it returns SUPPORTED,
UNSUPPORTED, or UNDECIDED for a proposed document property, with a source
TextUnit. Source grounding (citation exists) is kept separate from semantic
verification; an unvalidatable source is never SUPPORTED. Production,
discovery, and taxonomy are unchanged.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.doctags.source import validate_source
from overgraph_ingest.jev.client import HttpJevClient, JevClient, JevResult
from overgraph_ingest.retrieval.document_properties import (
    PropertyClass,
    load_gold_mapping,
    load_taxonomy,
)
from overgraph_ingest.retrieval.evidence_gold import inventory_groups
from overgraph_ingest.retrieval.gold import RetrievalGold, load_gold_suite
from overgraph_ingest.retrieval.gold_map import locate_contains
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.jev_io import proposed_spans

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
DEFAULT_TAXONOMY = DEFAULT_GOLD_DIR / "document_properties" / "taxonomy-v1.json"
DEFAULT_MAPPING = DEFAULT_GOLD_DIR / "document_properties" / "gold-mapping-v1.json"

SUPPORTED = "SUPPORTED"
UNSUPPORTED = "UNSUPPORTED"
UNDECIDED = "UNDECIDED"
ERROR = "ERROR"
VERDICTS = (SUPPORTED, UNSUPPORTED, UNDECIDED, ERROR)

GROUP_POSITIVE = "positive"
GROUP_ERROR = "error"
GROUP_GOLD_GAP = "gold_gap"

# ~20 gold-positive controls, spread across the nine golds.
POSITIVE_ALLOCATION = {
    "auto-renewal": 2,
    "notice-period": 2,
    "liability-cap": 3,
    "confidentiality": 2,
    "liability-secrecy-carveout": 2,
    "governing-law": 3,
    "force-majeure": 2,
    "personal-data": 2,
    "assignment": 2,
}

VERIFY_INSTRUCTIONS = (
    "Judge whether the listed excerpt supports the proposed document property. "
    "SUPPORTED only when the excerpt itself asserts the property with the "
    "stated polarity. A heading, a cross-reference, or a permission is not "
    "support for an obligation or prohibition. UNSUPPORTED when the excerpt "
    "does not assert the property or asserts the opposite. UNDECIDED when it "
    "is unclear without more context. Choose a listed excerpt for SUPPORTED; "
    "choose none otherwise."
)


@dataclass(frozen=True)
class VerificationCase:
    group: str
    gold_id: str
    property_class: str
    relative_path: str
    polarity: str | None
    value: str
    unit_key: str
    unit_text: str
    clause_title: str
    previous_text: str
    next_text: str
    review_classification: str | None = None


@dataclass(frozen=True)
class VerificationOutcome:
    case: VerificationCase
    verdict: str
    source_valid: bool
    effective: str
    source_unit_key: str | None
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None = None


@dataclass(frozen=True)
class VerificationReport:
    payload: dict[str, object]


def build_positive_controls(
    units: list[StoredUnit],
    golds: list[RetrievalGold],
    mapping: dict[str, tuple[str, ...]],
    *,
    allocation: dict[str, int] | None = None,
    by_key: dict[str, StoredUnit] | None = None,
    structure_titles: dict[str, str] | None = None,
    neighbors: dict[str, tuple[str, str]] | None = None,
) -> list[VerificationCase]:
    """Positive controls cite the gold evidence unit, not the extractor's unit.

    This measures property-level false rejection: does Jev keep a true
    property when shown the passage that actually answers the question.
    """
    allocation = allocation or POSITIVE_ALLOCATION
    by_key = by_key or {}
    structure_titles = structure_titles or {}
    neighbors = neighbors or {}
    units_by_path: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        units_by_path[unit.relative_path].append(unit)
    cases: list[VerificationCase] = []
    for gold in golds:
        class_ids = mapping.get(gold.id, ())
        if not class_ids:
            continue
        class_id = class_ids[0]
        gold_pos = sorted(set(inventory_groups(gold)))
        chosen = _even_pick(gold_pos, allocation.get(gold.id, 2))
        for path in chosen:
            unit = _gold_evidence_unit(gold, path, units_by_path.get(path, []))
            if unit is None:
                continue
            previous_text, next_text = neighbors.get(unit.key, ("", ""))
            cases.append(
                VerificationCase(
                    group=GROUP_POSITIVE,
                    gold_id=gold.id,
                    property_class=class_id,
                    relative_path=path,
                    polarity="positive",
                    value=_value_for_class(class_id),
                    unit_key=unit.key,
                    unit_text=unit.text,
                    clause_title=structure_titles.get(unit.structure_id, ""),
                    previous_text=previous_text,
                    next_text=next_text,
                )
            )
    return cases


def _gold_evidence_unit(
    gold: RetrievalGold,
    path: str,
    local: list[StoredUnit],
) -> StoredUnit | None:
    for span in gold.relevant_units:
        if span.relative_path != path:
            continue
        for unit in local:
            if locate_contains(unit.text, span.contains):
                return unit
    return None


def _value_for_class(class_id: str) -> str:
    return "Sweden" if class_id == "governing_law" else "true"


def build_review_controls(
    review_path: Path,
) -> tuple[list[VerificationCase], list[VerificationCase]]:
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    errors: list[VerificationCase] = []
    gaps: list[VerificationCase] = []
    for entry in payload.get("entries") or []:
        review = entry.get("review") or {}
        classification = review.get("classification")
        if classification not in {"wrong_property", "wrong_relation_or_polarity", "gold_gap"}:
            continue
        evidence = (entry.get("evidence") or [])[0] if entry.get("evidence") else {}
        case = VerificationCase(
            group=GROUP_ERROR if classification != "gold_gap" else GROUP_GOLD_GAP,
            gold_id=str(entry.get("gold_id") or ""),
            property_class=str(entry.get("property_class") or ""),
            relative_path=str(entry.get("relative_path") or ""),
            polarity=entry.get("polarity"),
            value=str(entry.get("value") or ""),
            unit_key=str(evidence.get("unit_key") or ""),
            unit_text=str(evidence.get("unit_text") or ""),
            clause_title=str(evidence.get("clause_title") or ""),
            previous_text=str(evidence.get("previous_text") or ""),
            next_text=str(evidence.get("next_text") or ""),
            review_classification=classification,
        )
        if classification == "gold_gap":
            gaps.append(case)
        else:
            errors.append(case)
    return errors, gaps


def verify_case(
    client: JevClient,
    case: VerificationCase,
    taxonomy: dict[str, PropertyClass],
    units: list[StoredUnit],
    *,
    model: str,
    timeout_seconds: float,
) -> VerificationOutcome:
    spec = taxonomy.get(case.property_class)
    definition = spec.definition if spec else ""
    label = spec.label if spec else case.property_class
    candidates = _candidate_units(units, case)
    spans = proposed_spans(candidates)
    excerpt_criteria = {span["id"]: span["text"] for span in spans}
    excerpt_criteria["none"] = "No listed excerpt supports the property."
    questions = {
        "verdict": {
            "type": "choice",
            "instructions": VERIFY_INSTRUCTIONS,
            "criteria": {
                SUPPORTED: "The excerpt asserts the property with the stated polarity.",
                UNSUPPORTED: "The excerpt does not assert the property or asserts the opposite.",
                UNDECIDED: "Unclear without more context.",
            },
        },
        "source": {
            "type": "choice",
            "instructions": "Pick one listed excerpt that supports the property, or none.",
            "criteria": excerpt_criteria,
        },
    }
    started = time.perf_counter()
    try:
        result = client.ask(
            state={
                "task": "property_verification",
                "relative_path": case.relative_path,
                "property": {
                    "class_id": case.property_class,
                    "label": label,
                    "definition": definition,
                    "value": case.value,
                    "polarity": case.polarity,
                },
                "clause_title": case.clause_title,
                "previous_text": case.previous_text,
                "text": case.unit_text,
                "next_text": case.next_text,
            },
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — measurement must record, not crash
        return VerificationOutcome(
            case=case,
            verdict=ERROR,
            source_valid=False,
            effective=ERROR,
            source_unit_key=None,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            prompt_tokens=None,
            completion_tokens=None,
            error=str(exc),
        )
    latency_ms = (time.perf_counter() - started) * 1000.0
    verdict = _choice(result, "verdict", set(VERDICTS), UNDECIDED)
    source_id = _choice(result, "source", set(excerpt_criteria), "none")
    source_valid, source_unit_key = _validate_source(source_id, spans, units, case)
    if verdict == SUPPORTED:
        effective = SUPPORTED if source_valid else UNDECIDED
    else:
        effective = verdict
    return VerificationOutcome(
        case=case,
        verdict=verdict,
        source_valid=source_valid,
        effective=effective,
        source_unit_key=source_unit_key,
        latency_ms=latency_ms,
        prompt_tokens=_int_or_none(result.usage.prompt_tokens),
        completion_tokens=_int_or_none(result.usage.completion_tokens),
    )


def run_jev_property_verification(
    config: RetrievalConfig,
    *,
    review_path: Path | None = None,
    taxonomy_path: Path | None = None,
    mapping_path: Path | None = None,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    golds: list[RetrievalGold] | None = None,
    jev: JevClient | None = None,
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 8.0,
) -> VerificationReport:
    taxonomy = load_taxonomy(taxonomy_path)
    mapping = load_gold_mapping(mapping_path)
    gold_rows = golds if golds is not None else load_gold_suite(DEFAULT_GOLD_DIR)
    if units is None or structures is None:
        from overgraph_ingest.graph.writer import (
            GraphWriter,
            open_database,
            resolve_dimension,
        )
        from overgraph_ingest.jev.candidates import load_graph_context

        dimension = resolve_dimension(config.db_path, config.dense_dimension)
        db = open_database(config.db_path, dimension)
        try:
            context = load_graph_context(GraphWriter(db, batch_size=config.write_batch_size))
        finally:
            db.close()
        units = units if units is not None else context.units
        structures = structures if structures is not None else context.structures
    by_key = {unit.key: unit for unit in units}
    structure_titles = {
        structure_id: str(props.get("title") or "")
        for structure_id, props in structures.items()
    }
    neighbors = _neighbors(units)
    positives = build_positive_controls(
        units,
        gold_rows,
        mapping,
        by_key=by_key,
        structure_titles=structure_titles,
        neighbors=neighbors,
    )
    if review_path is None:
        raise RuntimeError(
            "--jev-property-review is required: the per-entry review JSON "
            "with filled review.classification fields."
        )
    errors, gaps = build_review_controls(review_path)
    cases = positives + errors + gaps
    client = jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    outcomes = [
        verify_case(
            client,
            case,
            taxonomy,
            units,
            model=jev_model,
            timeout_seconds=jev_timeout_seconds,
        )
        for case in cases
    ]
    metrics = _metrics(outcomes)
    payload = {
        "operation": "jev_property_verification",
        "experiment": "jev_property_verification_v1",
        "status": "completed",
        "production_changed": False,
        "default_retriever_unchanged": True,
        "discovery_unchanged": True,
        "taxonomy_unchanged": True,
        "groups": {
            "positive": len(positives),
            "error": len(errors),
            "gold_gap": len(gaps),
        },
        "metrics": metrics,
        "outcomes": [_outcome_payload(outcome) for outcome in outcomes],
        "manifest": _manifest(config, units, taxonomy_path, mapping_path, review_path, jev_model),
        "decision": _decision(metrics),
    }
    return VerificationReport(payload=payload)


def _outcome_payload(outcome: VerificationOutcome) -> dict[str, object]:
    payload = dict(outcome.__dict__)
    payload["case"] = dict(outcome.case.__dict__)
    return payload


def _metrics(outcomes: list[VerificationOutcome]) -> dict[str, object]:
    by_group: dict[str, list[VerificationOutcome]] = defaultdict(list)
    for outcome in outcomes:
        by_group[outcome.case.group].append(outcome)

    def counts(group: str) -> dict[str, int]:
        rows = [row for row in by_group.get(group, []) if row.effective != ERROR]
        return {
            SUPPORTED: sum(1 for row in rows if row.effective == SUPPORTED),
            UNSUPPORTED: sum(1 for row in rows if row.effective == UNSUPPORTED),
            UNDECIDED: sum(1 for row in rows if row.effective == UNDECIDED),
        }

    positive = counts(GROUP_POSITIVE)
    error = counts(GROUP_ERROR)
    gap = counts(GROUP_GOLD_GAP)
    n_positive = sum(positive.values())
    n_error = sum(error.values())
    n_gap = sum(gap.values())
    return {
        "keep_rate_strict": (positive[SUPPORTED] / n_positive) if n_positive else None,
        "keep_rate_cautious": ((positive[SUPPORTED] + positive[UNDECIDED]) / n_positive)
        if n_positive
        else None,
        "false_rejection_count": positive[UNSUPPORTED],
        "reject_rate_errors": ((error[UNSUPPORTED]) / n_error) if n_error else None,
        "error_miss_rate": (error[SUPPORTED] / n_error) if n_error else None,
        "error_undecided_rate": (error[UNDECIDED] / n_error) if n_error else None,
        "gold_gap_agreement": (gap[SUPPORTED] / n_gap) if n_gap else None,
        "gold_gap_undecided_rate": (gap[UNDECIDED] / n_gap) if n_gap else None,
        "undecided_rate_positive": (positive[UNDECIDED] / n_positive) if n_positive else None,
        "counts": {"positive": positive, "error": error, "gold_gap": gap},
        "lost_documents": _lost_documents(by_group.get(GROUP_POSITIVE, [])),
        "latency_ms": {
            "total": sum(row.latency_ms for row in outcomes),
            "mean": mean([row.latency_ms for row in outcomes]) if outcomes else 0.0,
            "max": max((row.latency_ms for row in outcomes), default=0.0),
        },
        "tokens": {
            "prompt": sum(row.prompt_tokens or 0 for row in outcomes),
            "completion": sum(row.completion_tokens or 0 for row in outcomes),
        },
        "errors": [row.error for row in outcomes if row.error],
    }


def _lost_documents(rows: list[VerificationOutcome]) -> dict[str, object]:
    lost: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        if row.effective == UNSUPPORTED:
            lost[row.case.property_class].append(row.case.relative_path)
    return {key: sorted(set(value)) for key, value in lost.items()}


def _decision(metrics: dict[str, object]) -> dict[str, object]:
    keep = metrics.get("keep_rate_strict")
    reject = metrics.get("reject_rate_errors")
    if keep is None or reject is None:
        return {"verdict": "no_measurement", "conservative": True}
    if keep >= 0.95 and reject is not None and reject >= 0.6:
        verdict = "jev_adds_precision_without_recall_loss"
    elif keep is not None and keep < 0.9:
        verdict = "jev_unsafe_as_verifier"
    else:
        verdict = "inconclusive"
    return {
        "verdict": verdict,
        "conservative": True,
        "note": (
            "Prefer keeping false positives over losing correct contracts. "
            "UNDECIDED is never treated as UNSUPPORTED."
        ),
    }


def _candidate_units(units: list[StoredUnit], case: VerificationCase) -> list[StoredUnit]:
    candidates = [
        unit
        for unit in units
        if unit.relative_path == case.relative_path
        and unit.key in {case.unit_key}
    ]
    if not candidates:
        return []
    return candidates


def _validate_source(
    source_id: str,
    spans: list[dict[str, str]],
    units: list[StoredUnit],
    case: VerificationCase,
) -> tuple[bool, str | None]:
    if source_id == "none":
        return False, None
    span = next((item for item in spans if item["id"] == source_id), None)
    if span is None:
        return False, None
    unit = next(
        (item for item in units if item.key == span.get("unit_id") and item.relative_path == case.relative_path),
        None,
    )
    validated = validate_source(
        str(span.get("text") or ""),
        unit=unit,
        document_id=(unit.document_id if unit else ""),
    )
    return validated.validated, str(span.get("unit_id") or "") if validated.validated else None


def _choice(result: JevResult, key: str, allowed: set[str], default: str) -> str:
    row = result.answers.get(key)
    if not isinstance(row, dict):
        return default
    choice = str(row.get("choice") or "").strip()
    return choice if choice in allowed else default


def _even_pick(items: list[str], count: int) -> list[str]:
    if not items:
        return []
    if count >= len(items):
        return items
    if count == 1:
        return [items[len(items) // 2]]
    return [items[round(i * (len(items) - 1) / (count - 1))] for i in range(count)]


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


def _int_or_none(value) -> int | None:
    return int(value) if value is not None else None


def _manifest(
    config: RetrievalConfig,
    units: list[StoredUnit],
    taxonomy_path: Path | None,
    mapping_path: Path | None,
    review_path: Path | None,
    jev_model: str,
) -> dict[str, object]:
    def file_hash(path: Path | None) -> str:
        if path is None or not path.is_file():
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return {
        "run_id": "phase2-jev-property-verification-v1",
        "code_revision": _code_revision(),
        "created_at": datetime.now(UTC).isoformat(),
        "db": str(config.db_path),
        "units": len(units),
        "taxonomy_hash": file_hash(taxonomy_path or DEFAULT_TAXONOMY),
        "mapping_hash": file_hash(mapping_path or DEFAULT_MAPPING),
        "review_hash": file_hash(review_path),
        "jev_model": jev_model,
        "positive_allocation": POSITIVE_ALLOCATION,
        "undecided_is_not_unsupported": True,
    }


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


VERIFICATION_BASELINE_ID = "phase2-jev-property-verification-v1"
VERIFICATION_BASELINE_PATH = ROOT / "baselines" / f"{VERIFICATION_BASELINE_ID}.json"


def freeze_verification_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": VERIFICATION_BASELINE_ID,
        "label": (
            "Frozen Jev property-verification experiment. Jev is a non-hard "
            "verifier of deterministic document properties. Production, "
            "discovery, and taxonomy are unchanged."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "default_retriever_unchanged": True,
        "production_changed": False,
        "discovery_unchanged": True,
        "taxonomy_unchanged": True,
        "groups": payload.get("groups"),
        "metrics": payload.get("metrics"),
        "decision": payload.get("decision"),
        "manifest": payload.get("manifest"),
        "outcomes": payload.get("outcomes"),
    }


def write_verification_baseline(payload: dict[str, object], path: Path | None = None) -> Path:
    target = path or VERIFICATION_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(freeze_verification_baseline(payload), ensure_ascii=False, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
    return target


def write_verification_report(payload: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_report_markdown(payload), encoding="utf-8")
    return path


def _report_markdown(payload: dict[str, object]) -> str:
    metrics = payload["metrics"]
    counts = metrics["counts"]
    lines = [
        "# Jev property verification v1",
        "",
        (
            "Jev is a non-hard verifier of deterministic document properties. "
            "UNDECIDED is never treated as UNSUPPORTED."
        ),
        "",
        "## Verdict",
        "",
        "```json",
        json.dumps(payload["decision"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Metrics",
        "",
        "| Group | SUPPORTED | UNSUPPORTED | UNDECIDED |",
        "|---|---:|---:|---:|",
    ]
    for group in ("positive", "error", "gold_gap"):
        row = counts[group]
        lines.append(
            f"| {group} | {row['SUPPORTED']} | {row['UNSUPPORTED']} | {row['UNDECIDED']} |"
        )
    lines.extend(
        [
            "",
            f"keep_rate_strict: {_fmt(metrics.get('keep_rate_strict'))}",
            f"keep_rate_cautious: {_fmt(metrics.get('keep_rate_cautious'))}",
            f"false_rejection_count: {metrics.get('false_rejection_count')}",
            f"reject_rate_errors: {_fmt(metrics.get('reject_rate_errors'))}",
            f"error_miss_rate: {_fmt(metrics.get('error_miss_rate'))}",
            f"gold_gap_agreement: {_fmt(metrics.get('gold_gap_agreement'))}",
            "",
            "## Lost documents under a simulated soft filter (positive controls)",
            "",
            "```json",
            json.dumps(metrics.get("lost_documents"), ensure_ascii=False, indent=2),
            "```",
            "",
            "## Latency and tokens",
            "",
            "```json",
            json.dumps(
                {"latency_ms": metrics.get("latency_ms"), "tokens": metrics.get("tokens")},
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "## Errors",
            "",
            "```json",
            json.dumps(metrics.get("errors"), ensure_ascii=False, indent=2),
            "```",
        ]
    )
    return "\n".join(lines)


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)
