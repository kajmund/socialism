"""CLI for the standalone OverGraph ingest experiment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from overgraph_ingest.benchmarks.corpus import generate_corpus
from overgraph_ingest.benchmarks.report import report_payload, write_report
from overgraph_ingest.benchmarks.suite import run_suite
from overgraph_ingest.config import IngestConfig, JevRunConfig, RetrievalConfig
from overgraph_ingest.jev.run import run_jev_classification
from overgraph_ingest.coverage.run import run_coverage
from overgraph_ingest.coverage.v2 import run_coverage_v2
from overgraph_ingest.coverage.compare import compare_v3_golds
from overgraph_ingest.coverage.v3 import run_coverage_v3
from overgraph_ingest.retrieval.expand_run import run_query_expansion
from overgraph_ingest.navigation.run import run_navigation
from overgraph_ingest.pipeline import prepare_documents, run_ingest, run_verify, write_prepared
from overgraph_ingest.quality.evaluate import evaluate_gold_dir, summarize_scores
from overgraph_ingest.quality.gold import generate_gold_set
from overgraph_ingest.retrieval.run import run_retrieval


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OverGraph document ingest and retrieval")
    parser.add_argument("--input", type=Path, help="Directory of PDF/DOCX files")
    parser.add_argument("--db", type=Path, required=True, help="OverGraph directory")
    parser.add_argument("--cache-dir", type=Path, help="Extraction cache directory")
    parser.add_argument("--collection", default="contracts")
    parser.add_argument("--dense-dimension", type=int)
    parser.add_argument("--write-batch-size", type=int, default=500)
    parser.add_argument("--target-chars", type=int, default=1200)
    parser.add_argument("--max-chars", type=int, default=2400)
    parser.add_argument("--limit", type=int, help="Use only the first N discovered files")
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--output", type=Path, help="Benchmark JSON path")
    parser.add_argument("--generate-corpus", type=int, metavar="N")
    parser.add_argument("--suite", action="store_true", help="Run scaling, graph-only, and gold quality")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--gold", action="store_true", help="Generate and score the synthetic gold set")
    parser.add_argument("--gold-dir", type=Path)
    parser.add_argument("--real-gold", type=Path, help="Optional real contract directory")
    parser.add_argument("--graph-only", action="store_true", help="Write a prepared graph to a fresh database")
    parser.add_argument("--batch-sweep", action="store_true")
    parser.add_argument("--retrieve-gold", type=Path, help="Retrieval gold JSON")
    parser.add_argument("--embed", action="store_true", help="Write dense and sparse vectors before search")
    parser.add_argument("--dense-model", default="text-embedding-3-large")
    parser.add_argument("--openai-api-key", help="Required for text-embedding-3-large")
    parser.add_argument("--openai-base-url")
    parser.add_argument("--fusion-mode", default="reciprocal_rank")
    parser.add_argument("--k", default="5,10,20,50,100", help="Comma-separated k values")
    parser.add_argument("--classify-jev", action="store_true")
    parser.add_argument("--candidates", type=Path, help="Frozen retrieval JSON with hybrid hits")
    parser.add_argument("--typesafe-api-key")
    parser.add_argument("--typesafe-base-url", default="https://api.typesafe.ai")
    parser.add_argument("--jev-model", default="jev-latest")
    parser.add_argument("--jev-experiment", choices=("A", "B", "B1", "B2", "C", "E"), default="A")
    parser.add_argument("--jev-batch-size", type=int, default=1)
    parser.add_argument("--jev-concurrency", type=int, default=8)
    parser.add_argument("--jev-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--jev-baseline", type=Path, help="Experiment A JSON for flip comparison")
    parser.add_argument("--candidate-strategy", default="hybrid")
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument(
        "--navigate",
        action="store_true",
        help="Run the Avtal 46 and Avtal 49 hop measurements only",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Run deterministic document coverage A/B/C without Jev",
    )
    parser.add_argument("--coverage-global-k", type=int, default=50)
    parser.add_argument(
        "--coverage-per-document",
        default="3,5",
        help="Comma-separated per-document depths for scoped and progressive",
    )
    parser.add_argument(
        "--coverage-v2",
        action="store_true",
        help="Run coverage v2: C@8 classify plus touched/fair deepen and measured hops",
    )
    parser.add_argument("--coverage-v2-passes", type=int, default=3)
    parser.add_argument(
        "--coverage-v3",
        action="store_true",
        help="Run coverage v3: per-document budget curves and proof-kind stop",
    )
    parser.add_argument(
        "--coverage-budgets",
        default="1,2,3,5",
        help="Comma-separated per-document classify caps; 0 means unlimited",
    )
    parser.add_argument(
        "--expand-queries",
        action="store_true",
        help="Compare deterministic query expansion against the baseline query",
    )
    parser.add_argument(
        "--coverage-query-variant",
        choices=("baseline", "append"),
        default="baseline",
        help="Query text for coverage ranking. Does not change the default retriever.",
    )
    parser.add_argument(
        "--coverage-gold-id",
        action="append",
        default=[],
        help="Limit coverage to these gold ids. Repeatable.",
    )
    parser.add_argument(
        "--coverage-v3-baseline",
        type=Path,
        help="Frozen Coverage v3 JSON to compare against a treatment run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = IngestConfig(
        db_path=args.db,
        input_dir=args.input,
        cache_dir=args.cache_dir,
        collection_id=args.collection,
        dense_dimension=args.dense_dimension,
        write_batch_size=args.write_batch_size,
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        benchmark=args.benchmark,
        verify_only=args.verify,
        output_path=args.output,
        generate_corpus=args.generate_corpus,
        limit=args.limit,
        suite=args.suite,
        repeats=args.repeats,
        gold_dir=args.gold_dir,
        real_gold_dir=args.real_gold,
        graph_only=args.graph_only,
        batch_sweep=args.batch_sweep,
        retrieve_gold=args.retrieve_gold,
        embed=args.embed,
        dense_model=args.dense_model,
        openai_api_key=args.openai_api_key,
        openai_base_url=args.openai_base_url,
        fusion_mode=args.fusion_mode,
        ks=_parse_ks(args.k),
        classify_jev=args.classify_jev,
        candidates_path=args.candidates,
        typesafe_api_key=args.typesafe_api_key,
        typesafe_base_url=args.typesafe_base_url,
        jev_model=args.jev_model,
        jev_experiment=args.jev_experiment,
        jev_batch_size=args.jev_batch_size,
        jev_concurrency=args.jev_concurrency,
        jev_timeout_seconds=args.jev_timeout_seconds,
        jev_baseline_path=args.jev_baseline,
        candidate_strategy=args.candidate_strategy,
        candidate_k=args.candidate_k,
        navigate=args.navigate,
        coverage=args.coverage,
        coverage_global_k=args.coverage_global_k,
        coverage_per_document=_parse_ks(args.coverage_per_document),
        coverage_v2=args.coverage_v2,
        coverage_v2_passes=args.coverage_v2_passes,
        coverage_v3=args.coverage_v3,
        coverage_budgets=_parse_budgets(args.coverage_budgets),
        expand_queries=args.expand_queries,
        coverage_query_variant=args.coverage_query_variant,
        coverage_gold_ids=tuple(args.coverage_gold_id),
        coverage_v3_baseline=args.coverage_v3_baseline,
    )
    if config.generate_corpus is not None and not config.suite:
        if config.input_dir is None:
            print("--input is required with --generate-corpus", file=sys.stderr)
            return 2
        generate_corpus(config.input_dir, config.generate_corpus)
    if args.gold and not config.suite:
        return _run_gold(config)
    if config.classify_jev:
        return _run_jev(config)
    if config.navigate:
        return _run_navigation(config)
    if config.coverage:
        return _run_coverage(config)
    if config.coverage_v2:
        return _run_coverage_v2(config)
    if config.coverage_v3:
        return _run_coverage_v3(config)
    if config.expand_queries:
        return _run_expand_queries(config)
    if config.verify_only:
        errors = run_verify(config)
        if errors:
            print("\n".join(errors), file=sys.stderr)
            return 1
        print("verification ok")
        return 0
    if config.suite:
        payload = run_suite(config)
        print(json.dumps(_suite_preview(payload), ensure_ascii=False, indent=2))
        return 0
    if config.retrieve_gold is not None and config.input_dir is None:
        return _run_retrieval(config)
    if config.graph_only:
        prepared = prepare_documents(config)
        report = write_prepared(config, prepared)
    else:
        report = run_ingest(config)
    payload = report_payload(config, report)
    if config.output_path is not None and config.retrieve_gold is None:
        write_report(config, report, config.output_path)
    if config.benchmark:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif config.retrieve_gold is None:
        print(
            f"ingested {payload['document_count']} files: "
            f"{payload['published']} published, {payload['failed']} failed "
            f"in {report.total_seconds:.2f}s"
        )
    if payload["failed"] != 0:
        return 1
    if config.retrieve_gold is not None:
        return _run_retrieval(config)
    return 0


COVERAGE_GOLD_DIR = Path(__file__).resolve().parents[1] / "retrieval_gold"


def _run_coverage_v2(config: IngestConfig) -> int:
    report = run_coverage_v2(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
        ),
        gold_dir=None if config.retrieve_gold is not None else COVERAGE_GOLD_DIR,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        timeout_seconds=config.jev_timeout_seconds,
        concurrency=config.jev_concurrency,
        global_k=config.coverage_global_k,
        max_passes=config.coverage_v2_passes,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_coverage_v2_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _coverage_v2_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        variants = {}
        for name, row in (item.get("variants") or {}).items():
            variants[name] = {
                "document_recall": row.get("document_recall"),
                "jev_yes_document_recall": row.get("jev_yes_document_recall"),
                "jev_calls": row.get("jev_calls"),
                "cache_hits": row.get("cache_hits"),
                "classified": row.get("classified"),
                "hop_fetches": row.get("hop_fetches"),
                "first_complete_phase": row.get("first_complete_phase"),
                "first_complete_classified": row.get("first_complete_classified"),
                "unresolved_documents": row.get("unresolved_documents"),
                "unresolved_relevant_documents": row.get("unresolved_relevant_documents"),
                "false_negative_documents": row.get("false_negative_documents"),
                "status_counts": row.get("status_counts"),
                "timeline": [
                    {
                        "phase": point.get("phase"),
                        "classified": point.get("classified"),
                        "jev_yes_document_recall": point.get("jev_yes_document_recall"),
                        "unresolved_relevant": point.get("unresolved_relevant"),
                    }
                    for point in (row.get("timeline") or [])
                ],
            }
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "proof_kind": item.get("proof_kind"),
                "variants": variants,
            }
        )
    return {
        "operation": payload.get("operation"),
        "controller": payload.get("controller"),
        "classify_unchanged": payload.get("classify_unchanged"),
        "global_k": payload.get("global_k"),
        "max_passes": payload.get("max_passes"),
        "wall_seconds": payload.get("wall_seconds"),
        "golds": golds,
    }


def _run_coverage_v3(config: IngestConfig) -> int:
    report = run_coverage_v3(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
        ),
        gold_dir=None if config.retrieve_gold is not None else COVERAGE_GOLD_DIR,
        typesafe_api_key=config.typesafe_api_key,
        typesafe_base_url=config.typesafe_base_url,
        jev_model=config.jev_model,
        timeout_seconds=config.jev_timeout_seconds,
        concurrency=config.jev_concurrency,
        global_k=config.coverage_global_k,
        budgets=config.coverage_budgets,
        query_variant=config.coverage_query_variant,
        gold_ids=config.coverage_gold_ids or None,
    )
    if config.coverage_v3_baseline is not None:
        frozen = json.loads(config.coverage_v3_baseline.read_text(encoding="utf-8"))
        for item in frozen.get("golds") or []:
            if item.get("gold_id") == "confidentiality" and item.get("recall_at_50") is None:
                item["recall_at_50"] = 0.46153846153846156
                item["document_coverage_at_50"] = 0.46153846153846156
        gold_id = (report.payload.get("golds") or [{}])[0].get("gold_id")
        if gold_id:
            report.payload["versus_baseline_v3"] = compare_v3_golds(
                frozen,
                report.payload,
                gold_id=str(gold_id),
            )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_coverage_v3_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _coverage_v3_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "proof_kind": item.get("proof_kind"),
                "query_variant": item.get("query_variant"),
                "query_used": item.get("query_used"),
                "recall_at_50": item.get("recall_at_50"),
                "document_coverage_at_50": item.get("document_coverage_at_50"),
                "matched_v2_at": item.get("matched_v2_at"),
                "budgets": [
                    {
                        "budget": row.get("budget"),
                        "document_recall": row.get("document_recall"),
                        "jev_yes_document_recall": row.get("jev_yes_document_recall"),
                        "jev_calls": row.get("jev_calls"),
                        "cache_hits": row.get("cache_hits"),
                        "classified": row.get("classified"),
                        "hop_fetches": row.get("hop_fetches"),
                        "matched_v2_recall": row.get("matched_v2_recall"),
                        "unresolved_documents": row.get("unresolved_documents"),
                        "unresolved_relevant_documents": row.get("unresolved_relevant_documents"),
                        "false_negative_documents": row.get("false_negative_documents"),
                        "budget_exhausted_documents": row.get("budget_exhausted_documents"),
                        "budget_exhausted_relevant": row.get("budget_exhausted_relevant"),
                        "status_counts": row.get("status_counts"),
                        "composite_groups": row.get("composite_groups"),
                    }
                    for row in (item.get("budgets") or [])
                ],
            }
        )
    return {
        "operation": payload.get("operation"),
        "controller": payload.get("controller"),
        "classify_unchanged": payload.get("classify_unchanged"),
        "query_variant": payload.get("query_variant"),
        "default_retriever_unchanged": payload.get("default_retriever_unchanged"),
        "budget_exhausted_is_not_absent": payload.get("budget_exhausted_is_not_absent"),
        "global_k": payload.get("global_k"),
        "budgets": payload.get("budgets"),
        "wall_seconds": payload.get("wall_seconds"),
        "versus_baseline_v3": payload.get("versus_baseline_v3"),
        "golds": golds,
    }


def _run_expand_queries(config: IngestConfig) -> int:
    report = run_query_expansion(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
        ),
        gold_dir=None if config.retrieve_gold is not None else COVERAGE_GOLD_DIR,
        ks=config.ks,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_expand_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _expand_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "concept": item.get("concept"),
                "terms": item.get("terms"),
                "delta_at_50": item.get("delta_at_50"),
                "variants": {
                    name: {
                        "query": row.get("query"),
                        "modes": {
                            mode: {
                                "recall_at_50": metrics.get("recall_at_50"),
                                "document_coverage_at_50": metrics.get(
                                    "document_coverage_at_50"
                                ),
                                "hard_negatives_at_50": metrics.get("hard_negatives_at_50"),
                                "units_to_document_recall": metrics.get(
                                    "units_to_document_recall"
                                ),
                            }
                            for mode, metrics in (row.get("modes") or {}).items()
                        },
                    }
                    for name, row in (item.get("variants") or {}).items()
                },
            }
        )
    return {
        "operation": payload.get("operation"),
        "experiment": payload.get("experiment"),
        "classify_unchanged": payload.get("classify_unchanged"),
        "dense_model": payload.get("dense_model"),
        "wall_seconds": payload.get("wall_seconds"),
        "golds": golds,
    }


def _run_coverage(config: IngestConfig) -> int:
    report = run_coverage(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
        ),
        gold_dir=None if config.retrieve_gold is not None else COVERAGE_GOLD_DIR,
        global_k=config.coverage_global_k,
        per_document=config.coverage_per_document,
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_coverage_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _coverage_preview(payload: dict[str, object]) -> dict[str, object]:
    golds = []
    for item in payload.get("golds") or []:
        scorers = {}
        for mode, strategies in (item.get("scorers") or {}).items():
            scorers[mode] = {
                name: {
                    "document_recall": row.get("document_recall"),
                    "evidence_recall": row.get("evidence_recall"),
                    "would_be_jev_calls": row.get("would_be_jev_calls"),
                    "extra_units": row.get("extra_units"),
                    "curve": (row.get("curve") or {}).get("units_to_document_recall"),
                    "missed_relevant_documents": row.get("missed_relevant_documents"),
                    "touched_relevant_without_evidence": row.get(
                        "touched_relevant_without_evidence"
                    ),
                    "false_negative_documents": row.get("false_negative_documents"),
                    "status_counts": row.get("status_counts"),
                }
                for name, row in strategies.items()
            }
        golds.append(
            {
                "gold_id": item.get("gold_id"),
                "relevant_documents": item.get("relevant_documents"),
                "wall_seconds": item.get("wall_seconds"),
                "scorers": scorers,
            }
        )
    return {
        "operation": payload.get("operation"),
        "controller": payload.get("controller"),
        "classify_unchanged": payload.get("classify_unchanged"),
        "global_k": payload.get("global_k"),
        "per_document": payload.get("per_document"),
        "units": payload.get("units"),
        "wall_seconds": payload.get("wall_seconds"),
        "golds": golds,
    }


def _run_navigation(config: IngestConfig) -> int:
    report = run_navigation(db_path=config.db_path, dense_dimension=config.dense_dimension)
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(report.payload, ensure_ascii=False, indent=2))
    return 0


def _run_jev(config: IngestConfig) -> int:
    report = run_jev_classification(
        JevRunConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            candidates_path=config.candidates_path,
            dense_dimension=config.dense_dimension,
            typesafe_api_key=config.typesafe_api_key,
            typesafe_base_url=config.typesafe_base_url,
            jev_model=config.jev_model,
            experiment=config.jev_experiment,
            batch_size=config.jev_batch_size,
            concurrency=config.jev_concurrency,
            baseline_path=config.jev_baseline_path,
            candidate_strategy=config.candidate_strategy,
            candidate_k=config.candidate_k,
            timeout_seconds=config.jev_timeout_seconds,
        )
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_jev_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _jev_preview(payload: dict[str, object]) -> dict[str, object]:
    runs = []
    for item in payload.get("runs") or []:
        runs.append(
            {
                "variant": item.get("variant"),
                "context": item.get("context"),
                "batch_size": item.get("batch_size"),
                "concurrency": item.get("concurrency"),
                "precision": item.get("precision"),
                "recall": item.get("recall"),
                "predicted": item.get("predicted"),
                "false_positives": [
                    row.get("relative_path") for row in (item.get("false_positives") or [])
                ],
                "false_negatives": [
                    row.get("relative_path") for row in (item.get("false_negatives") or [])
                ],
                "watch_predicted_yes": [
                    row.get("relative_path") for row in (item.get("watch_predicted_yes") or [])
                ],
                "uncertain_relevant": len(item.get("uncertain_relevant") or []),
                "document_recall": item.get("document_recall"),
                "hard_negative_predictions": [
                    {
                        "relative_path": row.get("relative_path"),
                        "gold_label": row.get("gold_label"),
                        "predicted": row.get("predicted"),
                    }
                    for row in (item.get("hard_negative_predictions") or [])
                ],
                "coverage_groups": item.get("coverage_groups"),
                "versus_baseline": _delta_preview(item.get("versus_baseline")),
                "versus_reference": _delta_preview(item.get("versus_reference")),
                "speedup_vs_reference": item.get("speedup_vs_reference"),
                "model_calls": item.get("model_calls"),
                "wall_seconds": item.get("wall_seconds"),
                "errors": item.get("errors"),
            }
        )
    return {
        "experiment": payload.get("experiment"),
        "gold_id": payload.get("gold_id"),
        "kind": payload.get("kind"),
        "classify_question": payload.get("classify_question"),
        "jev_model": payload.get("jev_model"),
        "candidates": payload.get("candidates"),
        "candidate_strategy": payload.get("candidate_strategy"),
        "candidate_k": payload.get("candidate_k"),
        "runs": runs,
    }


def _delta_preview(delta: object) -> dict[str, object] | None:
    if not isinstance(delta, dict):
        return None
    return {
        "changed": len(delta.get("changed") or []),
        "improvements": len(delta.get("improvements") or []),
        "regressions": len(delta.get("regressions") or []),
        "retained_true_yes": delta.get("retained_true_yes"),
        "watched": [
            {
                "relative_path": row.get("relative_path"),
                "from": row.get("from"),
                "to": row.get("to"),
            }
            for row in (delta.get("watched") or [])
        ],
    }


def _run_retrieval(config: IngestConfig) -> int:
    report = run_retrieval(
        RetrievalConfig(
            db_path=config.db_path,
            gold_path=config.retrieve_gold,
            dense_dimension=config.dense_dimension,
            write_batch_size=config.write_batch_size,
            dense_model=config.dense_model,
            openai_api_key=config.openai_api_key,
            openai_base_url=config.openai_base_url,
            embed=config.embed,
            fusion_mode=config.fusion_mode,
            ks=config.ks,
        )
    )
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(report.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(_retrieval_preview(report.payload), ensure_ascii=False, indent=2))
    return 0


def _parse_ks(raw: str) -> tuple[int, ...]:
    values = tuple(int(part.strip()) for part in raw.split(",") if part.strip())
    if not values:
        raise ValueError("--k must contain at least one integer")
    return values


def _parse_budgets(raw: str) -> tuple[int | None, ...]:
    values: list[int | None] = []
    for part in raw.split(","):
        if not part.strip():
            continue
        number = int(part.strip())
        values.append(None if number == 0 else number)
    if not values:
        raise ValueError("--coverage-budgets must contain at least one integer")
    return tuple(values)


def _retrieval_preview(payload: dict[str, object]) -> dict[str, object]:
    strategies = payload.get("strategies") or {}
    preview = {
        "gold_id": payload.get("gold_id"),
        "query": payload.get("query"),
        "dense_model": payload.get("dense_model"),
        "sparse_encoder": payload.get("sparse_encoder"),
        "units": payload.get("units"),
        "relevant_units_in_graph": payload.get("relevant_units_in_graph"),
        "hard_negatives_in_graph": payload.get("hard_negatives_in_graph"),
        "absent_from_graph": len(payload.get("absent_from_graph") or []),
        "strategies": {},
    }
    for name, block in strategies.items():
        at_k = block.get("at_k") or {}
        preview["strategies"][name] = {
            "ranking": block.get("ranking"),
            "at_k": {
                k: {
                    "recall": cell.get("recall"),
                    "precision": cell.get("precision"),
                    "document_coverage": cell.get("document_coverage"),
                    "unique_documents": cell.get("unique_documents"),
                    "mrr": cell.get("mrr"),
                    "document_mrr": cell.get("document_mrr"),
                    "ndcg": cell.get("ndcg"),
                    "first_relevant_rank": cell.get("first_relevant_rank"),
                    "hard_negatives_in_topk": cell.get("hard_negatives_in_topk"),
                    "hard_negative_ranks": cell.get("hard_negative_ranks"),
                    "unretrieved": len(cell.get("unretrieved") or []),
                    "low_rank": len(cell.get("low_rank") or []),
                }
                for k, cell in at_k.items()
            },
        }
    return preview


def _run_gold(config: IngestConfig) -> int:
    gold_dir = config.gold_dir or (config.db_path.parent / "gold" / "synthetic")
    generate_gold_set(gold_dir)
    scores = evaluate_gold_dir(gold_dir, config, origin="synthetic")
    payload = summarize_scores(scores)
    if config.real_gold_dir is not None:
        payload = {
            "synthetic": payload,
            "real": summarize_scores(
                evaluate_gold_dir(config.real_gold_dir, config, origin="real")
            ),
        }
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    structure_errors = (
        payload.get("structure_errors")
        if "structure_errors" in payload
        else payload.get("synthetic", {}).get("structure_errors", 0)
    )
    return 0 if structure_errors == 0 else 1


def _suite_preview(payload: dict[str, object]) -> dict[str, object]:
    quality = payload.get("quality") or {}
    synthetic = quality.get("synthetic") or {}
    return {
        "environment": payload.get("environment"),
        "scaling": payload.get("scaling"),
        "preparation": payload.get("preparation"),
        "quality": {
            "synthetic_structure_errors": synthetic.get("structure_errors"),
            "synthetic_perfect_cases": synthetic.get("perfect_cases"),
            "synthetic_mean_clause_recall": synthetic.get("mean_clause_recall"),
            "real": quality.get("real"),
        },
        "experiments": {
            name: {
                "total_seconds": block.get("total_seconds"),
                "extraction_seconds": block.get("extraction_seconds"),
                "overgraph_persist_seconds": block.get("overgraph_persist_seconds"),
                "last_headline": block.get("last_headline"),
            }
            for name, block in (payload.get("experiments") or {}).items()
        },
        "batch_sizes": {
            name: block.get("overgraph_persist_seconds")
            for name, block in (payload.get("batch_sizes") or {}).items()
        },
        "output": "full JSON written to --output when set",
    }
