"""Baseline measurement for the current research loop. Fake mode only.

This harness runs `execute_attempt_research` with deterministic local inputs:
file SQLite, fake research sources, fake embeddings and the programmatic (no LLM)
assessor/completeness review. It records wall time, need counts, per-need
durations, stop reason, provider calls, LLM usage (must stay zero) and OverGraph
knowledge reuse. The second attempt of the same question measures the reuse path.

Every pair uses a fresh question so the cold attempt cannot reuse an earlier
answer and the warm attempt reuses only the answer produced by its own cold
attempt. This is orchestration measurement, not research quality measurement.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund
from app.llm import LLMCallStats, bind_usage_recorder, reset_usage_recorder
from app.services.execution import (
    create_attempt,
    create_run,
    get_attempt,
    list_evidence_items,
    list_need_executions,
    list_runtime_needs,
)
from app.services.overgraph.catalogs import (
    OverGraphRuntime,
    open_catalog,
    set_runtime,
)
from app.services.research.execution import AttemptResearchResult, execute_attempt_research
from app.services.research.result_execution import REUSE_KEY
from app.services.research.models import ResearchContext, ResearchNeed, research_evidence
from app.services.research.planner import (
    FakeResearchPlanner,
    ResearchNeedDraft,
    ResearchObjective,
)
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.registry import ResearchSourceRegistry
from app.services.research.router import ResearchRouter

EMBEDDING_DIM = 32
CUSTOMER_ID = 1


def _vector() -> list[float]:
    return [1.0] + [0.0] * (EMBEDDING_DIM - 1)


class FakeEmbeddings:
    """Deterministic local embedding provider; never calls a network."""

    model = "benchmark-fake-embedding"
    dimension = EMBEDDING_DIM
    provider_id = "benchmark-fake"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_vector() for _ in texts]


class RecordingSource:
    """Deterministic research source. Counts calls so reuse is observable."""

    provider_id = "benchmark-fake"

    def __init__(self, source_type: str) -> None:
        self.source_type = source_type
        self.calls = 0

    async def research(self, need: ResearchNeed, _context: ResearchContext):
        self.calls += 1
        return [
            research_evidence(
                research_need_id=need.id,
                source_type=self.source_type,  # type: ignore[arg-type]
                status="found",
                title="Fake underlag",
                excerpt="Skattesatsen är 32 procent enligt fake-underlaget.",
                locator="s1",
                source_id=f"source-{need.id}",
                provider=self.provider_id,
                score=0.9,
                retrieved_at=datetime.now(UTC),
                metadata={
                    "document_id": f"doc-{need.id}",
                    "version": "1",
                    "content_hash": f"hash-{need.id}",
                },
            )
        ]


@dataclass
class RunMetrics:
    label: str
    question: str
    wall_ms: float
    status: str
    stop_reason: str | None
    needs: int
    need_durations_ms: list[float] = field(default_factory=list)
    found: int = 0
    not_found: int = 0
    errors: int = 0
    reused_answer_id: str | None = None
    reuse_match: str | None = None
    providers: dict[str, int] = field(default_factory=dict)
    provider_calls: int = 0
    llm_calls: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "question": self.question,
            "wall_ms": round(self.wall_ms, 3),
            "status": self.status,
            "stop_reason": self.stop_reason,
            "needs": self.needs,
            "need_durations_ms": [round(value, 3) for value in self.need_durations_ms],
            "evidence": {
                "found": self.found,
                "not_found": self.not_found,
                "error": self.errors,
                "providers": self.providers,
            },
            "reused_answer_id": self.reused_answer_id,
            "reuse_match": self.reuse_match,
            "provider_calls": self.provider_calls,
            "llm_calls": self.llm_calls,
        }


@dataclass(frozen=True)
class AttemptRun:
    attempt_id: str
    result: AttemptResearchResult
    wall_ms: float
    provider_calls: int
    llm_calls: int


@dataclass(frozen=True)
class BenchHarness:
    engine: Any
    factory: async_sessionmaker[AsyncSession]
    router: ResearchRouter
    sources: tuple[RecordingSource, ...]
    llm_calls: list[LLMCallStats]

    def provider_calls(self) -> int:
        return sum(source.calls for source in self.sources)


def _install_fake_embeddings() -> Any:
    """Point research embedding lookups at the deterministic local provider."""
    import app.services.research.composition as composition

    original = composition.research_embeddings
    composition.research_embeddings = lambda: FakeEmbeddings()
    return original


async def _open_database(path: Path) -> tuple[Any, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.execute(text("PRAGMA journal_mode=WAL"))
    async with factory.begin() as session:
        session.add(Kund(id=CUSTOMER_ID, name="Bench", slug="bench", available_modules=["dd"]))
    return engine, factory


def _open_runtime(root: Path) -> OverGraphRuntime:
    runtime = OverGraphRuntime(
        open_catalog(root / "knowledge", kind="knowledge", dimension=EMBEDDING_DIM),
        open_catalog(root / "memory", kind="memory", dimension=EMBEDDING_DIM),
    )
    set_runtime(runtime)
    return runtime


@dataclass
class OwnerBinding:
    """In-process single writer for the runtime this benchmark just opened."""

    owner: Any
    previous_client: Any


async def open_owner_for_runtime(runtime: OverGraphRuntime) -> OwnerBinding:
    """Research now publishes answers through the owner; benchmarks must too."""
    from app.services.overgraph.owner import OwnerClient, OvergraphOwner
    from app.services.overgraph.owner_runtime import get_owner_runtime

    root = Path(tempfile.mkdtemp(prefix="bench-owner-"))
    owner = OvergraphOwner(
        root / "lock",
        dimension=runtime.knowledge.dimension,
        socket_path=root / "owner.sock",
        catalog=runtime.knowledge,
    )
    await owner.start()
    state = get_owner_runtime()
    binding = OwnerBinding(owner=owner, previous_client=state.client)
    state.client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    return binding


async def close_owner_binding(binding: OwnerBinding) -> None:
    from app.services.overgraph.owner_runtime import get_owner_runtime

    get_owner_runtime().client = binding.previous_client
    await binding.owner.close()


async def _new_attempt(factory: async_sessionmaker[AsyncSession], question: str) -> str:
    async with factory.begin() as session:
        run = await create_run(
            session,
            customer_id=CUSTOMER_ID,
            module="dd",
            title="Research baseline",
            context={"case_id": "bench-case"},
        )
        attempt = await create_attempt(
            session,
            run_id=run.id,
            attempt_type="generic_panel",
            configuration_snapshot={"mode": "benchmark-fake"},
            input_snapshot={"question": question},
        )
        return attempt.id


def _provider_counts(items: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.provider or "none"] = counts.get(item.provider or "none", 0) + 1
    return counts


async def _collect(
    factory: async_sessionmaker[AsyncSession],
    *,
    label: str,
    question: str,
    run: AttemptRun,
) -> RunMetrics:
    async with factory() as session:
        attempt = await get_attempt(session, run.attempt_id)
        needs = await list_runtime_needs(session, run.attempt_id)
        executions = await list_need_executions(session, run.attempt_id)
        items = (
            await list_evidence_items(session, run.result.evidence_set_id)
            if run.result.evidence_set_id is not None
            else []
        )
    durations = [
        (row.completed_at - row.started_at).total_seconds() * 1000
        for row in executions
        if row.started_at is not None and row.completed_at is not None
    ]
    reused = attempt.input_snapshot.get(REUSE_KEY) or {}
    return RunMetrics(
        label=label,
        question=question,
        wall_ms=run.wall_ms,
        status=run.result.status,
        stop_reason=attempt.research_stop_reason,
        needs=len(needs),
        need_durations_ms=durations,
        found=run.result.found_count,
        not_found=run.result.not_found_count,
        errors=run.result.error_count,
        reused_answer_id=reused.get("answer_fact_id"),
        reuse_match=reused.get("match"),
        providers=_provider_counts(items),
        provider_calls=run.provider_calls,
        llm_calls=run.llm_calls,
    )


async def _run_attempt(
    harness: BenchHarness,
    *,
    question: str,
    label: str,
) -> RunMetrics:
    attempt_id = await _new_attempt(harness.factory, question)
    provider_before = harness.provider_calls()
    llm_before = len(harness.llm_calls)
    started = time.perf_counter()
    planner = FakeResearchPlanner([
        ResearchNeedDraft(
            question=f"{question} – underfråga",
            why_needed="benchmark child need",
            source_types=["case_knowledge"],
        )
    ])
    async with harness.factory() as session:
        result = await execute_attempt_research(
            session,
            attempt_id=attempt_id,
            research_objective=ResearchObjective(question),
            research_planner=planner,
            router=harness.router,
            question_graph=SqlQuestionEvidenceGraph(),
            session_factory=harness.factory,
        )
    wall_ms = (time.perf_counter() - started) * 1000
    return await _collect(
        harness.factory,
        label=label,
        question=question,
        run=AttemptRun(
            attempt_id=attempt_id,
            result=result,
            wall_ms=wall_ms,
            provider_calls=harness.provider_calls() - provider_before,
            llm_calls=len(harness.llm_calls) - llm_before,
        ),
    )


def _summary(cold: list[RunMetrics], warm: list[RunMetrics]) -> dict[str, Any]:
    def _stats(rows: list[RunMetrics]) -> dict[str, Any]:
        walls = sorted(row.wall_ms for row in rows)
        return {
            "median_wall_ms": round(statistics.median(walls), 3),
            "p95_wall_ms": round(walls[min(len(walls) - 1, int(len(walls) * 0.95))], 3),
            "runs": len(rows),
            "median_needs": statistics.median([row.needs for row in rows]),
            "reused_answers": sum(1 for row in rows if row.reused_answer_id),
            "provider_calls": sum(row.provider_calls for row in rows),
            "llm_calls": sum(row.llm_calls for row in rows),
        }

    cold_stats = _stats(cold)
    warm_stats = _stats(warm)
    return {
        "mode": "fake-orchestration-measurement",
        "note": (
            "Fake sources and programs only. No LLM or network. Numbers measure "
            "orchestration and knowledge reuse, not research quality."
        ),
        "cold": cold_stats,
        "warm": warm_stats,
        "cold_to_warm_median_speedup": (
            round(cold_stats["median_wall_ms"] / warm_stats["median_wall_ms"], 3)
            if warm_stats["median_wall_ms"]
            else None
        ),
        "reused_answers_cold": cold_stats["reused_answers"],
        "reused_answers_warm": warm_stats["reused_answers"],
        "llm_calls_total": cold_stats["llm_calls"] + warm_stats["llm_calls"],
    }


def _print_report(pairs: list[tuple[RunMetrics, RunMetrics]], summary: dict[str, Any]) -> None:
    for index, (cold, warm) in enumerate(pairs, start=1):
        print(
            f"pair={index} cold_ms={cold.wall_ms:.2f} warm_ms={warm.wall_ms:.2f} "
            f"needs={cold.needs}/{warm.needs} "
            f"reused_answer={bool(cold.reused_answer_id)}/{bool(warm.reused_answer_id)} "
            f"providers={cold.providers}/{warm.providers} "
            f"provider_calls={cold.provider_calls}/{warm.provider_calls} "
            f"stop_reason={cold.stop_reason!r}/{warm.stop_reason!r}"
        )
    print(
        "cold median_ms={median_wall_ms} p95_ms={p95_wall_ms} provider_calls={provider_calls}"
        .format(**summary["cold"])
    )
    print(
        "warm median_ms={median_wall_ms} p95_ms={p95_wall_ms} provider_calls={provider_calls} "
        "reused_answers={reused_answers}".format(**summary["warm"])
    )
    print(f"cold_to_warm_median_speedup={summary['cold_to_warm_median_speedup']}")
    print(f"llm_calls_total={summary['llm_calls_total']}")


def _json_payload(
    pairs: list[tuple[RunMetrics, RunMetrics]], summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "summary": summary,
        "runs": [
            run
            for cold, warm in pairs
            for run in (cold.as_dict(), warm.as_dict())
        ],
    }


async def _measure_pair(
    index: int,
    root: Path,
    llm_calls: list[LLMCallStats],
) -> tuple[RunMetrics, RunMetrics]:
    pair_root = root / f"pair-{index + 1}"
    pair_root.mkdir(parents=True, exist_ok=True)
    runtime = _open_runtime(pair_root / "overgraph")
    owner_binding = await open_owner_for_runtime(runtime)
    engine, factory = await _open_database(pair_root / "research.sqlite")
    source = RecordingSource("case_knowledge")
    registry = ResearchSourceRegistry()
    registry.register(source)
    harness = BenchHarness(
        engine=engine,
        factory=factory,
        router=ResearchRouter(registry),
        sources=(source,),
        llm_calls=llm_calls,
    )
    question = f"Vad gäller skattesatsen i kommun {index + 1}?"
    try:
        cold = await _run_attempt(harness, question=question, label="cold")
        warm = await _run_attempt(harness, question=question, label="warm")
    finally:
        await close_owner_binding(owner_binding)
        runtime.close()
        await engine.dispose()
    return cold, warm


async def _benchmark(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="research-bench-"))
    root.mkdir(parents=True, exist_ok=True)
    import app.services.research.composition as composition

    original_embeddings = _install_fake_embeddings()
    llm_calls: list[LLMCallStats] = []
    token = bind_usage_recorder(llm_calls.append)
    pairs: list[tuple[RunMetrics, RunMetrics]] = []
    try:
        for index in range(args.runs):
            pairs.append(await _measure_pair(index, root, llm_calls))
    finally:
        reset_usage_recorder(token)
        composition.research_embeddings = original_embeddings
        set_runtime(None)
    summary = _summary([cold for cold, _warm in pairs], [warm for _cold, warm in pairs])
    payload = _json_payload(pairs, summary)
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    _print_report(pairs, summary)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3, help="cold/warm pairs to run")
    parser.add_argument("--json", default="", help="optional path for raw JSON output")
    parser.add_argument(
        "--data-dir",
        default="",
        help="optional working directory; defaults to a fresh temp directory",
    )
    args = parser.parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be >= 1")
    asyncio.run(_benchmark(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
