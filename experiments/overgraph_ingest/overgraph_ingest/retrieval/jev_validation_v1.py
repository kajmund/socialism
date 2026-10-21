"""Broad validation of the Jev verification chain.

Isolated experiment. Freezes the pipeline: deterministic discovery -> Jev ->
document-local dense (gold.query) -> Jev, with the presentation fix (candidate
clauses shown as primary evidence). Case set is all 111 suspected false
positives plus a balanced sample of >=100 gold-positive document-property
pairs. The 30 AI-preliminary labels are reported as agreement only, never as
definitive gold.
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
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.metrics import percentile
from overgraph_ingest.retrieval.document_properties import (
    extract_document_properties,
    load_gold_mapping,
    load_taxonomy,
)
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.evidence_gold import inventory_groups
from overgraph_ingest.retrieval.gold import load_gold_suite
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.jev_end_to_end import _dense_top
from overgraph_ingest.retrieval.jev_presentation_v1 import _verify_present
from overgraph_ingest.retrieval.jev_property_verify import (
    SUPPORTED,
    UNDECIDED,
    UNSUPPORTED,
    VerificationCase,
    _even_pick,
)
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import encode_query

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
DEFAULT_TAXONOMY = DEFAULT_GOLD_DIR / "document_properties" / "taxonomy-v1.json"
DEFAULT_MAPPING = DEFAULT_GOLD_DIR / "document_properties" / "gold-mapping-v1.json"
DEFAULT_REVIEW = (
    DEFAULT_GOLD_DIR / "document_properties" / "review-false-positives-v1.json"
)
DEFAULT_PRELIM = (
    DEFAULT_GOLD_DIR
    / "document_properties"
    / "review-false-positives-sample-v1.ai-preliminary-review.json"
)

POSITIVE_CAP = 20


@dataclass(frozen=True)
class ValidationReport:
    payload: dict[str, object]


def run_jev_validation(
    config: RetrievalConfig,
    *,
    review_path: Path | None = None,
    prelim_path: Path | None = None,
    taxonomy_path: Path | None = None,
    mapping_path: Path | None = None,
    units: list[StoredUnit] | None = None,
    structures: dict[str, dict[str, object]] | None = None,
    golds=None,
    jev: JevClient | None = None,
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 8.0,
    dense_model: str = "text-embedding-3-large",
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    local_k: int = 5,
) -> ValidationReport:
    taxonomy = load_taxonomy(taxonomy_path)
    mapping = load_gold_mapping(mapping_path)
    gold_rows = golds if golds is not None else load_gold_suite(DEFAULT_GOLD_DIR)
    if units is None:
        units = _load_units(config)
    structures = structures or {}

    by_key = {unit.key: unit for unit in units}
    units_by_path: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        units_by_path[unit.relative_path].append(unit)
    structure_titles = {
        structure_id: str(props.get("title") or "")
        for structure_id, props in structures.items()
    }

    dimension = config.dense_dimension or (len(units[0].dense) if units and units[0].dense else 3072)
    dense_encoder = _dense_encoder(
        RetrievalConfig(
            db_path=config.db_path,
            dense_dimension=dimension,
            dense_model=dense_model,
            openai_api_key=openai_api_key,
            openai_base_url=openai_base_url,
        ),
        dimension,
    )
    sparse_encoder = LexicalSparseEncoder()
    sparse_encoder.fit([unit.text for unit in units])

    properties_by_doc = extract_document_properties(units, structures, taxonomy)
    neighbors = _neighbors(units)
    fp_cases = _fp_cases(review_path or DEFAULT_REVIEW, prelim_path or DEFAULT_PRELIM)
    positive_cases = _positive_cases(
        properties_by_doc, gold_rows, mapping, by_key, structure_titles, neighbors
    )
    cases = positive_cases + fp_cases

    queries = {
        gold.id: encode_query(gold.query, dense=dense_encoder, sparse=sparse_encoder)
        for gold in gold_rows
    }

    client = jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
    outcomes = []
    for case in cases:
        outcomes.append(
            _run_case(
                client,
                case,
                taxonomy,
                units_by_path.get(case.relative_path, []),
                by_key,
                structure_titles,
                queries.get(case.gold_id),
                model=jev_model,
                timeout_seconds=jev_timeout_seconds,
                local_k=local_k,
            )
        )
    metrics = _metrics(outcomes)
    payload = {
        "operation": "jev_validation",
        "experiment": "jev_validation_v1",
        "status": "completed",
        "production_changed": False,
        "default_retriever_unchanged": True,
        "discovery_unchanged": True,
        "taxonomy_unchanged": True,
        "groups": {
            "positive": len(positive_cases),
            "suspected_fp": len(fp_cases),
        },
        "metrics": metrics,
        "outcomes": [_outcome_payload(outcome) for outcome in outcomes],
        "manifest": _manifest(config, units, taxonomy_path, mapping_path, review_path, prelim_path, jev_model, dense_model, local_k),
    }
    return ValidationReport(payload=payload)


@dataclass(frozen=True)
class _ChainOutcome:
    case: VerificationCase
    stage: str  # discovery | local_dense | not_verified
    final: str
    stage1: str
    stage2: str | None
    calls: int
    local_dense_ran: bool
    latency_ms: float
    error: str | None = None


def _run_case(
    client, case, taxonomy, local_units, by_key, structure_titles, query, *, model, timeout_seconds, local_k
) -> _ChainOutcome:
    cited = by_key.get(case.unit_key)
    started = time.perf_counter()
    stage1 = _verify_present(
        client, case, taxonomy, [cited] if cited else [], structure_titles, model, timeout_seconds
    )
    if stage1.effective == SUPPORTED:
        return _ChainOutcome(
            case, "discovery", SUPPORTED, stage1.effective, None, 1, False,
            (time.perf_counter() - started) * 1000.0,
        )
    dense_query, sparse_query = query if query else (None, None)
    top = _dense_top(local_units, dense_query, sparse_query, k=local_k, exclude={case.unit_key})
    candidates = _dedup([cited] if cited else [], top)
    stage2 = _verify_present(client, case, taxonomy, candidates, structure_titles, model, timeout_seconds)
    stage = "local_dense" if stage2.effective == SUPPORTED else "not_verified"
    return _ChainOutcome(
        case, stage, stage2.effective, stage1.effective, stage2.effective, 2, True,
        (time.perf_counter() - started) * 1000.0,
    )


def _dedup(base: list[StoredUnit], top: list[StoredUnit]) -> list[StoredUnit]:
    result: list[StoredUnit] = []
    seen: set[str] = set()
    for unit in base + top:
        if unit.key not in seen:
            seen.add(unit.key)
            result.append(unit)
    return result


def _fp_cases(review_path: Path, prelim_path: Path) -> list[VerificationCase]:
    payload = json.loads(review_path.read_text(encoding="utf-8"))
    prelim_class = _prelim_classifications(prelim_path)
    cases: list[VerificationCase] = []
    for entry in payload.get("entries") or []:
        evidence = (entry.get("evidence") or [])[0] if entry.get("evidence") else {}
        key = (entry["relative_path"], entry["property_class"])
        cases.append(
            VerificationCase(
                group="suspected_fp",
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
                review_classification=prelim_class.get(key),
            )
        )
    return cases


def _prelim_classifications(prelim_path: Path) -> dict[tuple[str, str], str]:
    if prelim_path is None or not prelim_path.is_file():
        return {}
    payload = json.loads(prelim_path.read_text(encoding="utf-8"))
    result: dict[tuple[str, str], str] = {}
    for entry in payload.get("entries") or []:
        review = entry.get("review") or {}
        classification = review.get("classification")
        if classification in {"gold_gap", "wrong_property", "wrong_relation_or_polarity"}:
            result[(entry["relative_path"], entry["property_class"])] = classification
    return result


def _positive_cases(
    properties_by_doc, golds, mapping, by_key, structure_titles, neighbors
) -> list[VerificationCase]:
    cases: list[VerificationCase] = []
    for gold in golds:
        class_ids = mapping.get(gold.id, ())
        if not class_ids:
            continue
        class_id = class_ids[0]
        gold_pos = sorted(set(inventory_groups(gold)))
        count = min(len(gold_pos), POSITIVE_CAP)
        chosen = _even_pick(gold_pos, count)
        for path in chosen:
            item = next(
                (
                    p
                    for p in properties_by_doc.get(path, [])
                    if p.class_id == class_id and p.support == SUPPORTED
                ),
                None,
            )
            if item is None or not item.source_unit_keys:
                continue
            unit = by_key.get(item.source_unit_keys[0])
            if unit is None:
                continue
            previous_text, next_text = neighbors.get(unit.key, ("", ""))
            cases.append(
                VerificationCase(
                    group="positive",
                    gold_id=gold.id,
                    property_class=class_id,
                    relative_path=path,
                    polarity="positive",
                    value="Sweden" if class_id == "governing_law" else "true",
                    unit_key=unit.key,
                    unit_text=unit.text,
                    clause_title=structure_titles.get(unit.structure_id, ""),
                    previous_text=previous_text,
                    next_text=next_text,
                )
            )
    return cases


def _metrics(outcomes: list[_ChainOutcome]) -> dict[str, object]:
    by_group: dict[str, list[_ChainOutcome]] = defaultdict(list)
    for outcome in outcomes:
        by_group[outcome.case.group].append(outcome)

    def counts(group: str) -> dict[str, int]:
        rows = [row for row in by_group.get(group, []) if row.final != "ERROR"]
        return {
            SUPPORTED: sum(1 for row in rows if row.final == SUPPORTED),
            UNSUPPORTED: sum(1 for row in rows if row.final == UNSUPPORTED),
            UNDECIDED: sum(1 for row in rows if row.final == UNDECIDED),
        }

    per_property: dict[str, object] = {}
    for prop in sorted({o.case.property_class for o in outcomes}):
        prop_rows = [o for o in outcomes if o.case.property_class == prop]
        per_property[prop] = {
            "positive": _counts([o for o in prop_rows if o.case.group == "positive"]),
            "suspected_fp": _counts([o for o in prop_rows if o.case.group == "suspected_fp"]),
        }

    positive = counts("positive")
    suspected = counts("suspected_fp")
    n_positive = sum(positive.values())
    n_suspected = sum(suspected.values())

    recall_loss = {
        "total": positive[UNSUPPORTED],
        "rate": positive[UNSUPPORTED] / n_positive if n_positive else None,
        "per_property": {
            prop: per_property[prop]["positive"][UNSUPPORTED] for prop in per_property
        },
    }

    local_dense_rows = [o for o in outcomes if o.local_dense_ran]
    recovered = [o for o in local_dense_rows if o.stage == "local_dense"]

    latencies = [o.latency_ms for o in outcomes]
    calls = [o.calls for o in outcomes]

    return {
        "per_property": per_property,
        "totals": {"positive": positive, "suspected_fp": suspected},
        "recall_loss": recall_loss,
        "uncertain_share": {
            "positive": positive[UNDECIDED] / n_positive if n_positive else None,
            "suspected_fp": suspected[UNDECIDED] / n_suspected if n_suspected else None,
        },
        "preliminary_agreement_30": _preliminary_agreement(outcomes),
        "local_dense": {
            "runs": len(local_dense_rows),
            "recovered": len(recovered),
            "skip_rate": 1 - (len(local_dense_rows) / len(outcomes)) if outcomes else None,
        },
        "latency_ms": _latency_stats(latencies),
        "jev_calls": {
            "total": sum(calls),
            "mean": mean(calls) if calls else 0.0,
        },
        "errors": [o.error for o in outcomes if o.error],
    }


def _counts(rows: list[_ChainOutcome]) -> dict[str, int]:
    clean = [r for r in rows if r.final != "ERROR"]
    return {
        SUPPORTED: sum(1 for r in clean if r.final == SUPPORTED),
        UNSUPPORTED: sum(1 for r in clean if r.final == UNSUPPORTED),
        UNDECIDED: sum(1 for r in clean if r.final == UNDECIDED),
    }


def _preliminary_agreement(outcomes: list[_ChainOutcome]) -> dict[str, object]:
    result: dict[str, dict[str, int]] = {
        "gold_gap": {"supported": 0, "not_supported": 0},
        "wrong_property": {"supported": 0, "not_supported": 0},
        "wrong_relation_or_polarity": {"supported": 0, "not_supported": 0},
    }
    for outcome in outcomes:
        label = outcome.case.review_classification
        if label not in result:
            continue
        if outcome.final == SUPPORTED:
            result[label]["supported"] += 1
        else:
            result[label]["not_supported"] += 1
    return result


def _latency_stats(values: list[float]) -> dict[str, object]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "mean": mean(values),
        "p50": percentile(values, 50) or 0.0,
        "p95": percentile(values, 95) or 0.0,
        "max": max(values),
    }


def _outcome_payload(outcome: _ChainOutcome) -> dict[str, object]:
    payload = dict(outcome.__dict__)
    payload["case"] = dict(outcome.case.__dict__)
    return payload


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


def _load_units(config: RetrievalConfig) -> list[StoredUnit]:
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
    return context.units


def _manifest(config, units, taxonomy_path, mapping_path, review_path, prelim_path, jev_model, dense_model, local_k) -> dict[str, object]:
    def file_hash(path):
        if path is None or not path.is_file():
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return {
        "run_id": "phase2-jev-validation-v1",
        "code_revision": _code_revision(),
        "created_at": datetime.now(UTC).isoformat(),
        "db": str(config.db_path),
        "units": len(units),
        "taxonomy_hash": file_hash(taxonomy_path or DEFAULT_TAXONOMY),
        "mapping_hash": file_hash(mapping_path or DEFAULT_MAPPING),
        "review_hash": file_hash(review_path or DEFAULT_REVIEW),
        "preliminary_hash": file_hash(prelim_path or DEFAULT_PRELIM),
        "jev_model": jev_model,
        "dense_model": dense_model,
        "local_k": local_k,
        "positive_cap": POSITIVE_CAP,
        "presentation": "evidence_clauses_as_primary_text",
        "preliminary_labels_are_not_gold": True,
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


VALIDATION_BASELINE_ID = "phase2-jev-validation-v1"
VALIDATION_BASELINE_PATH = ROOT / "baselines" / f"{VALIDATION_BASELINE_ID}.json"


def write_validation_baseline(payload: dict[str, object], path: Path | None = None) -> Path:
    target = path or VALIDATION_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    frozen = {
        "id": VALIDATION_BASELINE_ID,
        "label": (
            "Frozen broad validation of the Jev verification chain (discovery -> "
            "Jev -> local dense -> Jev with presentation fix). All 111 suspected "
            "false positives plus a balanced >=100 gold-positive sample."
        ),
        "production_changed": False,
        "default_retriever_unchanged": True,
        "discovery_unchanged": True,
        "taxonomy_unchanged": True,
        "groups": payload.get("groups"),
        "metrics": payload.get("metrics"),
        "manifest": payload.get("manifest"),
        "outcomes": payload.get("outcomes"),
    }
    target.write_text(
        json.dumps(frozen, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return target


def write_validation_report(payload: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_validation_markdown(payload), encoding="utf-8")
    return path


def _validation_markdown(payload: dict[str, object]) -> str:
    metrics = payload["metrics"]
    lines = [
        "# Jev chain broad validation v1",
        "",
        (
            "Pipeline: deterministic discovery -> Jev -> document-local dense (gold.query) "
            "-> Jev, with the presentation fix. All 111 suspected false positives plus a "
            "balanced >=100 gold-positive sample. Preliminary AI labels are agreement only, "
            "never definitive gold."
        ),
        "",
        "## Totals",
        "",
        "| Group | SUPPORTED | UNSUPPORTED | UNDECIDED |",
        "|---|---:|---:|---:|",
    ]
    for group, label in (("positive", "positive"), ("suspected_fp", "suspected_fp")):
        row = metrics["totals"][group]
        lines.append(f"| {label} | {row['SUPPORTED']} | {row['UNSUPPORTED']} | {row['UNDECIDED']} |")
    lines.extend(
        [
            "",
            (
                f"recall_loss_total: {metrics['recall_loss']['total']} "
                f"(rate {_fmt(metrics['recall_loss']['rate'])})"
            ),
            f"uncertain_share positive: {_fmt(metrics['uncertain_share']['positive'])}",
            f"uncertain_share suspected_fp: {_fmt(metrics['uncertain_share']['suspected_fp'])}",
            "",
            "## Local dense",
            "",
            "```json",
            json.dumps(metrics["local_dense"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Latency and Jev calls",
            "",
            "```json",
            json.dumps(
                {"latency_ms": metrics["latency_ms"], "jev_calls": metrics["jev_calls"]},
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "## Preliminary agreement (30 labeled FP)",
            "",
            "```json",
            json.dumps(metrics["preliminary_agreement_30"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Per property",
            "",
            "```json",
            json.dumps(metrics["per_property"], ensure_ascii=False, indent=2),
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
