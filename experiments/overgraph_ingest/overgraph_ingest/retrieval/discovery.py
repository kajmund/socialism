"""Document discovery: aggregate passage scores into an independent document signal.

Model-free diagnostic. It reuses the stored dense/sparse vectors and the same
query embeddings as the retrieval comparison, but ranks *documents* by
aggregating their TextUnit scores instead of ranking TextUnits directly. It is
not a new retriever and does not touch production. The point is to measure
whether the discovery bottleneck is the aggregation, not the underlying signal.
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
from overgraph_ingest.metrics import environment_metadata
from overgraph_ingest.retrieval.encode import LexicalSparseEncoder, cosine
from overgraph_ingest.retrieval.evidence_gold import (
    first_group_ranks,
    inventory_groups,
    validate_groups_against_units,
)
from overgraph_ingest.retrieval.gold import RetrievalGold, load_gold_suite
from overgraph_ingest.retrieval.index import StoredUnit, load_published_units
from overgraph_ingest.retrieval.run import _dense_encoder
from overgraph_ingest.retrieval.search import exhaustive_rank, search_units

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GOLD_DIR = ROOT / "retrieval_gold"
UNITS_PER_DOC = 5
DOC_BUDGETS = (10, 20, 50)
AGGREGATIONS = (
    "dense_top1",
    "dense_top3_sum",
    "dense_top3_mean",
    "dense_top5_sum",
    "dense_top5_mean",
)


@dataclass(frozen=True)
class DiscoveryReport:
    payload: dict[str, object]


def aggregate_document_scores(
    units: list[StoredUnit],
    unit_scores: dict[str, float],
) -> dict[str, dict[str, float]]:
    by_path: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        by_path[unit.relative_path].append(unit)
    documents: dict[str, dict[str, float]] = {}
    for path, local in by_path.items():
        scores = sorted(
            [unit_scores.get(unit.key, 0.0) for unit in local],
            reverse=True,
        )
        documents[path] = {
            "dense_top1": scores[0] if scores else 0.0,
            "dense_top3_sum": sum(scores[:3]),
            "dense_top3_mean": mean(scores[:3]) if scores else 0.0,
            "dense_top5_sum": sum(scores[:5]),
            "dense_top5_mean": mean(scores[:5]) if scores else 0.0,
        }
    return documents


def run_document_discovery(
    config: RetrievalConfig,
    *,
    gold_dir: Path | None = None,
    units: list[StoredUnit] | None = None,
    golds: list[RetrievalGold] | None = None,
    queries: dict[str, tuple[list[float], list[tuple[int, float]]]] | None = None,
    doc_budgets: tuple[int, ...] = DOC_BUDGETS,
    units_per_doc: int = UNITS_PER_DOC,
) -> DiscoveryReport:
    if units_per_doc != UNITS_PER_DOC:
        raise ValueError("document discovery keeps the existing five-unit local budget")
    loaded = units if units is not None else _load_units(config)
    gold_rows = golds if golds is not None else load_gold_suite(gold_dir or DEFAULT_GOLD_DIR)
    dimension = _dimension(config, loaded)
    dense_encoder = _dense_encoder(config, dimension)
    sparse_encoder = LexicalSparseEncoder()
    sparse_encoder.fit([unit.text for unit in loaded])
    if queries is None:
        queries = {
            gold.id: _encode_query(gold.query, dense_encoder, sparse_encoder)
            for gold in gold_rows
        }
    db = open_database(config.db_path, dimension)
    try:
        rows = [
            _discovery_row(
                db,
                loaded,
                gold,
                queries[gold.id],
                doc_budgets=doc_budgets,
                units_per_doc=units_per_doc,
            )
            for gold in gold_rows
        ]
    finally:
        db.close()
    macro = _macro(rows, doc_budgets, units_per_doc)
    payload = {
        "operation": "document_discovery",
        "experiment": "document_discovery_v1",
        "status": "completed",
        "production_changed": False,
        "default_retriever_unchanged": True,
        "hypothesis": (
            "Document discovery is the binding loss, and it can be reduced by "
            "aggregating all TextUnit scores per document instead of using only "
            "the best hit. This is a model-free diagnostic, not a retriever."
        ),
        "units_per_doc": units_per_doc,
        "doc_budgets": list(doc_budgets),
        "equal_budget_docs": units_per_doc and 50 // units_per_doc,
        "rows": rows,
        "macro": macro,
        "manifest": _manifest(config, loaded, gold_rows, dimension),
        "limitations": [
            (
                "The discovery signal still uses the same dense embedding; only "
                "the aggregation changes. A ceiling that does not move means the "
                "signal, not the aggregation, is the bottleneck."
            ),
            (
                "Equal-budget comparison is 50 examined TextUnits: hybrid top-50 "
                "versus 10 documents x 5 units."
            ),
            "DocumentRecall is measured against documents that have passage gold.",
        ],
    }
    return DiscoveryReport(payload=payload)


def _discovery_row(
    db,
    units: list[StoredUnit],
    gold: RetrievalGold,
    query: tuple[list[float], list[tuple[int, float]]],
    *,
    doc_budgets: tuple[int, ...],
    units_per_doc: int,
) -> dict[str, object]:
    dense_query, sparse_query = query
    groups = inventory_groups(gold)
    all_groups = tuple(group for values in groups.values() for group in values)
    validate_groups_against_units(all_groups, units)
    docs_with_evidence = set(groups)
    by_path: dict[str, list[StoredUnit]] = defaultdict(list)
    for unit in units:
        by_path[unit.relative_path].append(unit)

    dense_scores = {
        unit.key: cosine(dense_query, unit.dense) if unit.dense is not None else 0.0
        for unit in units
    }
    document_scores = aggregate_document_scores(units, dense_scores)

    baselines = {}
    for units_k in (20, 50):
        hybrid_hits = search_units(
            db,
            units,
            mode="hybrid",
            k=units_k,
            dense_query=dense_query,
            sparse_query=sparse_query,
        )
        dense_hits = search_units(
            db,
            units,
            mode="dense",
            k=units_k,
            dense_query=dense_query,
            sparse_query=sparse_query,
        )
        baselines[f"hybrid_units_{units_k}"] = _baseline(
            hybrid_hits, docs_with_evidence, units_per_doc
        )
        baselines[f"dense_units_{units_k}"] = _baseline(
            dense_hits, docs_with_evidence, units_per_doc
        )

    hybrid_50 = set(baselines["hybrid_units_50"]["documents"])
    arms = {}
    for aggregation in AGGREGATIONS:
        ranked = sorted(
            document_scores,
            key=lambda path: (
                -document_scores[path][aggregation],
                path,
            ),
        )
        arms[aggregation] = _arm_payload(
            ranked,
            by_path,
            dense_query=dense_query,
            sparse_query=sparse_query,
            groups=groups,
            docs_with_evidence=docs_with_evidence,
            hybrid_50=hybrid_50,
            doc_budgets=doc_budgets,
            units_per_doc=units_per_doc,
        )

    return {
        "gold_id": gold.id,
        "split": gold.split,
        "query": gold.query,
        "documents_with_evidence": len(docs_with_evidence),
        "documents_expected": len(gold.relevant_documents),
        "document_gold_without_evidence": [
            path for path in gold.relevant_documents if path not in docs_with_evidence
        ],
        "baselines": baselines,
        "arms": arms,
    }


def _arm_payload(
    ranked: list[str],
    by_path: dict[str, list[StoredUnit]],
    *,
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
    groups: dict[str, tuple],
    docs_with_evidence: set[str],
    hybrid_50: set[str],
    doc_budgets: tuple[int, ...],
    units_per_doc: int,
) -> dict[str, object]:
    at_budget = {}
    for k in doc_budgets:
        selected = ranked[:k]
        found = [path for path in selected if path in docs_with_evidence]
        complete, units_examined = _local_completeness(
            selected,
            by_path,
            groups,
            dense_query=dense_query,
            sparse_query=sparse_query,
            units_per_doc=units_per_doc,
        )
        new_docs = sorted(set(found) - hybrid_50)
        missed_docs = sorted(hybrid_50 - set(found))
        at_budget[str(k)] = {
            "documents_selected": len(selected),
            "documents_found": len(found),
            "document_recall": len(found) / len(docs_with_evidence)
            if docs_with_evidence
            else 0.0,
            "complete_evidence": complete,
            "units_examined": units_examined,
            "new_documents_vs_hybrid50": new_docs,
            "new_documents_count": len(new_docs),
            "missed_vs_hybrid50": missed_docs,
            "missed_count": len(missed_docs),
        }
    return {
        "at_budget": at_budget,
        "units_to_90": _units_to_threshold(
            ranked, by_path, groups, docs_with_evidence, dense_query, sparse_query,
            units_per_doc=units_per_doc, threshold=0.9,
        ),
        "units_to_100": _units_to_threshold(
            ranked, by_path, groups, docs_with_evidence, dense_query, sparse_query,
            units_per_doc=units_per_doc, threshold=1.0,
        ),
        "ordered_documents": ranked[:50],
    }


def _local_completeness(
    selected: list[str],
    by_path: dict[str, list[StoredUnit]],
    groups: dict[str, tuple],
    *,
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
    units_per_doc: int,
) -> tuple[float, int]:
    complete = 0
    examined = 0
    total = 0
    for path in selected:
        doc_groups = groups.get(path)
        if doc_groups is None:
            continue
        total += 1
        local = by_path.get(path, [])
        hits = exhaustive_rank(
            local,
            mode="dense",
            dense_query=dense_query,
            sparse_query=sparse_query,
        )[:units_per_doc]
        examined += len(hits)
        ranks = first_group_ranks(doc_groups, hits)
        if len(ranks) == len(doc_groups):
            complete += 1
    return (complete / total) if total else 0.0, examined


def _units_to_threshold(
    ranked: list[str],
    by_path: dict[str, list[StoredUnit]],
    groups: dict[str, tuple],
    docs_with_evidence: set[str],
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
    *,
    units_per_doc: int,
    threshold: float,
) -> dict[str, object]:
    found = 0
    examined = 0
    for position, path in enumerate(ranked, start=1):
        if path in docs_with_evidence:
            found += 1
        local = by_path.get(path, [])
        examined += min(len(local), units_per_doc)
        recall = found / len(docs_with_evidence) if docs_with_evidence else 0.0
        if recall >= threshold:
            return {
                "status": "reached",
                "documents": position,
                "units_examined": examined,
            }
    return {
        "status": "not_reached",
        "documents": len(ranked),
        "units_examined": examined,
        "max_document_recall": found / len(docs_with_evidence) if docs_with_evidence else 0.0,
    }


def _baseline(
    hits: list,
    docs_with_evidence: set[str],
    units_per_doc: int,
) -> dict[str, object]:
    documents = [hit.relative_path for hit in hits]
    unique = []
    seen = set()
    for path in documents:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    found = [path for path in unique if path in docs_with_evidence]
    return {
        "documents_selected": len(unique),
        "documents_found": len(found),
        "document_recall": len(found) / len(docs_with_evidence)
        if docs_with_evidence
        else 0.0,
        "units_examined": len(hits),
        "documents": unique,
    }


def _macro(
    rows: list[dict[str, object]],
    doc_budgets: tuple[int, ...],
    units_per_doc: int,
) -> dict[str, object]:
    arms = {name: [] for name in AGGREGATIONS}
    baselines = {"hybrid_units_20": [], "hybrid_units_50": [], "dense_units_20": [], "dense_units_50": []}
    for row in rows:
        for name in AGGREGATIONS:
            arms[name].append(row["arms"][name])
    for name, values in baselines.items():
        for row in rows:
            values.append(row["baselines"][name])
    out: dict[str, object] = {}
    for name, values in baselines.items():
        out[name] = {
            "document_recall": mean(value["document_recall"] for value in values),
            "documents_found": sum(value["documents_found"] for value in values),
            "units_examined": sum(value["units_examined"] for value in values),
        }
    for name, values in arms.items():
        out[name] = {
            "document_recall_by_budget": {
                str(k): mean(value["at_budget"][str(k)]["document_recall"] for value in values)
                for k in doc_budgets
            },
            "new_documents_vs_hybrid50": {
                str(k): sum(value["at_budget"][str(k)]["new_documents_count"] for value in values)
                for k in doc_budgets
            },
            "complete_evidence_at_10": mean(
                value["at_budget"]["10"]["complete_evidence"] for value in values
            ),
        }
    return out


def _manifest(
    config: RetrievalConfig,
    units: list[StoredUnit],
    golds: list[RetrievalGold],
    dimension: int,
) -> dict[str, object]:
    return {
        "run_id": "phase2-document-discovery-v1",
        "code_revision": _code_revision(),
        "created_at": datetime.now(UTC).isoformat(),
        "db": str(config.db_path),
        "db_manifest_hash": _file_hash(config.db_path / "manifest.current"),
        "units": len(units),
        "documents": len({unit.relative_path for unit in units}),
        "dense_model": config.dense_model,
        "dense_dimension": dimension,
        "golds": [gold.id for gold in golds],
        "environment": environment_metadata(),
    }


def _encode_query(query, dense, sparse) -> tuple[list[float], list[tuple[int, float]]]:
    return dense.embed([query])[0], sparse.embed([query])[0]


def _load_units(config: RetrievalConfig) -> list[StoredUnit]:
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    db = open_database(config.db_path, dimension)
    try:
        return load_published_units(GraphWriter(db, batch_size=config.write_batch_size))
    finally:
        db.close()


def _dimension(config: RetrievalConfig, units: list[StoredUnit]) -> int:
    if config.dense_dimension is not None:
        return config.dense_dimension
    if units and units[0].dense:
        return len(units[0].dense)
    return 3072


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def write_discovery_report(payload: dict[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_report_markdown(payload), encoding="utf-8")
    return path


def _report_markdown(payload: dict[str, object]) -> str:
    macro = payload["macro"]
    lines = [
        "# Document discovery v1",
        "",
        (
            "Model-free diagnostic. Ranks documents by aggregating their "
            "TextUnit dense scores instead of ranking TextUnits directly. "
            "Production is unchanged; this is not a new retriever."
        ),
        "",
        "Equal budget: hybrid top-50 TextUnits vs 10 documents x 5 units.",
        "",
        "## DocumentRecall at equal budget (10 documents)",
        "",
        "| Arm | Recall@10 docs | New vs hybrid50 | CompleteEvidence@5 |",
        "|---|---:|---:|---:|",
    ]
    for arm in AGGREGATIONS:
        row = macro[arm]
        lines.append(
            f"| {arm} | {row['document_recall_by_budget']['10']:.4f} | "
            f"{row['new_documents_vs_hybrid50']['10']} | {row['complete_evidence_at_10']:.4f} |"
        )
    lines.extend(
        [
            "",
            "| Baseline | Recall | Found docs | Units examined |",
            "|---|---:|---:|---:|",
        ]
    )
    for name in ("hybrid_units_20", "hybrid_units_50", "dense_units_20", "dense_units_50"):
        row = macro[name]
        lines.append(
            f"| {name} | {row['document_recall']:.4f} | {row['documents_found']} | "
            f"{row['units_examined']} |"
        )
    lines.extend(
        [
            "",
            "## Recall by document budget",
            "",
            "| Arm | @10 | @20 | @50 |",
            "|---|---:|---:|---:|",
        ]
    )
    for arm in AGGREGATIONS:
        row = macro[arm]["document_recall_by_budget"]
        lines.append(
            f"| {arm} | {row['10']:.4f} | {row['20']:.4f} | {row['50']:.4f} |"
        )
    lines.extend(["", "## Limitations", ""])
    for limitation in payload["limitations"]:
        lines.append(f"- {limitation}")
    lines.append("")
    return "\n".join(lines)


DISCOVERY_BASELINE_ID = "phase2-document-discovery-v1"
DISCOVERY_BASELINE_PATH = ROOT / "baselines" / f"{DISCOVERY_BASELINE_ID}.json"


def freeze_discovery_baseline(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": DISCOVERY_BASELINE_ID,
        "label": (
            "Frozen document-discovery diagnostic: aggregate TextUnit dense "
            "scores per document and compare against hybrid top-50 at equal "
            "budget. Model-free. Production and default retriever unchanged."
        ),
        "do_not_overwrite": True,
        "does_not_replace_c8": True,
        "does_not_replace_coverage_v3": True,
        "default_retriever_unchanged": True,
        "production_changed": False,
        "hypothesis": payload.get("hypothesis"),
        "units_per_doc": payload.get("units_per_doc"),
        "doc_budgets": payload.get("doc_budgets"),
        "equal_budget_docs": payload.get("equal_budget_docs"),
        "macro": payload.get("macro"),
        "manifest": payload.get("manifest"),
        "limitations": payload.get("limitations"),
        "rows": payload.get("rows"),
    }


def write_discovery_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or DISCOVERY_BASELINE_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            freeze_discovery_baseline(payload),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return target
