"""A/B/C comparison of the document-local dense query for evidence supplement.

Isolated experiment. Uses the same 50 document-property cases and the same
frozen discovery signal and stage-1 verdicts as the end-to-end run. Three arms
differ only in the query text fed to document-local dense:

  A - gold.query (inventory question)
  B - the frozen property definition
  C - an evidence description derived from the definition

Measures EvidenceRecall@5 (does the correct supporting TextUnit appear in the
top-5) and JevRecovery@5 (do previously NOT_VERIFIED cases become SUPPORTED
when Jev receives the top-5). Candidate keys are recorded so a presentation
problem is distinguishable from a search problem. Discovery, taxonomy, and gold
are unchanged.
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
from overgraph_ingest.retrieval.jev_end_to_end import _dense_top, _verify
from overgraph_ingest.retrieval.jev_property_verify import (
    SUPPORTED,
    VerificationCase,
    _gold_evidence_unit,
)
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import encode_query

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
DEFAULT_TAXONOMY = DEFAULT_GOLD_DIR / "document_properties" / "taxonomy-v1.json"
DEFAULT_EVIDENCE_QUERIES = (
    DEFAULT_GOLD_DIR / "document_properties" / "evidence-queries-v1.json"
)
DEFAULT_BASELINE = ROOT / "baselines" / "phase2-jev-end-to-end-v1.json"

ARMS = ("A", "B", "C")


@dataclass(frozen=True)
class ABCReport:
    payload: dict[str, object]


def run_jev_local_query_abc(
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
) -> ABCReport:
    taxonomy = load_taxonomy(taxonomy_path)
    evidence_queries = _load_evidence_queries(evidence_queries_path)
    gold_rows = golds if golds is not None else load_gold_suite(DEFAULT_GOLD_DIR)
    if units is None:
        units = _load_units(config)
    baseline = json.loads((baseline_path or DEFAULT_BASELINE).read_text(encoding="utf-8"))

    by_key = {unit.key: unit for unit in units}
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

    cases, stage1_by_case = _cases_from_baseline(baseline)
    gold_by_id = {gold.id: gold for gold in gold_rows}

    # Encode arm queries. A is per-gold; B and C are per-class.
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
        results = _run_arm(
            arm,
            cases,
            stage1_by_case,
            arm_queries[arm],
            query_vecs[arm],
            taxonomy,
            gold_by_id,
            units_by_path,
            by_key,
            client,
            model=jev_model,
            timeout_seconds=jev_timeout_seconds,
            local_k=local_k,
        )
        arm_results[arm] = results["metrics"]
        arm_outcomes[arm] = results["outcomes"]

    payload = {
        "operation": "jev_local_query_abc",
        "experiment": "jev_local_query_abc_v1",
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
    return ABCReport(payload=payload)


def _run_arm(
    arm: str,
    cases: list[VerificationCase],
    stage1_by_case: dict[tuple[str, str], str],
    query_texts: dict[str, str],
    query_vecs: dict[str, object],
    taxonomy,
    gold_by_id,
    units_by_path,
    by_key,
    client: JevClient,
    *,
    model: str,
    timeout_seconds: float,
    local_k: int,
) -> dict[str, object]:
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
        gold_hit = None
        if case.group == "positive":
            gold = gold_by_id.get(case.gold_id)
            if gold is not None:
                gold_unit = _gold_evidence_unit(gold, case.relative_path, local_units)
                gold_hit = (gold_unit.key in top_keys) if gold_unit is not None else None
        if stage1 != SUPPORTED:
            not_verified.append(case)
            stage2 = _verify(client, case, taxonomy, candidates, model, timeout_seconds)
            outcomes.append(
                {
                    "arm": arm,
                    "case": dict(case.__dict__),
                    "stage1": stage1,
                    "stage2": stage2.effective,
                    "recovered": stage2.effective == SUPPORTED,
                    "top5_keys": top_keys,
                    "jev_candidate_keys": [unit.key for unit in candidates],
                    "gold_evidence_hit": gold_hit,
                }
            )
        else:
            outcomes.append(
                {
                    "arm": arm,
                    "case": dict(case.__dict__),
                    "stage1": stage1,
                    "stage2": None,
                    "recovered": None,
                    "top5_keys": top_keys,
                    "jev_candidate_keys": [unit.key for unit in candidates],
                    "gold_evidence_hit": gold_hit,
                }
            )
    metrics = _arm_metrics(not_verified, cases, outcomes)
    return {"metrics": metrics, "outcomes": outcomes}


def _arm_metrics(
    not_verified: list[VerificationCase],
    cases: list[VerificationCase],
    outcomes: list[dict[str, object]],
) -> dict[str, object]:
    positive_hits = [
        o for o in outcomes
        if o["case"]["group"] == "positive" and o["gold_evidence_hit"] is True
    ]
    nv_positive = [
        o for o in outcomes
        if o["case"]["group"] == "positive" and o["stage1"] != SUPPORTED
    ]
    nv_positive_hit = [o for o in nv_positive if o["gold_evidence_hit"] is True]
    recovered = [o for o in outcomes if o["recovered"] is True]
    nv_positive_recovered = [
        o for o in outcomes if o["case"]["group"] == "positive" and o["recovered"] is True
    ]
    new_error_supported = [
        o for o in outcomes
        if o["case"]["group"] == "error" and o["recovered"] is True
    ]
    new_gap_supported = [
        o for o in outcomes
        if o["case"]["group"] == "gold_gap" and o["recovered"] is True
    ]
    total_positive = sum(1 for c in cases if c.group == "positive")
    return {
        "not_verified_total": len(not_verified),
        "evidence_recall_5": {
            "positive_total": total_positive,
            "positive_hit": len(positive_hits),
            "not_verified_positive_total": len(nv_positive),
            "not_verified_positive_hit": len(nv_positive_hit),
        },
        "jev_recovery_5": {
            "recovered_total": len(recovered),
            "not_verified_positive_recovered": len(nv_positive_recovered),
        },
        "new_supported_errors": len(new_error_supported),
        "new_supported_gold_gap": len(new_gap_supported),
    }


def _cases_from_baseline(baseline: dict[str, object]) -> tuple[list[VerificationCase], dict[tuple[str, str], str]]:
    cases: list[VerificationCase] = []
    stage1: dict[tuple[str, str], str] = {}
    for outcome in baseline["outcomes"]:
        c = outcome["case"]
        case = VerificationCase(
            group=c["group"],
            gold_id=c["gold_id"],
            property_class=c["property_class"],
            relative_path=c["relative_path"],
            polarity=c.get("polarity"),
            value=c["value"],
            unit_key=c["unit_key"],
            unit_text=c.get("unit_text", ""),
            clause_title=c.get("clause_title", ""),
            previous_text=c.get("previous_text", ""),
            next_text=c.get("next_text", ""),
            review_classification=c.get("review_classification"),
        )
        cases.append(case)
        stage1[(case.relative_path, case.property_class)] = outcome["stage1"]
    return cases, stage1


def _dedup_candidates(base: list[StoredUnit], top: list[StoredUnit]) -> list[StoredUnit]:
    result: list[StoredUnit] = []
    seen: set[str] = set()
    for unit in base + top:
        if unit.key not in seen:
            seen.add(unit.key)
            result.append(unit)
    return result


def _load_evidence_queries(path: Path | None) -> dict[str, str]:
    target = path or DEFAULT_EVIDENCE_QUERIES
    payload = json.loads(target.read_text(encoding="utf-8"))
    return payload["queries"]


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
        "run_id": "phase2-jev-local-query-abc-v1",
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
        "arms": list(ARMS),
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


ABC_BASELINE_ID = "phase2-jev-local-query-abc-v1"
ABC_BASELINE_PATH = ROOT / "baselines" / f"{ABC_BASELINE_ID}.json"


def write_abc_baseline(payload: dict[str, object], path: Path | None = None) -> Path:
    target = path or ABC_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    frozen = {
        "id": ABC_BASELINE_ID,
        "label": (
            "Frozen A/B/C comparison of the document-local dense query. Same 50 "
            "cases and stage-1 verdicts as the end-to-end run. Discovery, "
            "taxonomy, and gold are unchanged."
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


def write_abc_report(payload: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_abc_markdown(payload), encoding="utf-8")
    return path


def _abc_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Jev local dense query A/B/C v1",
        "",
        (
            "Same 50 document-property cases and stage-1 verdicts as the end-to-end run. "
            "Three arms differ only in the query text for document-local dense."
        ),
        "",
        "| Arm | Query | EvidenceRecall@5 (pos) | NV-pos hit | JevRecovery@5 (all NV) | NV-pos recovered | New FP errors | New SUPPORTED gold-gap |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        m = payload["arms"][arm]
        er = m["evidence_recall_5"]
        jr = m["jev_recovery_5"]
        row = (
            f"| {arm} | {_arm_label(arm)} | {er['positive_hit']}/{er['positive_total']} "
            f"| {er['not_verified_positive_hit']}/{er['not_verified_positive_total']} "
            f"| {jr['recovered_total']}/{m['not_verified_total']} "
            f"| {jr['not_verified_positive_recovered']}/{er['not_verified_positive_total']} "
            f"| {m['new_supported_errors']} | {m['new_supported_gold_gap']} |"
        )
        lines.append(row)
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


def _arm_label(arm: str) -> str:
    return {"A": "gold.query", "B": "definition", "C": "evidence description"}[arm]
