"""Compare structure-only A with Jev B. Reuse frozen document-type B."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from overgraph_ingest.doctags.catalog import CATALOG_VERSION
from overgraph_ingest.doctags.classification import (
    classification_record,
    load_frozen_classifications,
)
from overgraph_ingest.doctags.context import TagDocument, load_tag_documents
from overgraph_ingest.doctags.evaluate import decide, pair_variants, summarize
from overgraph_ingest.doctags.extract import document_opening, document_title, extract_b
from overgraph_ingest.doctags.gold import GOLD_ID
from overgraph_ingest.doctags.gold_eval import require_document_tags_gold
from overgraph_ingest.doctags.store import prove_store_filter_corrections
from overgraph_ingest.doctags.variant_a import extract_a
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.tabular.jev_io import CountingJev
from overgraph_ingest.tabular.run import DEFAULT_DB

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
DOCUMENT_TAGS_RUN_ID = "phase2-document-tags-v1"
DOCUMENT_TAGS_RUN_PATH = ROOT / "baselines" / f"{DOCUMENT_TAGS_RUN_ID}.json"
VARIANT_A = "A"
VARIANT_B = "B"
VARIANTS = (VARIANT_A, VARIANT_B)


def run_document_tags(
    *,
    db_path: Path | None = None,
    dense_dimension: int = 3072,
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 20.0,
    documents: list[TagDocument] | None = None,
    jev: JevClient | None = None,
    variants: tuple[str, ...] = VARIANTS,
    store_db_path: Path | None = None,
    gold_path: Path | None = None,
    classification_path: Path | None = None,
    require_gold: bool = True,
) -> dict[str, object]:
    if require_gold:
        require_document_tags_gold(gold_path)
    frozen = {
        path: classification_record(row)
        for path, row in load_frozen_classifications(classification_path).items()
    }
    loaded = documents if documents is not None else load_tag_documents(
        db_path=db_path or DEFAULT_DB,
        dense_dimension=dense_dimension,
    )
    missing = [item.relative_path for item in loaded if item.relative_path not in frozen]
    if missing:
        raise ValueError(f"frozen classification missing paths: {missing}")
    if VARIANT_B in variants:
        if jev is None and not typesafe_api_key:
            raise ValueError("--typesafe-api-key is required for document-tag B")
    client = None
    if VARIANT_B in variants:
        client = jev if isinstance(jev, CountingJev) else CountingJev(
            jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
        )
    started = time.perf_counter()
    scored: dict[str, list[dict[str, object]]] = {name: [] for name in variants}
    cost_rows: dict[str, list[dict[str, float]]] = {name: [] for name in variants}
    for item in loaded:
        classification = frozen[item.relative_path]
        if VARIANT_A in variants:
            rows = extract_a(
                relative_path=item.relative_path,
                document_id=item.document_id,
                units=list(item.units),
            )
            scored[VARIANT_A].extend(rows)
            cost_rows[VARIANT_A].append({"latency_ms": 0.0, "jev_calls": 0.0})
            print(f"A {item.relative_path} {len(rows)}", file=sys.stderr, flush=True)
        if VARIANT_B in variants:
            rows, latency_ms, calls, model = extract_b(
                client,
                relative_path=item.relative_path,
                document_id=item.document_id,
                document_type=str(classification["predicted_type"]),
                title=document_title(list(item.units), item.relative_path),
                opening=document_opening(list(item.units)),
                units=list(item.units),
                model=jev_model,
                timeout_seconds=jev_timeout_seconds,
            )
            for row in rows:
                row["latency_ms"] = latency_ms
                row["jev_calls"] = calls
                row["model"] = model
            scored[VARIANT_B].extend(rows)
            cost_rows[VARIANT_B].append({"latency_ms": latency_ms, "jev_calls": float(calls)})
            print(f"B {item.relative_path} {len(rows)}", file=sys.stderr, flush=True)
    summaries = {name: summarize(rows) for name, rows in scored.items()}
    for name, summary in summaries.items():
        summary["jev_calls"] = int(sum(row["jev_calls"] for row in cost_rows[name]))
        summary["latency_ms"] = _mean([row["latency_ms"] for row in cost_rows[name]])
    paired = {}
    if VARIANT_A in summaries and VARIANT_B in summaries:
        paired["A_B"] = pair_variants(summaries[VARIANT_A], summaries[VARIANT_B])
    store = prove_store_filter_corrections(
        [frozen[item.relative_path] for item in loaded],
        scored.get(VARIANT_B) or scored.get(VARIANT_A) or [],
        db_path=store_db_path or (db_path or DEFAULT_DB).parent / "document-tags-filter-v1",
    )
    wall_seconds = time.perf_counter() - started
    return {
        "operation": "document_tags_run",
        "experiment": DOCUMENT_TAGS_RUN_ID,
        "gold_id": GOLD_ID,
        "catalog_version": CATALOG_VERSION,
        "reuses_frozen_doctype_b": True,
        "does_not_rerun_doctype_jev": True,
        "does_not_change_text_units": True,
        "does_not_change_retrieval": True,
        "does_not_change_answer_cell": True,
        "does_not_change_default_hybrid": True,
        "does_not_change_doctype_baseline": True,
        "default_remains_d": True,
        "no_production_integration": True,
        "no_automatic_approval_threshold": True,
        "confidence_is_not_legal_probability": True,
        "prepared_knowledge_not_legal_proof": True,
        "documents": [item.relative_path for item in loaded],
        "classifications": list(frozen.values()),
        "variants": {
            name: {
                "variant": name,
                "method": "structure" if name == VARIANT_A else "jev",
                "summary": summaries[name],
            }
            for name in variants
        },
        "scored": scored,
        "paired": paired,
        "store": store,
        "headline": summaries,
        "decision": decide(summaries),
        "cost": {
            "jev_calls": summaries.get(VARIANT_B, {}).get("jev_calls", 0),
            "jev_calls_per_document": {
                name: 1.0 if name == VARIANT_B else 0.0 for name in variants
            },
            "latency_ms_per_document": {
                name: summaries[name]["latency_ms"] for name in variants
            },
            "wall_seconds": wall_seconds,
            "filter_seconds": store["filter_seconds"],
            "store_write_seconds": store["write_seconds"],
        },
        "jev_calls": summaries.get(VARIANT_B, {}).get("jev_calls", 0),
        "wall_seconds": wall_seconds,
    }


def freeze_document_tags_run(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": DOCUMENT_TAGS_RUN_ID,
        "label": (
            "Document tags and stored classification. Structure-only A vs "
            "Jev B on frozen document type plus relevant text."
        ),
        "do_not_overwrite": True,
        "reuses_frozen_doctype_b": True,
        "does_not_rerun_doctype_jev": True,
        "does_not_change_text_units": True,
        "does_not_change_retrieval": True,
        "does_not_change_answer_cell": True,
        "does_not_change_doctype_baseline": True,
        "default_remains_d": True,
        "no_production_integration": True,
        "no_automatic_approval_threshold": True,
        "confidence_is_not_legal_probability": True,
        "prepared_knowledge_not_legal_proof": True,
        "gold_id": payload.get("gold_id"),
        "catalog_version": payload.get("catalog_version"),
        "documents": payload.get("documents"),
        "headline": payload.get("headline"),
        "decision": payload.get("decision"),
        "store": payload.get("store"),
        "cost": payload.get("cost"),
        "paired": payload.get("paired"),
        "variants": {
            name: variant["summary"] for name, variant in payload["variants"].items()
        },
        "scored": payload.get("scored"),
        "classifications": payload.get("classifications"),
        "jev_calls": payload.get("jev_calls"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_document_tags_run_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or DOCUMENT_TAGS_RUN_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_document_tags_run(payload), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return target


def write_document_tags_run_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "document-tags-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    cost = payload["cost"]
    lines = [
        "# Document tags at ingest",
        "",
        "Prepared document knowledge, not legal proof.",
        "Classification is reused from frozen document-type B.",
        "A is deterministic extraction. B is one Jev call per document.",
        "User corrections survive re-ingest. No approval threshold.",
        "",
        "| Variant | Precision | Recall | Hits | Extras | Misses | Jev/doc | Latency ms/doc |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in (VARIANT_A, VARIANT_B):
        if name not in payload["variants"]:
            continue
        summary = payload["variants"][name]["summary"]
        lines.append(
            "| {name} | {precision} | {recall} | {hits} | {extras} | {misses} | {calls} | {latency} |".format(
                name=name,
                precision=_pct(summary["precision"]),
                recall=_pct(summary["recall"]),
                hits=summary["hits"],
                extras=summary["extras"],
                misses=summary["misses"],
                calls=_num(cost["jev_calls_per_document"].get(name)),
                latency=_num(cost["latency_ms_per_document"].get(name)),
            )
        )
    lines.extend(["", "## Per class", ""])
    for name in (VARIANT_A, VARIANT_B):
        if name not in payload["variants"]:
            continue
        lines.extend(
            [f"### {name}", "", "| Class | Precision | Recall | Gold |", "|---|---:|---:|---:|"]
        )
        for tag_class, scores in payload["variants"][name]["summary"]["per_class"].items():
            lines.append(
                "| {tag_class} | {precision} | {recall} | {gold} |".format(
                    tag_class=tag_class,
                    precision=_pct(scores["precision"]),
                    recall=_pct(scores["recall"]),
                    gold=scores["gold_n"],
                )
            )
        lines.append("")
    store = payload["store"]
    lines.extend(
        [
            "## Cost and storage",
            "",
            f"Total Jev calls: {payload['jev_calls']}.",
            f"Wall seconds: {_num(payload['wall_seconds'])}.",
            f"Store write seconds: {_num(store['write_seconds'])}.",
            f"OverGraph filter seconds: {_num(store['filter_seconds'])}.",
            f"TextUnits unchanged: {store['text_units_unchanged']}.",
            f"Type correction survives reclassify: {store['type_correction_survives_reclassify']}.",
            f"Rejected tag stays rejected: {store['rejected_tag_stays_rejected']}.",
            f"Tenant isolation: {store['tenant_isolation']}.",
            "",
            payload["decision"]["reason"],
            "",
            "## Recommendation",
            "",
            _recommendation(payload),
            "",
            "## What this is not",
            "",
            "- Not a change to Tabular `answer_cell`.",
            "- Not Dense or Hybrid retrieval.",
            "- Not a new coverage controller.",
            "- Not production ingest.",
            "- Not a calibrated legal confidence.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _recommendation(payload: dict[str, object]) -> str:
    store = payload["store"]
    return (
        "Store classification, tags, user corrections, and tenant-scoped "
        "filters in OverGraph. Keep Jev confidence raw and diagnostic. "
        f"Type lock works: {store['type_correction_survives_reclassify']}. "
        "Do not start Socialism production ingest from this experiment. "
        "Tabular Review remains the path for legal answers."
    )


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _pct(value: object) -> str:
    if value is None:
        return "—"
    return f"{float(value):.1%}"


def _num(value: object) -> str:
    return f"{float(value):.3f}"
