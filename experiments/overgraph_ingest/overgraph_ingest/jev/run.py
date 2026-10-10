"""Run Jev classification on a frozen hybrid candidate list."""

from __future__ import annotations

from dataclasses import dataclass

from overgraph_ingest.config import JevRunConfig
from overgraph_ingest.graph.writer import GraphWriter, open_database, resolve_dimension
from overgraph_ingest.jev.baseline import load_baseline_judgments
from overgraph_ingest.jev.candidates import hydrate_candidates, load_frozen_hits
from overgraph_ingest.jev.classify import (
    CLASSIFY_CANDIDATES_PER_CALL,
    ContextKind,
    Judgment,
    classify_candidates,
)
from overgraph_ingest.jev.client import HttpJevClient, JevClient
from overgraph_ingest.jev.evaluate import (
    analyze_coverage_groups,
    compare_judgments,
    evaluate_judgments,
)
from overgraph_ingest.jev.questions import CLASSIFY_QUESTION
from overgraph_ingest.retrieval.gold import load_retrieval_gold

@dataclass(frozen=True)
class SweepCell:
    variant: str
    context: ContextKind
    batch_size: int
    concurrency: int


EXPERIMENT_CELLS: dict[str, tuple[SweepCell, ...]] = {
    "A": (SweepCell("A", "none", 1, 1),),
    "B": (
        SweepCell("B1", "parent", 1, 1),
        SweepCell("B2", "adjacent", 1, 1),
    ),
    "B1": (SweepCell("B1", "parent", 1, 1),),
    "B2": (SweepCell("B2", "adjacent", 1, 1),),
    "C": tuple(
        SweepCell(f"C@{concurrency}", "none", 1, concurrency) for concurrency in (1, 4, 8, 16)
    ),
    "E": tuple(SweepCell(f"E@b{batch}", "none", batch, 8) for batch in (1, 4, 8, 16)),
}


@dataclass
class JevReport:
    payload: dict[str, object]


def run_jev_classification(config: JevRunConfig, client: JevClient | None = None) -> JevReport:
    if config.gold_path is None or config.candidates_path is None:
        raise ValueError("--retrieve-gold and --candidates are required for --classify-jev")
    gold = load_retrieval_gold(config.gold_path)
    hits = load_frozen_hits(
        config.candidates_path,
        strategy=config.candidate_strategy,
        k=config.candidate_k,
    )
    dimension = resolve_dimension(config.db_path, config.dense_dimension)
    db = open_database(config.db_path, dimension)
    try:
        writer = GraphWriter(db, batch_size=500)
        candidates = hydrate_candidates(writer, hits, gold)
    finally:
        db.close()
    jev = client or HttpJevClient(api_key=config.typesafe_api_key or "", base_url=config.typesafe_base_url)
    question = gold.classify_question or CLASSIFY_QUESTION
    cells = _cells(config)
    baseline = None
    if config.baseline_path is not None and config.baseline_path.exists():
        baseline = load_baseline_judgments(config.baseline_path)
    reference: list[dict[str, object]] | None = None
    reference_wall: float | None = None
    runs = []
    for cell in cells:
        judgments, wall_seconds = classify_candidates(
            jev,
            candidates,
            model=config.jev_model,
            timeout_seconds=config.timeout_seconds,
            batch_size=cell.batch_size,
            context=cell.context,
            concurrency=cell.concurrency,
            allow_prompt_batch=config.experiment == "E",
            question=question,
        )
        metrics = evaluate_judgments(judgments)
        if gold.coverage_groups:
            metrics["coverage_groups"] = analyze_coverage_groups(gold, candidates, judgments)
        metrics["wall_seconds"] = wall_seconds
        metrics["batch_size"] = cell.batch_size
        metrics["concurrency"] = cell.concurrency
        metrics["context"] = cell.context
        metrics["variant"] = cell.variant
        metrics["with_context"] = cell.context != "none"
        if baseline is not None:
            versus_baseline = compare_judgments(baseline, judgments)
            metrics["versus_baseline"] = versus_baseline
            metrics["versus_a"] = versus_baseline
        if reference is not None and reference_wall is not None:
            versus_reference = compare_judgments(reference, judgments)
            metrics["versus_reference"] = versus_reference
            metrics["versus_c1"] = versus_reference
            metrics["speedup_vs_reference"] = reference_wall / wall_seconds if wall_seconds else None
            metrics["speedup_vs_c1"] = metrics["speedup_vs_reference"]
        if reference is None:
            reference = _rows(judgments)
            reference_wall = wall_seconds
        runs.append(metrics)
    return JevReport(
        payload={
            "experiment": config.experiment,
            "gold_id": gold.id,
            "question": gold.query,
            "classify_question": question,
            "kind": gold.kind,
            "candidate_strategy": config.candidate_strategy,
            "candidate_k": config.candidate_k,
            "candidates": len(candidates),
            "jev_model": config.jev_model,
            "operation": "classify",
            "baseline": str(config.baseline_path) if config.baseline_path else None,
            "runs": runs,
        }
    )


def _cells(config: JevRunConfig) -> tuple[SweepCell, ...]:
    if config.experiment == "A":
        return (
            SweepCell("A", "none", CLASSIFY_CANDIDATES_PER_CALL, config.concurrency),
        )
    return EXPERIMENT_CELLS[config.experiment]


def _rows(judgments: list[Judgment]) -> list[dict[str, object]]:
    return [
        {
            "key": item.key,
            "predicted": item.predicted,
            "expected": item.expected,
            "confidence": item.confidence,
            "gold_label": item.gold_label,
            "relative_path": item.relative_path,
        }
        for item in judgments
    ]
