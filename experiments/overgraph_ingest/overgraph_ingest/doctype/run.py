"""Compare structure-only A with Jev B and wider-context C."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from overgraph_ingest.doctype.classify import Classification, classify_jev
from overgraph_ingest.doctype.evaluate import decide, pair_variants, summarize
from overgraph_ingest.doctype.gold import GOLD_ID, gold_by_path
from overgraph_ingest.doctype.gold_eval import require_doctype_gold
from overgraph_ingest.doctype.store import prove_store_and_filter
from overgraph_ingest.doctype.taxonomy import TAXONOMY_VERSION, TYPE_LABELS
from overgraph_ingest.doctype.variant_a import classify_a
from overgraph_ingest.doctype.view import (
    VARIANT_A,
    VARIANT_B,
    VARIANT_C,
    DocumentView,
    load_document_views,
)
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.tabular.jev_io import CountingJev
from overgraph_ingest.tabular.run import DEFAULT_DB

ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = ROOT / "eval"
DOCTYPE_RUN_ID = "phase2-doctype-run-v1"
DOCTYPE_RUN_PATH = ROOT / "baselines" / f"{DOCTYPE_RUN_ID}.json"
VARIANTS = (VARIANT_A, VARIANT_B, VARIANT_C)


def run_doctype(
    *,
    db_path: Path | None = None,
    dense_dimension: int = 3072,
    typesafe_api_key: str | None = None,
    typesafe_base_url: str = "https://api.typesafe.ai",
    jev_model: str = "jev-latest",
    jev_timeout_seconds: float = 8.0,
    views: list[DocumentView] | None = None,
    jev: JevClient | None = None,
    variants: tuple[str, ...] = VARIANTS,
    store_db_path: Path | None = None,
    gold_path: Path | None = None,
    require_gold: bool = True,
) -> dict[str, object]:
    if require_gold:
        require_doctype_gold(gold_path)
    gold = gold_by_path()
    loaded = views if views is not None else load_document_views(
        db_path=db_path or DEFAULT_DB,
        dense_dimension=dense_dimension,
    )
    missing = [view.relative_path for view in loaded if view.relative_path not in gold]
    if missing:
        raise ValueError(f"document-type gold missing paths: {missing}")
    if {VARIANT_B, VARIANT_C} & set(variants):
        if jev is None and not typesafe_api_key:
            raise ValueError("--typesafe-api-key is required for document-type B and C")
    client = None
    if {VARIANT_B, VARIANT_C} & set(variants):
        client = jev if isinstance(jev, CountingJev) else CountingJev(
            jev or HttpJevClient(api_key=typesafe_api_key or "", base_url=typesafe_base_url)
        )
    started = time.perf_counter()
    scored: dict[str, list[dict[str, object]]] = {name: [] for name in variants}
    for view in loaded:
        if VARIANT_A in variants:
            predicted = classify_a(view)
            scored[VARIANT_A].append(_scored(view, predicted, method="structure", variant=VARIANT_A))
            print(f"A {view.relative_path} {predicted}", file=sys.stderr, flush=True)
        if VARIANT_B in variants:
            scored[VARIANT_B].append(
                _from_jev(
                    classify_jev(
                        client,
                        view,
                        wide=False,
                        model=jev_model,
                        timeout_seconds=jev_timeout_seconds,
                    )
                )
            )
            print(f"B {view.relative_path} {scored[VARIANT_B][-1]['document_type']}", file=sys.stderr, flush=True)
        if VARIANT_C in variants:
            scored[VARIANT_C].append(
                _from_jev(
                    classify_jev(
                        client,
                        view,
                        wide=True,
                        model=jev_model,
                        timeout_seconds=jev_timeout_seconds,
                    )
                )
            )
            print(f"C {view.relative_path} {scored[VARIANT_C][-1]['document_type']}", file=sys.stderr, flush=True)
    summaries = {name: _variant_summary(rows) for name, rows in scored.items()}
    paired = {}
    if VARIANT_A in scored and VARIANT_B in scored:
        paired["A_B"] = pair_variants(scored[VARIANT_A], scored[VARIANT_B], left_name="A", right_name="B")
    if VARIANT_B in scored and VARIANT_C in scored:
        paired["B_C"] = pair_variants(scored[VARIANT_B], scored[VARIANT_C], left_name="B", right_name="C")
    if VARIANT_A in scored and VARIANT_C in scored:
        paired["A_C"] = pair_variants(scored[VARIANT_A], scored[VARIANT_C], left_name="A", right_name="C")
    store_rows = scored.get(VARIANT_B) or scored.get(VARIANT_A) or next(iter(scored.values()))
    store = prove_store_and_filter(
        store_rows,
        db_path=store_db_path or (db_path or DEFAULT_DB).parent / "doctype-filter-v1",
    )
    wall_seconds = time.perf_counter() - started
    return {
        "operation": "doctype_run",
        "experiment": DOCTYPE_RUN_ID,
        "gold_id": GOLD_ID,
        "taxonomy_version": TAXONOMY_VERSION,
        "does_not_change_text_units": True,
        "does_not_change_retrieval": True,
        "does_not_change_answer_cell": True,
        "does_not_change_default_hybrid": True,
        "default_remains_d": True,
        "principal_function_not_clauses": True,
        "no_production_integration": True,
        "no_graph_navigation": True,
        "one_jev_call_per_document_per_variant": True,
        "documents": [view.relative_path for view in loaded],
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
        "decision": decide(summaries, paired),
        "cost": {
            "jev_calls": sum(int(row["jev_calls"]) for rows in scored.values() for row in rows),
            "jev_calls_per_document": {
                name: _mean([float(row["jev_calls"]) for row in rows])
                for name, rows in scored.items()
            },
            "latency_ms_per_document": {
                name: _mean([float(row["latency_ms"]) for row in rows])
                for name, rows in scored.items()
            },
            "wall_seconds": wall_seconds,
            "filter_seconds": store["filter_seconds"],
            "store_write_seconds": store["write_seconds"],
        },
        "jev_calls": sum(int(row["jev_calls"]) for rows in scored.values() for row in rows),
        "wall_seconds": wall_seconds,
    }


def freeze_doctype_run(payload: dict[str, object]) -> dict[str, object]:
    return {
        "id": DOCTYPE_RUN_ID,
        "label": (
            "Document classification at ingest. Structure-only A vs Jev B vs "
            "wider-context C. Type lives on Document, not TextUnits."
        ),
        "do_not_overwrite": True,
        "does_not_change_text_units": True,
        "does_not_change_retrieval": True,
        "does_not_change_answer_cell": True,
        "default_remains_d": True,
        "no_production_integration": True,
        "gold_id": payload.get("gold_id"),
        "taxonomy_version": payload.get("taxonomy_version"),
        "documents": payload.get("documents"),
        "headline": payload.get("headline"),
        "decision": payload.get("decision"),
        "store": payload.get("store"),
        "cost": payload.get("cost"),
        "paired": {
            name: {key: value[key] for key in ("n", "changed", "fixed", "regressed")}
            for name, value in payload["paired"].items()
        },
        "paired_rows": {
            name: value["rows"] for name, value in payload["paired"].items()
        },
        "variants": {
            name: variant["summary"] for name, variant in payload["variants"].items()
        },
        "scored": payload.get("scored"),
        "jev_calls": payload.get("jev_calls"),
        "wall_seconds": payload.get("wall_seconds"),
    }


def write_doctype_run_baseline(
    payload: dict[str, object],
    path: Path | None = None,
) -> Path:
    target = path or DOCTYPE_RUN_PATH
    if target.exists():
        raise FileExistsError(f"experimental baseline already exists: {target}")
    target.write_text(
        json.dumps(freeze_doctype_run(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def write_doctype_run_table(
    payload: dict[str, object],
    directory: Path | None = None,
) -> Path:
    target = (directory or EVAL_DIR) / "doctype-run-v1.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Document classification at ingest",
        "",
        "One type per document. Principal function, not clauses.",
        "A uses title, opening, headings, and stored metadata.",
        "B is one Jev choice on the same view. C adds a fixed extra-text budget.",
        "Type is stored on Document. TextUnits stay unchanged.",
        "",
        "| Variant | Accuracy | Jev calls/doc | Latency ms/doc |",
        "|---|---:|---:|---:|",
    ]
    cost = payload["cost"]
    for name in (VARIANT_A, VARIANT_B, VARIANT_C):
        if name not in payload["variants"]:
            continue
        summary = payload["variants"][name]["summary"]
        lines.append(
            "| {name} | {correct}/{n} ({acc}) | {calls} | {latency} |".format(
                name=name,
                correct=summary["correct"],
                n=summary["n"],
                acc=_pct(summary["accuracy"]),
                calls=_num(cost["jev_calls_per_document"].get(name)),
                latency=_num(cost["latency_ms_per_document"].get(name)),
            )
        )
    lines.extend(["", "## Precision and recall", ""])
    for name in (VARIANT_A, VARIANT_B, VARIANT_C):
        if name not in payload["variants"]:
            continue
        lines.extend([f"### {name}", "", "| Type | Precision | Recall | Gold |", "|---|---:|---:|---:|"])
        for document_type, scores in payload["variants"][name]["summary"]["per_type"].items():
            lines.append(
                "| {label} | {precision} | {recall} | {gold} |".format(
                    label=TYPE_LABELS[document_type],
                    precision=_pct(scores["precision"]),
                    recall=_pct(scores["recall"]),
                    gold=scores["gold_n"],
                )
            )
        lines.append("")
    store = payload["store"]
    lines.extend(
        [
            "## Cost",
            "",
            f"Total Jev calls: {payload['jev_calls']}.",
            f"Wall seconds: {_num(payload['wall_seconds'])}.",
            f"Store write seconds: {_num(store['write_seconds'])}.",
            f"OverGraph filter seconds: {_num(store['filter_seconds'])}.",
            f"TextUnits unchanged: {store['text_units_unchanged']}.",
            "",
            payload["decision"]["reason"],
            "",
            "## What this is not",
            "",
            "- Not a change to Tabular `answer_cell`.",
            "- Not Dense or Hybrid retrieval.",
            "- Not a new coverage controller.",
            "- Not production ingest.",
        ]
    )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _scored(
    view: DocumentView,
    predicted: str,
    *,
    method: str,
    variant: str,
    model: str = "",
    score: float | None = None,
    distribution: dict[str, object] | None = None,
    latency_ms: float = 0.0,
    jev_calls: int = 0,
) -> dict[str, object]:
    gold = gold_by_path()[view.relative_path]
    return {
        "document_id": view.document_id,
        "relative_path": view.relative_path,
        "document_type": predicted,
        "predicted": predicted,
        "gold": gold,
        "correct": predicted == gold,
        "method": method,
        "variant": variant,
        "model": model,
        "score": score,
        "taxonomy_version": TAXONOMY_VERSION,
        "distribution": distribution,
        "latency_ms": latency_ms,
        "jev_calls": jev_calls,
        "classification": {
            "method": method,
            "model": model,
            "score": score,
            "taxonomy_version": TAXONOMY_VERSION,
            "variant": variant,
            "distribution": distribution,
        },
    }


def _from_jev(result: Classification) -> dict[str, object]:
    view = DocumentView(
        document_id=result.document_id,
        relative_path=result.relative_path,
        title="",
        opening="",
        headings=(),
        mime_type="",
        page_count=None,
        char_count=None,
        extra_text="",
    )
    return _scored(
        view,
        result.document_type,
        method=result.method,
        variant=result.variant,
        model=result.model,
        score=result.score,
        distribution=result.distribution,
        latency_ms=result.latency_ms,
        jev_calls=result.jev_calls,
    )


def _variant_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    summary = summarize(rows)
    summary["jev_calls"] = sum(int(row["jev_calls"]) for row in rows)
    summary["latency_ms"] = _mean([float(row["latency_ms"]) for row in rows])
    return summary


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
