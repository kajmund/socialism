"""Phase 1 measurement suite: scaling, cache modes, graph-only, and gold quality."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import replace
from pathlib import Path

from overgraph_ingest.benchmarks.corpus import generate_corpus
from overgraph_ingest.benchmarks.report import report_payload
from overgraph_ingest.config import IngestConfig
from overgraph_ingest.metrics import environment_metadata, summarize_repeats
from overgraph_ingest.pipeline import prepare_documents, run_ingest, write_prepared
from overgraph_ingest.quality.evaluate import evaluate_gold_dir, summarize_scores
from overgraph_ingest.quality.gold import generate_gold_set

BATCH_SIZES = (100, 500, 1000, 5000)
SCALE_LIMITS = (("A", 10), ("B", 50), ("C", 200))


def run_suite(config: IngestConfig) -> dict[str, object]:
    if config.input_dir is None:
        raise ValueError("--input is required for --suite")
    root = config.output_path.parent if config.output_path else config.db_path.parent
    corpus_dir = config.input_dir
    size = config.generate_corpus or config.limit or 200
    generate_corpus(corpus_dir, size)
    gold_dir = config.gold_dir or (root / "gold" / "synthetic")
    generate_gold_set(gold_dir)
    quality = {
        "synthetic": summarize_scores(evaluate_gold_dir(gold_dir, config, origin="synthetic")),
    }
    if config.real_gold_dir is not None:
        quality["real"] = summarize_scores(
            evaluate_gold_dir(config.real_gold_dir, config, origin="real")
        )
        quality["note"] = "Real contracts are scored only when files exist in --real-gold."
    else:
        quality["real"] = {
            "case_count": 0,
            "note": "No --real-gold directory. Synthetic fixtures are not a substitute for real PDFs.",
        }

    shared_cache = root / "suite-cache"
    if shared_cache.exists():
        shutil.rmtree(shared_cache)
    prepare_config = replace(config, cache_dir=shared_cache, limit=size)
    prepared, prepare_seconds = _timed(lambda: prepare_documents(prepare_config))
    construction = sum(item.timings.get("build", 0.0) for item in prepared)
    extraction = sum(item.timings.get("extract", 0.0) for item in prepared)
    segmentation = sum(item.timings.get("segment", 0.0) for item in prepared)

    experiments: dict[str, object] = {}
    last_c_paths: tuple[Path, Path] | None = None
    for label, default_limit in SCALE_LIMITS:
        limit = min(default_limit, size)
        if limit < 1:
            continue
        runs = []
        for repeat in range(config.repeats):
            db_path = root / "suite-db" / f"{label}-{repeat}"
            cache_path = root / "suite-cache-cold" / f"{label}-{repeat}"
            _reset_dir(db_path)
            _reset_dir(cache_path)
            run_config = replace(
                config,
                db_path=db_path,
                cache_dir=cache_path,
                limit=limit,
            )
            payload = report_payload(run_config, run_ingest(run_config))
            runs.append(payload)
            if label == "C":
                last_c_paths = (db_path, cache_path)
        experiments[label] = _repeat_summary(runs, extra={"limit": limit, "cache": "cold", "db": "new"})

    d_runs = []
    for repeat in range(config.repeats):
        db_path = root / "suite-db" / f"D-{repeat}"
        _reset_dir(db_path)
        run_config = replace(config, db_path=db_path, cache_dir=shared_cache, limit=size)
        d_runs.append(report_payload(run_config, run_ingest(run_config)))
    experiments["D"] = _repeat_summary(
        d_runs, extra={"limit": size, "cache": "extract", "db": "new"}
    )

    e_runs = []
    if last_c_paths is not None:
        db_path, cache_path = last_c_paths
        for _repeat in range(config.repeats):
            run_config = replace(config, db_path=db_path, cache_dir=cache_path, limit=size)
            e_runs.append(report_payload(run_config, run_ingest(run_config)))
        experiments["E"] = _repeat_summary(
            e_runs, extra={"limit": size, "cache": "all", "db": "reused_from_C"}
        )

    f_runs = []
    for repeat in range(config.repeats):
        db_path = root / "suite-db" / f"F-{repeat}"
        _reset_dir(db_path)
        run_config = replace(config, db_path=db_path, cache_dir=shared_cache, limit=size)
        f_runs.append(report_payload(run_config, write_prepared(run_config, prepared)))
    experiments["F"] = _repeat_summary(
        f_runs,
        extra={
            "limit": size,
            "cache": "prepared_graph",
            "db": "new",
            "preparation_seconds": prepare_seconds,
            "graph_construction_seconds": construction,
        },
    )

    batch_results = {}
    for batch_size in BATCH_SIZES:
        runs = []
        for repeat in range(config.repeats):
            db_path = root / "suite-db" / f"batch-{batch_size}-{repeat}"
            _reset_dir(db_path)
            run_config = replace(
                config,
                db_path=db_path,
                cache_dir=shared_cache,
                write_batch_size=batch_size,
                limit=size,
            )
            runs.append(report_payload(run_config, write_prepared(run_config, prepared)))
        batch_results[str(batch_size)] = _repeat_summary(
            runs, extra={"write_batch_size": batch_size}
        )

    payload = {
        "environment": environment_metadata(),
        "corpus": {
            "path": str(corpus_dir),
            "documents": size,
            "kind": "synthetic",
        },
        "quality": quality,
        "preparation": {
            "seconds": prepare_seconds,
            "extraction_seconds": extraction,
            "segmentation_seconds": segmentation,
            "graph_construction_seconds": construction,
        },
        "experiments": experiments,
        "batch_sizes": batch_results,
        "scaling": _scaling_view(experiments),
    }
    if config.output_path is not None:
        config.output_path.parent.mkdir(parents=True, exist_ok=True)
        config.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return payload


def _repeat_summary(runs: list[dict[str, object]], *, extra: dict[str, object]) -> dict[str, object]:
    totals = [float(run["total_seconds"]) for run in runs]
    extracts = [float(run["stage_seconds"]["extract"]) for run in runs]
    segments = [float(run["stage_seconds"]["segment"]) for run in runs]
    builds = [float(run["stage_seconds"]["build"]) for run in runs]
    writes = [float(run["stage_seconds"]["write"]) for run in runs]
    verifies = [float(run["stage_seconds"]["verify"]) for run in runs]
    end_ingests = [float((run.get("finalize_seconds") or {}).get("end_ingest") or 0.0) for run in runs]
    syncs = [float((run.get("finalize_seconds") or {}).get("sync") or 0.0) for run in runs]
    persist = [write + end + sync for write, end, sync in zip(writes, end_ingests, syncs, strict=True)]
    headline = runs[-1]["headline"] if runs else {}
    return {
        **extra,
        "repeats": len(runs),
        "total_seconds": summarize_repeats(totals),
        "extraction_seconds": summarize_repeats(extracts),
        "segmentation_seconds": summarize_repeats(segments),
        "graph_construction_seconds": summarize_repeats(builds),
        "overgraph_batch_write_seconds": summarize_repeats(writes),
        "end_ingest_seconds": summarize_repeats(end_ingests),
        "sync_seconds": summarize_repeats(syncs),
        "overgraph_persist_seconds": summarize_repeats(persist),
        "verification_seconds": summarize_repeats(verifies),
        "last_headline": headline,
        "runs": runs,
    }


def _scaling_view(experiments: dict[str, object]) -> dict[str, object]:
    rows = {}
    for label in ("A", "B", "C"):
        block = experiments.get(label)
        if not isinstance(block, dict):
            continue
        totals = block["total_seconds"]
        rows[label] = {
            "documents": block.get("limit"),
            "median_seconds": totals.get("median"),
            "p95_seconds": totals.get("p95"),
        }
    return rows


def _reset_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _timed(work):
    started = time.perf_counter()
    result = work()
    return result, time.perf_counter() - started
