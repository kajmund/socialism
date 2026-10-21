"""Presentation-fix experiment for Jev property verification.

Isolated experiment. Reuses the same 50 cases, stage-1 verdicts, and local
dense top-5 as the A/B/C run, but changes only how the candidate TextUnits are
presented to Jev: the top-5 clauses are shown as primary evidence (a list of
full clause texts) instead of appearing only as excerpt choices. Everything
else stays frozen.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from overgraph_ingest.config import RetrievalConfig
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.retrieval.document_properties import load_taxonomy
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder
from overgraph_ingest.retrieval.gold import load_gold_suite
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.jev_end_to_end import _dense_top, _validate
from overgraph_ingest.retrieval.jev_local_query_abc import (
    _cases_from_baseline,
    _dedup_candidates,
    _load_evidence_queries,
)
from overgraph_ingest.retrieval.jev_property_verify import (
    SUPPORTED,
    UNDECIDED,
    UNSUPPORTED,
    VerificationCase,
)
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import encode_query
from overgraph_ingest.tabular.jev_io import proposed_spans

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
DEFAULT_TAXONOMY = DEFAULT_GOLD_DIR / "document_properties" / "taxonomy-v1.json"
DEFAULT_EVIDENCE_QUERIES = (
    DEFAULT_GOLD_DIR / "document_properties" / "evidence-queries-v1.json"
)
DEFAULT_BASELINE = ROOT / "baselines" / "phase2-jev-end-to-end-v1.json"

ARMS = ("A", "B", "C")

VERIFY_INSTRUCTIONS = (
    "Judge whether any of the listed clause texts supports the proposed "
    "document property. SUPPORTED only when a clause text itself asserts the "
    "property with the stated polarity. A heading, a cross-reference, or a "
    "permission is not support for an obligation or prohibition. UNSUPPORTED "
    "when no clause asserts the property. UNDECIDED when it is unclear without "
    "more context. Choose the clause excerpt that supports the property for "
    "SUPPORTED; choose none otherwise."
)


@dataclass(frozen=True)
class PresentationReport:
    payload: dict[str, object]


def run_jev_presentation_v1(
    config: RetrievalConfig,
    *,
    baseline_path: Path | None = None,
    evidence_queries_path: Path | None = None,
    taxonomy_path: Path | None = None,
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
) -> PresentationReport:
    taxonomy = load_taxonomy(taxonomy_path)
    evidence_queries = _load_evidence_queries(evidence_queries_path)
    gold_rows = golds if golds is not None else load_gold_suite(DEFAULT_GOLD_DIR)
    if units is None:
        units = _load_units(config)
    structures = structures or {}
    baseline = json.loads((baseline_path or DEFAULT_BASELINE).read_text(encoding="utf-8"))

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

    cases, stage1_by_case = _cases_from_baseline(baseline)
    arm_queries: dict[str, dict[str, str]] = {"A": {}, "B": {}, "C": {}}
    for gold in gold_rows:
        arm_queries["A"][gold.id] = gold.query
    for class_id, spec in taxonomy.items():
        arm_queries["B"][class_id] = spec.definition
        arm_queries["C"][class_id] = evidence_queries.get(class_id, spec.definition)
    query_vecs: dict[str, dict[str, object]] = {arm: {} for arm in ARMS}
    for arm in ARMS:
        for key, text in arm_queries[arm].items():
            query_vecs[arm][key] = encode_query(text, dense=dense_encoder, sparse=sparse_encoder)

    client = jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)

    arm_results: dict[str, object] = {}
    arm_outcomes: dict[str, list[dict[str, object]]] = {}
    for arm in ARMS:
        metrics, outcomes = _run_arm_present(
            arm,
            cases,
            stage1_by_case,
            arm_queries[arm],
            query_vecs[arm],
            taxonomy,
            units_by_path,
            by_key,
            structure_titles,
            client,
            model=jev_model,
            timeout_seconds=jev_timeout_seconds,
            local_k=local_k,
        )
        arm_results[arm] = metrics
        arm_outcomes[arm] = outcomes

    payload = {
        "operation": "jev_presentation_v1",
        "experiment": "jev_presentation_v1",
        "status": "completed",
        "production_changed": False,
        "default_retriever_unchanged": True,
        "discovery_unchanged": True,
        "taxonomy_unchanged": True,
        "groups": {
            "positive": sum(1 for c in cases if c.group == "positive"),
            "error": sum(1 for c in cases if c.group == "error"),
            "gold_gap": sum(1 for c in cases if c.group == "gold_gap"),
        },
        "arms": arm_results,
        "outcomes": arm_outcomes,
        "manifest": _manifest(config, units, taxonomy_path, evidence_queries_path, baseline_path, jev_model, dense_model, local_k),
    }
    return PresentationReport(payload=payload)


def _run_arm_present(
    arm: str,
    cases: list[VerificationCase],
    stage1_by_case: dict[tuple[str, str], str],
    query_texts: dict[str, str],
    query_vecs: dict[str, object],
    taxonomy,
    units_by_path,
    by_key,
    structure_titles,
    client: JevClient,
    *,
    model: str,
    timeout_seconds: float,
    local_k: int,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    not_verified: list[VerificationCase] = []
    outcomes: list[dict[str, object]] = []
    for case in cases:
        stage1 = stage1_by_case.get((case.relative_path, case.property_class), SUPPORTED)
        local_units = units_by_path.get(case.relative_path, [])
        key = case.gold_id if arm == "A" else case.property_class
        dense_query, sparse_query = query_vecs[key]
        top = _dense_top(local_units, dense_query, sparse_query, k=local_k, exclude={case.unit_key})
        top_keys = [unit.key for unit in top]
        candidates = _dedup_candidates([by_key.get(case.unit_key)] if by_key.get(case.unit_key) else [], top)
        if stage1 != SUPPORTED:
            not_verified.append(case)
            stage2 = _verify_present(client, case, taxonomy, candidates, structure_titles, model, timeout_seconds)
            outcomes.append(
                {
                    "arm": arm,
                    "case": dict(case.__dict__),
                    "stage1": stage1,
                    "stage2": stage2.effective,
                    "recovered": stage2.effective == SUPPORTED,
                    "top5_keys": top_keys,
                    "jev_candidate_keys": [unit.key for unit in candidates],
                }
            )
    metrics = _metrics(not_verified, outcomes)
    return metrics, outcomes


def _verify_present(client, case, taxonomy, candidates, structure_titles, model, timeout_seconds):
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
                SUPPORTED: "A clause asserts the property with the stated polarity.",
                UNSUPPORTED: "No clause asserts the property.",
                UNDECIDED: "Unclear without more context.",
            },
        },
        "source": {
            "type": "choice",
            "instructions": "Pick the clause excerpt that supports the property, or none.",
            "criteria": excerpt_criteria,
        },
    }
    evidence_clauses = [
        {"heading": structure_titles.get(unit.structure_id, ""), "text": unit.text}
        for unit in candidates
    ]
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
                "evidence_clauses": evidence_clauses,
            },
            questions=questions,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — measurement must record, not crash
        return _PresentResult(UNDECIDED, False, UNDECIDED, None, str(exc))
    verdict = _choice(result, "verdict", {SUPPORTED, UNSUPPORTED, UNDECIDED}, UNDECIDED)
    source_id = _choice(result, "source", set(excerpt_criteria), "none")
    source_valid, source_key = _validate(source_id, spans, candidates, case)
    if verdict == SUPPORTED:
        effective = SUPPORTED if source_valid else UNDECIDED
    else:
        effective = verdict
    return _PresentResult(verdict, source_valid, effective, source_key, None)


@dataclass(frozen=True)
class _PresentResult:
    verdict: str
    source_valid: bool
    effective: str
    source_key: str | None
    error: str | None


def _choice(result, key, allowed, default):
    row = result.answers.get(key)
    if not isinstance(row, dict):
        return default
    choice = str(row.get("choice") or "").strip()
    return choice if choice in allowed else default


def _metrics(not_verified: list[VerificationCase], outcomes: list[dict[str, object]]) -> dict[str, object]:
    recovered = [o for o in outcomes if o["recovered"] is True]
    nv_positive_recovered = [
        o for o in outcomes if o["case"]["group"] == "positive" and o["recovered"] is True
    ]
    new_error_supported = [
        o for o in outcomes if o["case"]["group"] == "error" and o["recovered"] is True
    ]
    new_gap_supported = [
        o for o in outcomes if o["case"]["group"] == "gold_gap" and o["recovered"] is True
    ]
    nv_positive = [c for c in not_verified if c.group == "positive"]
    return {
        "not_verified_total": len(not_verified),
        "not_verified_positive_total": len(nv_positive),
        "jev_recovery_5": {
            "recovered_total": len(recovered),
            "not_verified_positive_recovered": len(nv_positive_recovered),
        },
        "new_supported_errors": len(new_error_supported),
        "new_supported_gold_gap": len(new_gap_supported),
    }


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


def _manifest(config, units, taxonomy_path, evidence_queries_path, baseline_path, jev_model, dense_model, local_k) -> dict[str, object]:
    def file_hash(path):
        if path is None or not path.is_file():
            return ""
        return hashlib.sha256(path.read_bytes()).hexdigest()

    return {
        "run_id": "phase2-jev-presentation-v1",
        "code_revision": _code_revision(),
        "created_at": datetime.now(UTC).isoformat(),
        "db": str(config.db_path),
        "units": len(units),
        "taxonomy_hash": file_hash(taxonomy_path or DEFAULT_TAXONOMY),
        "evidence_queries_hash": file_hash(evidence_queries_path or DEFAULT_EVIDENCE_QUERIES),
        "baseline_hash": file_hash(baseline_path or DEFAULT_BASELINE),
        "jev_model": jev_model,
        "dense_model": dense_model,
        "local_k": local_k,
        "presentation": "evidence_clauses_as_primary_text",
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


PRESENT_BASELINE_ID = "phase2-jev-presentation-v1"
PRESENT_BASELINE_PATH = ROOT / "baselines" / f"{PRESENT_BASELINE_ID}.json"


def write_presentation_baseline(payload: dict[str, object], path: Path | None = None) -> Path:
    target = path or PRESENT_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    frozen = {
        "id": PRESENT_BASELINE_ID,
        "label": (
            "Frozen presentation-fix experiment. Same 50 cases, stage-1 verdicts, "
            "and local dense top-5 as the A/B/C run; only the Jev presentation is "
            "changed (top-5 clauses shown as primary evidence)."
        ),
        "production_changed": False,
        "default_retriever_unchanged": True,
        "discovery_unchanged": True,
        "taxonomy_unchanged": True,
        "groups": payload.get("groups"),
        "arms": payload.get("arms"),
        "manifest": payload.get("manifest"),
        "outcomes": payload.get("outcomes"),
    }
    target.write_text(
        json.dumps(frozen, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return target


def write_presentation_report(payload: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_presentation_markdown(payload), encoding="utf-8")
    return path


def _presentation_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Jev presentation fix v1",
        "",
        (
            "Same 50 cases, stage-1 verdicts, and local dense top-5 as the A/B/C run. "
            "Only the Jev presentation changes: top-5 clauses are shown as primary "
            "evidence (`evidence_clauses`), not just excerpt choices."
        ),
        "",
        "| Arm | JevRecovery@5 (all NV) | NV-pos recovered | New FP errors | New SUPPORTED gold-gap |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        m = payload["arms"][arm]
        jr = m["jev_recovery_5"]
        lines.append(
            f"| {arm} | {jr['recovered_total']}/{m['not_verified_total']} "
            f"| {jr['not_verified_positive_recovered']}/{m['not_verified_positive_total']} "
            f"| {m['new_supported_errors']} | {m['new_supported_gold_gap']} |"
        )
    lines.extend(
        [
            "",
            "## Groups",
            "",
            "```json",
            json.dumps(payload["groups"], ensure_ascii=False, indent=2),
            "```",
        ]
    )
    return "\n".join(lines)
