"""End-to-end document-property verification: discovery -> Jev -> local dense -> Jev.

Isolated experiment. Uses the deterministic discovery's own TextUnit first. Local
dense runs only when Jev does not SUPPORT the first citation. A second
UNSUPPORTED means NOT_VERIFIED (the document stays a candidate), not that the
property is absent. Discovery, taxonomy, and gold are unchanged.
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
    extract_document_properties,
    load_gold_mapping,
    load_taxonomy,
)
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.evidence_gold import inventory_groups
from overgraph_ingest.retrieval.gold import RetrievalGold, load_gold_suite
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.jev_property_verify import (
    POSITIVE_ALLOCATION,
    SUPPORTED,
    UNDECIDED,
    UNSUPPORTED,
    VerificationCase,
    _even_pick,
    build_review_controls,
)
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import encode_query, exhaustive_rank
from overgraph_ingest.tabular.jev_io import proposed_spans

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
DEFAULT_TAXONOMY = DEFAULT_GOLD_DIR / "document_properties" / "taxonomy-v1.json"
DEFAULT_MAPPING = DEFAULT_GOLD_DIR / "document_properties" / "gold-mapping-v1.json"

VERIFY_INSTRUCTIONS = (
    "Judge whether the listed excerpt supports the proposed document property. "
    "SUPPORTED only when an excerpt itself asserts the property with the stated "
    "polarity. A heading, a cross-reference, or a permission is not support for "
    "an obligation or prohibition. UNSUPPORTED when no excerpt asserts the "
    "property. UNDECIDED when it is unclear without more context. Choose one "
    "listed excerpt for SUPPORTED; choose none otherwise."
)


@dataclass(frozen=True)
class E2EOutcome:
    case: VerificationCase
    stage: str  # discovery | local_dense | not_verified
    stage1: str
    stage2: str | None
    calls: int
    local_dense_ran: bool
    latency_ms: float
    source_valid: bool
    error: str | None = None


@dataclass(frozen=True)
class E2EReport:
    payload: dict[str, object]


def run_jev_end_to_end(
    config: RetrievalConfig,
    *,
    review_path: Path | None,
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
    dense_model: str = "text-embedding-3-large",
    openai_api_key: str | None = None,
    openai_base_url: str | None = None,
    local_k: int = 5,
) -> E2EReport:
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
    if review_path is None:
        raise RuntimeError("--jev-end-to-end requires --jev-property-review")

    by_key = {unit.key: unit for unit in units}
    structure_titles = {
        structure_id: str(props.get("title") or "")
        for structure_id, props in structures.items()
    }
    neighbors = _neighbors(units)
    units_by_path: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        units_by_path[unit.relative_path].append(unit)

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
    queries = {
        gold.id: encode_query(gold.query, dense=dense_encoder, sparse=sparse_encoder)
        for gold in gold_rows
    }

    properties_by_doc = extract_document_properties(units, structures, taxonomy)
    positives = _positive_cases(
        properties_by_doc, gold_rows, mapping, by_key, structure_titles, neighbors
    )
    errors, gaps = build_review_controls(review_path)
    cases = positives + errors + gaps

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
                queries.get(case.gold_id),
                model=jev_model,
                timeout_seconds=jev_timeout_seconds,
                local_k=local_k,
            )
        )
    metrics = _metrics(outcomes)
    payload = {
        "operation": "jev_end_to_end",
        "experiment": "jev_end_to_end_v1",
        "status": "completed",
        "production_changed": False,
        "default_retriever_unchanged": True,
        "discovery_unchanged": True,
        "taxonomy_unchanged": True,
        "groups": {"positive": len(positives), "error": len(errors), "gold_gap": len(gaps)},
        "metrics": metrics,
        "outcomes": [_outcome_payload(outcome) for outcome in outcomes],
        "manifest": _manifest(config, units, taxonomy_path, mapping_path, review_path, jev_model, dense_model, local_k),
    }
    return E2EReport(payload=payload)


def _run_case(
    client: JevClient,
    case: VerificationCase,
    taxonomy: dict[str, PropertyClass],
    local_units: list[StoredUnit],
    by_key: dict[str, StoredUnit],
    query,
    *,
    model: str,
    timeout_seconds: float,
    local_k: int,
) -> E2EOutcome:
    cited = by_key.get(case.unit_key)
    started = time.perf_counter()
    stage1 = _verify(client, case, taxonomy, [cited] if cited else [], model, timeout_seconds)
    if stage1.effective == SUPPORTED:
        return E2EOutcome(
            case=case,
            stage="discovery",
            stage1=stage1.effective,
            stage2=None,
            calls=1,
            local_dense_ran=False,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            source_valid=stage1.source_valid,
        )
    dense_query, sparse_query = query if query else (None, None)
    top = _dense_top(local_units, dense_query, sparse_query, k=local_k, exclude={case.unit_key})
    candidates = [cited] if cited else []
    seen = {case.unit_key}
    for unit in top:
        if unit.key not in seen:
            seen.add(unit.key)
            candidates.append(unit)
    stage2 = _verify(client, case, taxonomy, candidates, model, timeout_seconds)
    stage = "local_dense" if stage2.effective == SUPPORTED else "not_verified"
    return E2EOutcome(
        case=case,
        stage=stage,
        stage1=stage1.effective,
        stage2=stage2.effective,
        calls=2,
        local_dense_ran=True,
        latency_ms=(time.perf_counter() - started) * 1000.0,
        source_valid=stage2.source_valid,
    )


def _verify(
    client: JevClient,
    case: VerificationCase,
    taxonomy: dict[str, PropertyClass],
    candidates: list[StoredUnit],
    model: str,
    timeout_seconds: float,
):
    spec = taxonomy.get(case.property_class)
    definition = spec.definition if spec else ""
    label = spec.label if spec else case.property_class
    spans = proposed_spans(candidates)
    excerpt_criteria = {span["id"]: span["text"] for span in spans}
    excerpt_criteria["none"] = "No listed excerpt supports the property."
    questions = {
        "verdict": {
            "type": "choice",
            "instructions": VERIFY_INSTRUCTIONS,
            "criteria": {
                SUPPORTED: "An excerpt asserts the property with the stated polarity.",
                UNSUPPORTED: "No excerpt asserts the property.",
                UNDECIDED: "Unclear without more context.",
            },
        },
        "source": {
            "type": "choice",
            "instructions": "Pick one listed excerpt that supports the property, or none.",
            "criteria": excerpt_criteria,
        },
    }
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
        return _VerifyResult(UNDECIDED, False, UNDECIDED, None, str(exc))
    verdict = _choice(result, "verdict", {SUPPORTED, UNSUPPORTED, UNDECIDED}, UNDECIDED)
    source_id = _choice(result, "source", set(excerpt_criteria), "none")
    source_valid, source_key = _validate(source_id, spans, candidates, case)
    if verdict == SUPPORTED:
        effective = SUPPORTED if source_valid else UNDECIDED
    else:
        effective = verdict
    return _VerifyResult(verdict, source_valid, effective, source_key, None)


@dataclass(frozen=True)
class _VerifyResult:
    verdict: str
    source_valid: bool
    effective: str
    source_key: str | None
    error: str | None


def _positive_cases(
    properties_by_doc: dict[str, list],
    golds: list[RetrievalGold],
    mapping: dict[str, tuple[str, ...]],
    by_key: dict[str, StoredUnit],
    structure_titles: dict[str, str],
    neighbors: dict[str, tuple[str, str]],
) -> list[VerificationCase]:
    cases: list[VerificationCase] = []
    for gold in golds:
        class_ids = mapping.get(gold.id, ())
        if not class_ids:
            continue
        class_id = class_ids[0]
        gold_pos = sorted(set(inventory_groups(gold)))
        chosen = _even_pick(gold_pos, POSITIVE_ALLOCATION.get(gold.id, 2))
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


def _dense_top(
    local_units: list[StoredUnit],
    dense_query,
    sparse_query,
    *,
    k: int,
    exclude: set[str],
) -> list[StoredUnit]:
    if dense_query is None:
        return []
    ranked = exhaustive_rank(
        local_units,
        mode="dense",
        dense_query=dense_query,
        sparse_query=sparse_query,
    )
    by_key = {unit.key: unit for unit in local_units}
    result = []
    for hit in ranked:
        if hit.key in exclude:
            continue
        unit = by_key.get(hit.key)
        if unit is not None:
            result.append(unit)
        if len(result) >= k:
            break
    return result


def _validate(source_id, spans, candidates, case):
    if source_id == "none":
        return False, None
    span = next((item for item in spans if item["id"] == source_id), None)
    if span is None:
        return False, None
    unit = next(
        (item for item in candidates if item.key == span.get("unit_id")),
        None,
    )
    if unit is None:
        return False, None
    validated = validate_source(
        str(span.get("text") or ""), unit=unit, document_id=unit.document_id
    )
    return (validated.validated, unit.key) if validated.validated else (False, None)


def _metrics(outcomes: list[E2EOutcome]) -> dict[str, object]:
    by_group: dict[str, list[E2EOutcome]] = defaultdict(list)
    for outcome in outcomes:
        by_group[outcome.case.group].append(outcome)

    def stages(group: str) -> dict[str, int]:
        rows = by_group.get(group, [])
        return {
            "verified_at_discovery": sum(1 for row in rows if row.stage == "discovery"),
            "verified_after_local_dense": sum(1 for row in rows if row.stage == "local_dense"),
            "not_verified": sum(1 for row in rows if row.stage == "not_verified"),
        }

    positive = stages("positive")
    error = stages("error")
    gap = stages("gold_gap")
    non_supported_first = [
        row for row in outcomes if row.stage1 != SUPPORTED
    ]
    recovered = [row for row in non_supported_first if row.stage2 == SUPPORTED]
    latencies = [row.latency_ms for row in outcomes]
    return {
        "positive": positive,
        "error": error,
        "gold_gap": gap,
        "recovery_count": len(recovered),
        "recovery_rate_of_non_supported": (
            len(recovered) / len(non_supported_first) if non_supported_first else None
        ),
        "local_dense_runs": sum(1 for row in outcomes if row.local_dense_ran),
        "local_dense_skip_rate": (
            1 - (sum(1 for row in outcomes if row.local_dense_ran) / len(outcomes))
        ) if outcomes else None,
        "jev_calls": {
            "total": sum(row.calls for row in outcomes),
            "mean": mean([row.calls for row in outcomes]),
        },
        "latency_ms": _latency_stats(latencies),
        "errors": [row.error for row in outcomes if row.error],
    }


def _latency_stats(values: list[float]) -> dict[str, object]:
    if not values:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    from overgraph_ingest.metrics import percentile

    return {
        "mean": mean(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": max(values),
    }


def _choice(result: JevResult, key: str, allowed: set[str], default: str) -> str:
    row = result.answers.get(key)
    if not isinstance(row, dict):
        return default
    choice = str(row.get("choice") or "").strip()
    return choice if choice in allowed else default


def _outcome_payload(outcome: E2EOutcome) -> dict[str, object]:
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


def _manifest(config, units, taxonomy_path, mapping_path, review_path, jev_model, dense_model, local_k) -> dict[str, object]:
    def file_hash(path):
        if path is None or not path.is_file():
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return {
        "run_id": "phase2-jev-end-to-end-v1",
        "code_revision": _code_revision(),
        "created_at": datetime.now(UTC).isoformat(),
        "db": str(config.db_path),
        "units": len(units),
        "taxonomy_hash": file_hash(taxonomy_path or DEFAULT_TAXONOMY),
        "mapping_hash": file_hash(mapping_path or DEFAULT_MAPPING),
        "review_hash": file_hash(review_path),
        "jev_model": jev_model,
        "dense_model": dense_model,
        "local_k": local_k,
        "undecided_is_not_unsupported": True,
        "second_unsupported_means_not_verified": True,
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


E2E_BASELINE_ID = "phase2-jev-end-to-end-v1"
E2E_BASELINE_PATH = ROOT / "baselines" / f"{E2E_BASELINE_ID}.json"


def write_e2e_baseline(payload: dict[str, object], path: Path | None = None) -> Path:
    target = path or E2E_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    frozen = {
        "id": E2E_BASELINE_ID,
        "label": (
            "Frozen end-to-end document-property verification. Discovery is unchanged; "
            "Jev verifies the discovery citation, then document-local dense supplements "
            "only when needed. A second UNSUPPORTED means NOT_VERIFIED."
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


def write_e2e_report(payload: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_e2e_markdown(payload), encoding="utf-8")
    return path


def _e2e_markdown(payload: dict[str, object]) -> str:
    metrics = payload["metrics"]
    lines = [
        "# Jev end-to-end verification v1",
        "",
        (
            "Deterministic discovery -> Jev -> document-local dense -> Jev. "
            "Local dense runs only when Jev does not SUPPORT the first citation. "
            "A second UNSUPPORTED means NOT_VERIFIED, not absent."
        ),
        "",
        "## Groups",
        "",
        "```json",
        json.dumps(payload["groups"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Stage counts",
        "",
        "| Group | verified_at_discovery | verified_after_local_dense | not_verified |",
        "|---|---:|---:|---:|",
    ]
    for group in ("positive", "error", "gold_gap"):
        row = metrics[group]
        lines.append(
            f"| {group} | {row['verified_at_discovery']} | {row['verified_after_local_dense']} | {row['not_verified']} |"
        )
    lines.extend(
        [
            "",
            f"recovery_count (UNSUPPORTED -> SUPPORTED after local dense): {metrics['recovery_count']}",
            f"recovery_rate_of_non_supported: {_fmt(metrics['recovery_rate_of_non_supported'])}",
            f"local_dense_runs: {metrics['local_dense_runs']}",
            f"local_dense_skip_rate: {_fmt(metrics['local_dense_skip_rate'])}",
            "",
            "## Jev calls and latency",
            "",
            "```json",
            json.dumps(
                {"jev_calls": metrics["jev_calls"], "latency_ms": metrics["latency_ms"]},
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "## Errors",
            "",
            "```json",
            json.dumps(metrics["errors"], ensure_ascii=False, indent=2),
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
