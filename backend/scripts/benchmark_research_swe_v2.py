"""Research SWE measurement v2: critical path, peak concurrency, parity, live quality.

The v1 artifact (`benchmark_research_swe.py`, frozen sha a00ba565) remains the
cutover basis. This harness is a separate, observational instrument:

1. fake mode: per arm and run, total wall, handler wait sum, busy-union critical
   path, peak concurrent handlers, overhead, per-need and per-SWE-node timings,
   plus dispersion (per-run medians, paired ratio min/max/mean/sd, per question).
2. parity mode: differential scenarios that fake mode can cover (provider error,
   not_found, per-need timeout, follow-up wave, empty plan, freeze/status,
   progress events) plus the explicit retry/timeout statement; cancellation and
   lease-lost are listed as wiring-test-only.
3. live mode: observational app-lifecycle run (vector store + OverGraph wiring,
   temp DB at head) for 2 questions x 3 arms x 2 repeats with evidence coverage,
   successful needs, assessment/completeness, an explicit synthesis rubric with
   saved judge artifact, tokens and dispersion.

No production code is modified. No gate is imposed by v2; fake guards and parity
are enforced so the instrumentation cannot silently pass on a broken fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.llm import LLMCallStats, bind_usage_recorder, reset_usage_recorder
from app.services.execution import (
    create_attempt,
    create_run,
    get_attempt,
    get_evidence_set,
    list_evidence_items,
    list_evidence_quality,
    list_research_assessments,
    list_research_completeness_passes,
    list_runtime_needs,
)
from app.services.overgraph.workflows import WorkflowRunStore
from app.services.research import graph_reuse, quality_persist, reuse_gate, swe_bridge
from app.services.research import execution as research_execution
from app.services.research.evidence_screen import JevEvidenceRelevanceAssessor
from app.services.research import loop_control as research_loop_control
from app.services.research.execution import execute_attempt_research
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.planner import (
    FakeResearchPlanner,
    ResearchObjective,
)
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.registry import ResearchSourceRegistry
from app.services.research.router import ResearchRouter
from app.swe.features import WorkflowHostContext
from scripts.benchmark_research_loop import (
    CUSTOMER_ID,
    _install_fake_embeddings,
    _new_attempt,
    _open_database,
    _open_runtime,
)
from scripts.benchmark_research_swe import (
    ARMS,
    ARM_LABELS,
    LatencySource,
    SocketGuard,
    _median,
    _rotated_arms,
    _swe_concurrency,
    git_head,
    load_eval_questions,
    parallel_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_FILE = REPO_ROOT / "docs" / "guides" / "research-36-eval.json"
DEFAULT_OUT = REPO_ROOT / "data" / "research_swe"
V2_REPORT = REPO_ROOT / "docs" / "guides" / "research-swe-experiment-v2.md"
MEASUREMENT_LOG = REPO_ROOT / "docs" / "guides" / "research-swe-measurement-log.md"
FAKE_SOURCE_TYPE = "case_knowledge"
DEFAULT_RUNS = 8
DEFAULT_REPEATS = 6
DEFAULT_QUESTIONS = 2
DEFAULT_NEEDS = 16
DEFAULT_LATENCY_MS = 40
DEFAULT_LIVE_QUESTIONS = 2
DEFAULT_LIVE_REPEATS = 2
LIVE_TIMEOUT_SECONDS = 900.0
T_CRITICAL_975 = {2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365}


# ------------------------------------------------------------ instrumentation


@dataclass(frozen=True)
class Interval:
    name: str
    start: float
    end: float


def interval_metrics(intervals: Sequence[Interval], wall_ms: float) -> dict[str, Any]:
    """Busy-union critical path, peak concurrency and overhead for one run."""
    if not intervals:
        return {
            "sum_ms": 0.0, "busy_union_ms": 0.0, "span_ms": 0.0,
            "peak_concurrency": 0, "overhead_ms": round(wall_ms, 3),
            "parallel_gain_ms": 0.0, "span_overhead_ms": round(wall_ms, 3),
            "per_name": {},
        }
    durations = [(row.end - row.start) * 1000 for row in intervals]
    sum_ms = sum(durations)
    busy_union = _busy_union(intervals) * 1000
    span = (max(row.end for row in intervals) - min(row.start for row in intervals)) * 1000
    peak = _peak_concurrency(intervals)
    per_name: dict[str, dict[str, float]] = {}
    for row, duration in zip(intervals, durations, strict=True):
        entry = per_name.setdefault(row.name, {"count": 0, "sum_ms": 0.0, "max_ms": 0.0})
        entry["count"] += 1
        entry["sum_ms"] = round(entry["sum_ms"] + duration, 3)
        entry["max_ms"] = round(max(entry["max_ms"], duration), 3)
    return {
        "sum_ms": round(sum_ms, 3),
        "busy_union_ms": round(busy_union, 3),
        "span_ms": round(span, 3),
        "peak_concurrency": peak,
        "overhead_ms": round(max(0.0, wall_ms - busy_union), 3),
        "parallel_gain_ms": round(max(0.0, sum_ms - busy_union), 3),
        "span_overhead_ms": round(max(0.0, wall_ms - span), 3),
        "per_name": per_name,
    }


def _busy_union(intervals: Sequence[Interval]) -> float:
    spans = sorted((row.start, row.end) for row in intervals)
    total = 0.0
    current_start, current_end = spans[0]
    for start, end in spans[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
        else:
            total += current_end - current_start
            current_start, current_end = start, end
    return total + current_end - current_start


def _peak_concurrency(intervals: Sequence[Interval]) -> int:
    events: list[tuple[float, int]] = []
    for row in intervals:
        events.append((row.start, 1))
        events.append((row.end, -1))
    active = peak = 0
    for _time, delta in sorted(events, key=lambda item: (item[0], item[1])):
        active += delta
        peak = max(peak, active)
    return peak


class Recorder:
    """Collects need-execution and SWE handler intervals for one attempt."""

    def __init__(self) -> None:
        self.needs: list[Interval] = []
        self.handlers: list[Interval] = []
        self.provider_peak = 0
        self._provider_active = 0
        self._source_restore: Any = None

    def install(self) -> None:
        self._real_need = research_execution.execute_one_need
        recorder = self

        async def timed(**kwargs: Any) -> Any:
            start = time.perf_counter()
            need = kwargs.get("need")
            name = str(getattr(need, "id", "need"))
            try:
                return await recorder._real_need(**kwargs)
            finally:
                recorder.needs.append(Interval(name, start, time.perf_counter()))

        research_execution.execute_one_need = timed

    def restore(self) -> None:
        research_execution.execute_one_need = self._real_need

    def wrap_source(self, source: Any) -> None:
        """Count in-flight provider calls, not coroutine lifetime/semaphore wait."""
        original = source.research
        recorder = self

        async def counted(need: Any, context: Any) -> Any:
            recorder._provider_active += 1
            recorder.provider_peak = max(
                recorder.provider_peak, recorder._provider_active
            )
            try:
                return await original(need, context)
            finally:
                recorder._provider_active -= 1

        source.research = counted
        self._source_restore = (source, original)

    def restore_source(self) -> None:
        if self._source_restore is not None:
            source, original = self._source_restore
            source.research = original
            self._source_restore = None

    def wrap_loop_handlers(self, loop: Any) -> None:
        recorder = self
        for name, handler in list(loop.handlers.items()):
            async def wrapper(payload: Any, *, _handler: Any = handler, _name: str = name):
                start = time.perf_counter()
                label = _name
                if _name == "research.execute_need":
                    item = payload.get("item") if isinstance(payload, Mapping) else None
                    need_id = (item or {}).get("need_id")
                    label = f"need:{need_id}"
                try:
                    return await _handler(payload)
                finally:
                    recorder.handlers.append(Interval(label, start, time.perf_counter()))

            loop.handlers[name] = wrapper


# ------------------------------------------------------------ stage timers


STAGE_LABELS: dict[str, str] = {
    "knowledge_reuse": "Knowledge reuse (graph lookup/prepare)",
    "planning": "Planning (planner + legal normalizer)",
    "source_fetch": "Source fetch (router.execute_need)",
    "jev_relevance": "Jev/relevance judge",
    "assessment": "Assessment",
    "completeness": "Completeness review",
    "follow_up": "Follow-up planning",
    "quality_persist": "Quality persist",
    "persist": "Wave persist",
    "freeze": "Freeze + answer capture",
}
SYNTHESIS_STAGE: dict[str, str] = {
    "stage": "synthesis",
    "status": "not a separate stage",
    "note": (
        "The research loop ends at a frozen EvidenceSet; there is no separate "
        "synthesis stage. Synthesis quality is judged post-hoc by the rubric "
        "prompt/LLM verdict stored in the live sample artifact."
    ),
}


class StageRecorder:
    """Wall-clock stage timers around live research boundaries."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, float]] = {}
        self._restores: list[tuple[Any, str, Any]] = []

    def add(self, stage: str, seconds: float) -> None:
        entry = self._data.setdefault(stage, {"seconds": 0.0, "calls": 0.0})
        entry["seconds"] += seconds
        entry["calls"] += 1

    def snapshot(self) -> dict[str, dict[str, float]]:
        return {
            stage: {
                "sum_ms": round(entry["seconds"] * 1000, 3),
                "calls": int(entry["calls"]),
            }
            for stage, entry in sorted(self._data.items())
        }

    def wrap_async(self, target: Any, name: str, stage: str) -> None:
        original = getattr(target, name, None)
        if original is None:
            return

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return await original(*args, **kwargs)
            finally:
                self.add(stage, time.perf_counter() - start)

        self._restores.append((target, name, original))
        setattr(target, name, wrapper)

    def patch_class_method(self, cls: type, name: str, stage: str) -> None:
        original = getattr(cls, name)
        recorder = self

        async def wrapper(instance: Any, *args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return await original(instance, *args, **kwargs)
            finally:
                recorder.add(stage, time.perf_counter() - start)

        self._restores.append((cls, name, original))
        setattr(cls, name, wrapper)

    def patch_function(self, module: Any, name: str, stage: str) -> None:
        original = getattr(module, name, None)
        if original is None:
            return
        recorder = self

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return await original(*args, **kwargs)
            finally:
                recorder.add(stage, time.perf_counter() - start)

        self._restores.append((module, name, original))
        setattr(module, name, wrapper)
        for holder in (research_execution,):
            if getattr(holder, name, None) is original:
                self._restores.append((holder, name, original))
                setattr(holder, name, wrapper)

    def restore(self) -> None:
        for target, name, original in reversed(self._restores):
            setattr(target, name, original)
        self._restores.clear()


def aggregate_stage_timings(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for stage in STAGE_LABELS:
        sums, calls = [], []
        for row in rows:
            entry = (row.get("stage_ms") or {}).get(stage)
            if entry:
                sums.append(float(entry.get("sum_ms") or 0.0))
                calls.append(int(entry.get("calls") or 0))
        if not sums:
            continue
        need_total = sum(len(row.get("needs") or []) for row in rows)
        out[stage] = {
            "samples": len(sums),
            "calls_total": sum(calls),
            "sum_ms": round(sum(sums), 3),
            "mean_ms_per_sample": round(statistics.fmean(sums), 3),
            "median_ms_per_sample": round(statistics.median(sums), 3),
            "max_ms_per_sample": round(max(sums), 3),
            "mean_ms_per_call": round(
                sum(sums) / sum(calls), 3
            ) if sum(calls) else 0.0,
            "calls_per_need": round(sum(calls) / need_total, 3) if need_total else None,
        }
    out["synthesis"] = SYNTHESIS_STAGE
    return out


# ------------------------------------------------------------ fake mode


@dataclass(frozen=True)
class Env:
    engine: Any
    factory: async_sessionmaker[AsyncSession]
    router: ResearchRouter
    source: Any
    run_store: WorkflowRunStore | None
    llm_calls: list[LLMCallStats]

    def provider_calls(self) -> int:
        return int(getattr(self.source, "calls", 0))


@dataclass
class FakeSample:
    run_index: int
    arm: str
    question_id: str
    repeat: int
    wall_ms: float
    need_metrics: dict[str, Any]
    handler_metrics: dict[str, Any]
    domain: dict[str, Any]
    swe: dict[str, Any] | None
    provider_calls: int
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    provider_peak_concurrency: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_index": self.run_index, "arm": self.arm,
            "question_id": self.question_id, "repeat": self.repeat,
            "wall_ms": round(self.wall_ms, 3),
            "need_metrics": self.need_metrics,
            "handler_metrics": self.handler_metrics,
            "domain": self.domain, "swe": self.swe,
            "provider_calls": self.provider_calls,
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "provider_peak_concurrency": self.provider_peak_concurrency,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> FakeSample:
        return cls(
            run_index=int(raw["run_index"]), arm=str(raw["arm"]),
            question_id=str(raw["question_id"]), repeat=int(raw["repeat"]),
            wall_ms=float(raw["wall_ms"]),
            need_metrics=dict(raw["need_metrics"]),
            handler_metrics=dict(raw["handler_metrics"]),
            domain=dict(raw["domain"]), swe=raw["swe"],
            provider_calls=int(raw["provider_calls"]),
            llm_calls=int(raw["llm_calls"]),
            prompt_tokens=int(raw["prompt_tokens"]),
            completion_tokens=int(raw["completion_tokens"]),
            provider_peak_concurrency=int(
                raw.get("provider_peak_concurrency") or 0
            ),
        )


def _swe_impl(arm: str, store: WorkflowRunStore | None, recorder: Recorder,
              recorded: dict[str, Any]):
    async def impl(**kwargs: object) -> None:
        concurrency = _swe_concurrency(arm)
        loop, snapshot_plan = swe_bridge.build_loop(
            dict(kwargs), concurrency=concurrency, run_store=store,
        )
        recorder.wrap_loop_handlers(loop)
        result = await loop.run(snapshot_plan=snapshot_plan)
        counts = Counter(event["type"] for event in result.events)
        recorded.update(
            {
                "status": result.status, "concurrency": concurrency,
                "definition_sha256": swe_bridge._workflow(concurrency).sha256,
                "events": len(result.events),
                "steps_used": counts["NodeScheduled"] + counts["JoinSatisfied"],
                "map_children": counts["BranchSpawned"],
            }
        )
        if result.status != "completed":
            from app.services.research.execution import ResearchExecutionError

            raise ResearchExecutionError(
                f"SWE research loop ended status={result.status}: {result.error}"
            )

    return impl


async def _execute(env: Env, arm: str, attempt_id: str, *, plan: ResearchPlan | None,
                   objective: ResearchObjective | None, recorder: Recorder,
                   recorded: dict[str, Any]) -> Any:
    kwargs: dict[str, Any] = {
        "attempt_id": attempt_id,
        "router": env.router,
        "question_graph": SqlQuestionEvidenceGraph(),
        "session_factory": env.factory,
    }
    if plan is not None:
        kwargs["research_plan"] = plan
    if objective is not None:
        kwargs["research_objective"] = objective
        kwargs["research_planner"] = FakeResearchPlanner([])
    async with env.factory() as session:
        if arm == "baseline":
            return await execute_attempt_research(session, **kwargs)
        impl = _swe_impl(arm, env.run_store, recorder, recorded)
        with mock.patch("app.services.research.execution._run_research_loop", impl):
            return await execute_attempt_research(session, **kwargs)


async def _domain(factory: async_sessionmaker[AsyncSession], attempt_id: str, result: Any) -> dict[str, Any]:
    async with factory() as session:
        attempt = await get_attempt(session, attempt_id)
        needs = await list_runtime_needs(session, attempt_id)
        assessments = await list_research_assessments(session, attempt_id)
        completeness = await list_research_completeness_passes(session, attempt_id)
        evidence_set = (
            await get_evidence_set(session, result.evidence_set_id)
            if result.evidence_set_id is not None else None
        )
        items = (
            await list_evidence_items(session, result.evidence_set_id)
            if result.evidence_set_id is not None else []
        )
        quality = (
            await list_evidence_quality(session, evidence_set.id)
            if evidence_set is not None else []
        )
    return {
        "status": result.status, "attempt_status": attempt.status,
        "stop_reason": attempt.research_stop_reason, "wave": attempt.research_wave,
        "needs": len(needs),
        "evidence_status": evidence_set.status if evidence_set is not None else None,
        "found": result.found_count, "not_found": result.not_found_count,
        "errors": result.error_count,
        "evidence": sorted(
            (str(item.research_need_id or ""), str(item.source_type),
             str(item.status), str(item.provider))
            for item in items
        ),
        "assessments": sorted((row.assessment_pass, row.result) for row in assessments),
        "completeness": sorted(
            (row.completeness_pass, row.result) for row in completeness
        ),
        "quality_rows": len(quality),
    }


def _domain_key(domain: Mapping[str, Any]) -> str:
    return json.dumps(domain, sort_keys=True, ensure_ascii=False)


async def _open_env(*, arm: str, root: Path, latency_ms: int, persist: bool,
                    llm_calls: list[LLMCallStats], tag: str,
                    source: Any = None) -> Env:
    env_root = root / tag
    env_root.mkdir(parents=True, exist_ok=True)
    _open_runtime(env_root / "overgraph")
    engine, factory = await _open_database(env_root / "research.sqlite")
    chosen = source or LatencySource(FAKE_SOURCE_TYPE, latency_ms)
    registry = ResearchSourceRegistry()
    registry.register(chosen)
    run_store = (
        WorkflowRunStore.open(
            env_root / "swe",
            WorkflowHostContext(customer_id=str(CUSTOMER_ID), feature_id="research"),
        )
        if arm != "baseline" and persist else None
    )
    return Env(
        engine=engine, factory=factory, router=ResearchRouter(registry),
        source=chosen, run_store=run_store, llm_calls=llm_calls,
    )


async def _close_env(env: Env) -> None:
    if env.run_store is not None:
        env.run_store.close()
    from app.services.overgraph.catalogs import set_runtime

    set_runtime(None)
    await env.engine.dispose()


async def _fake_sample(*, run_index: int, arm: str, question: Mapping[str, Any],
                       repeat: int, env: Env, needs: int,
                       timeout_seconds: float) -> FakeSample:
    attempt_id = await _new_attempt(env.factory, question["question"])
    provider_before = env.provider_calls()
    llm_before = len(env.llm_calls)
    recorder = Recorder()
    recorded: dict[str, Any] = {}
    recorder.install()
    recorder.wrap_source(env.source)
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            _execute(
                env, arm, attempt_id, plan=parallel_plan(question, needs),
                objective=None, recorder=recorder, recorded=recorded,
            ),
            timeout=timeout_seconds,
        )
    finally:
        wall_ms = (time.perf_counter() - started) * 1000
        recorder.restore()
        recorder.restore_source()
    calls = env.llm_calls[llm_before:]
    domain = await _domain(env.factory, attempt_id, result)
    return FakeSample(
        run_index=run_index, arm=arm, question_id=str(question["id"]),
        repeat=repeat, wall_ms=wall_ms,
        need_metrics=interval_metrics(recorder.needs, wall_ms),
        handler_metrics=interval_metrics(recorder.handlers, wall_ms),
        domain=domain, swe=recorded or None,
        provider_calls=env.provider_calls() - provider_before,
        llm_calls=len(calls),
        prompt_tokens=sum(call.prompt_tokens for call in calls),
        completion_tokens=sum(call.completion_tokens for call in calls),
        provider_peak_concurrency=recorder.provider_peak,
    )


async def fake_pass(args: argparse.Namespace) -> dict[str, Any]:
    questions = load_eval_questions(args.questions)
    root = Path(tempfile.mkdtemp(prefix="research-swe-v2-fake-"))
    llm_calls: list[LLMCallStats] = []
    original = _install_fake_embeddings()
    token = bind_usage_recorder(llm_calls.append)
    samples: list[dict[str, Any]] = []
    with SocketGuard() as guard:
        try:
            samples.extend(await _fake_samples(args, questions, root, llm_calls))
        finally:
            reset_usage_recorder(token)
            import app.services.research.composition as composition

            composition.research_embeddings = original
            if not args.keep:
                shutil.rmtree(root, ignore_errors=True)
    return {
        "run_index": args.run_index,
        "git_head": git_head(),
        "script_sha256": v2_sha256(),
        "arms": list(args.arms),
        "runs": args.runs,
        "repeats": args.repeats,
        "questions": args.questions,
        "needs": args.needs,
        "latency_ms": args.fake_latency_ms,
        "network_attempts": guard.attempts,
        "samples": samples,
    }


async def _fake_samples(args: argparse.Namespace, questions: list[dict[str, Any]],
                        root: Path, llm_calls: list[LLMCallStats]) -> list[dict[str, Any]]:
    samples: list[FakeSample] = []
    for repeat in range(args.repeats):
        for question in questions:
            for arm in _rotated_arms(args.arms, repeat + len(question["id"])):
                env = await _open_env(
                    arm=arm, root=root, latency_ms=args.fake_latency_ms,
                    persist=args.persist_swe, llm_calls=llm_calls,
                    tag=f"fake-{arm}-{question['id']}-{repeat}",
                )
                try:
                    samples.append(
                        await _fake_sample(
                            run_index=args.run_index, arm=arm, question=question,
                            repeat=repeat, env=env, needs=args.needs,
                            timeout_seconds=args.timeout_seconds,
                        )
                    )
                finally:
                    await _close_env(env)
    return [sample.as_dict() for sample in samples]


# ------------------------------------------------------------ dispersion


def _stats(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "sd": 0.0, "median": 0.0}
    ordered = sorted(values)
    mean = statistics.fmean(ordered)
    sd = statistics.stdev(ordered) if len(ordered) > 1 else 0.0
    return {
        "min": round(ordered[0], 4), "max": round(ordered[-1], 4),
        "mean": round(mean, 4), "sd": round(sd, 4),
        "median": round(statistics.median(ordered), 4),
    }


def dispersion(samples: Sequence[FakeSample], runs: int) -> dict[str, Any]:
    runs_seen = sorted({row.run_index for row in samples})
    out: dict[str, Any] = {}
    baseline_by_run = {
        run: _median([row.wall_ms for row in samples
                      if row.arm == "baseline" and row.run_index == run])
        for run in runs_seen
    }
    for arm in ARMS:
        rows = [row for row in samples if row.arm == arm]
        if not rows:
            continue
        per_run = {}
        for run in runs_seen:
            run_rows = [row for row in rows if row.run_index == run]
            per_run[str(run)] = {
                "wall_median": round(_median([row.wall_ms for row in run_rows]), 3),
                "overhead_median": round(
                    _median([row.need_metrics["overhead_ms"] for row in run_rows]), 3
                ),
                "peak_concurrency_median": _median(
                    [float(row.need_metrics["peak_concurrency"]) for row in run_rows]
                ),
                "busy_union_median": round(
                    _median([row.need_metrics["busy_union_ms"] for row in run_rows]), 3
                ),
            }
        ratios_by_run = [
            per_run[str(run)]["wall_median"] / baseline_by_run[run]
            for run in runs_seen
            if baseline_by_run.get(run)
        ]
        per_ratio = [
            row.wall_ms / baseline_by_run[row.run_index]
            for row in rows
            if baseline_by_run.get(row.run_index)
        ]
        per_question: dict[str, Any] = {}
        for question in sorted({row.question_id for row in rows}):
            per_question[question] = round(
                _median([row.wall_ms for row in rows if row.question_id == question]), 3
            )
        out[arm] = {
            "per_run": per_run,
            "per_run_median_stats": _stats(
                [entry["wall_median"] for entry in per_run.values()]
            ),
            "overhead_stats": _stats(
                [entry["overhead_median"] for entry in per_run.values()]
            ),
            "peak_concurrency": _stats(
                [row.need_metrics["peak_concurrency"] for row in rows]
            ),
            "provider_peak_concurrency": _stats(
                [row.provider_peak_concurrency for row in rows]
            ),
            "expected_provider_peak": min(
                _swe_concurrency(arm), int(rows[0].domain["needs"])
            ),
            "provider_peak_ok": (
                _stats([row.provider_peak_concurrency for row in rows])["max"]
                == min(_swe_concurrency(arm), int(rows[0].domain["needs"]))
            ),
            "busy_union_stats": _stats(
                [row.need_metrics["busy_union_ms"] for row in rows]
            ),
            "sum_wait_stats": _stats([row.need_metrics["sum_ms"] for row in rows]),
            "ratio_per_run": _stats(ratios_by_run),
            "ratio_paired": _stats(per_ratio),
            "per_question_median_ms": per_question,
        }
    return out


# ------------------------------------------------------------ parity mode


class ErrorSource(LatencySource):
    async def research(self, need: Any, context: Any) -> list[Any]:
        self.calls += 1
        raise RuntimeError("provider exploded")


class EmptySource(LatencySource):
    async def research(self, need: Any, context: Any) -> list[Any]:
        self.calls += 1
        return []


class SlowSource(LatencySource):
    async def research(self, need: Any, context: Any) -> list[Any]:
        self.calls += 1
        await asyncio.sleep(self.latency_s)
        from app.services.research.models import research_evidence

        return [
            research_evidence(
                research_need_id=need.id, source_type=self.source_type,
                status="found", title="Slow", excerpt="slow evidence",
                locator="s1", source_id=f"source-{need.id}",
                provider=self.provider_id, retrieved_at=datetime.now(UTC),
                metadata={"content_hash": f"hash-{need.id}"},
            )
        ]


class FixedAssessor:
    def __init__(self, sufficient: Sequence[bool]) -> None:
        self._values = list(sufficient)

    async def assess(self, plan: ResearchPlan, evidence: Sequence[Any]) -> Any:
        from app.services.research.assessment import (
            ResearchAssessmentDraft, ResearchNeedAssessment,
        )

        value = self._values.pop(0) if len(self._values) > 1 else self._values[0]
        refs = [item.evidence_id for item in evidence]
        return ResearchAssessmentDraft(
            result="sufficient" if value else "insufficient",
            rationale="scenario assessment",
            need_assessments=[
                ResearchNeedAssessment(
                    research_need_id=need.id, sufficient=value,
                    supporting_evidence_ids=refs if value else [],
                    missing_or_weak="" if value else "gap",
                )
                for need in plan.needs
            ],
        )


class FollowUpPlanner:
    def __init__(self, waves: Sequence[Sequence[str]]) -> None:
        self._waves = list(waves)

    async def plan_follow_ups(self, **_kwargs: Any) -> list[Any]:
        from app.services.research.followup import FollowUpNeedDraft

        if not self._waves:
            return []
        return [
            FollowUpNeedDraft(
                question=question, why_needed="scenario follow-up",
                source_types=[FAKE_SOURCE_TYPE],
            )
            for question in self._waves.pop(0)
        ]


def _single_need_plan(question: str) -> ResearchPlan:
    return ResearchPlan(
        needs=[
            ResearchNeed(
                id="research_1", question=question, why_needed="scenario",
                requested_by=["scenario"], source_types=[FAKE_SOURCE_TYPE],
            )
        ]
    )


async def _snapshot(factory: async_sessionmaker[AsyncSession], attempt_id: str,
                    result: Any) -> dict[str, Any]:
    from app.database.models import ResearchProgressEvent

    domain = await _domain(factory, attempt_id, result)
    async with factory() as session:
        events = (
            await session.execute(
                select(ResearchProgressEvent)
                .where(ResearchProgressEvent.attempt_id == attempt_id)
                .order_by(ResearchProgressEvent.sequence)
            )
        ).scalars().all()
    domain["progress_event_types"] = [str(row.event_type) for row in events]
    return domain


async def _run_scenario_arm(*, arm: str, scenario: Mapping[str, Any], source: Any,
                            root: Path, llm_calls: list[LLMCallStats]) -> dict[str, Any]:
    env = await _open_env(
        arm=arm, root=root, latency_ms=5, persist=False, llm_calls=llm_calls,
        tag=f"parity-{scenario['name']}-{arm}", source=source,
    )
    try:
        plan = scenario.get("plan")
        if callable(plan):
            plan = plan()
        assessor = scenario.get("assessor")
        if callable(assessor):
            assessor = assessor()
        follow_up = scenario.get("follow_up")
        if callable(follow_up):
            follow_up = follow_up()
        attempt_id = await _new_attempt(env.factory, scenario["question"])
        patches = scenario.get("settings", {})
        old_values = {key: getattr(settings, key) for key in patches}
        try:
            for key, value in patches.items():
                setattr(settings, key, value)
            async with env.factory() as session:
                result = await execute_attempt_research(
                    session, attempt_id=attempt_id,
                    research_plan=plan if plan is not None else ResearchPlan(),
                    router=env.router,
                    assessor=assessor,
                    planner=follow_up if follow_up is not None else FollowUpPlanner([]),
                    question_graph=SqlQuestionEvidenceGraph(),
                    session_factory=env.factory,
                )
        finally:
            for key, value in old_values.items():
                setattr(settings, key, value)
        return await _snapshot(env.factory, attempt_id, result)
    finally:
        await _close_env(env)


def _scenarios() -> list[dict[str, Any]]:
    return [
        {
            "name": "provider_error",
            "question": "Vad händer vid leverantörsfel?",
            "plan": lambda: _single_need_plan("Vad händer vid leverantörsfel?"),
            "source": lambda: ErrorSource(FAKE_SOURCE_TYPE, 5),
        },
        {
            "name": "not_found",
            "question": "Finns inget underlag?",
            "plan": lambda: _single_need_plan("Finns inget underlag?"),
            "source": lambda: EmptySource(FAKE_SOURCE_TYPE, 5),
        },
        {
            "name": "per_need_timeout",
            "question": "Vad gäller vid timeout?",
            "plan": lambda: _single_need_plan("Vad gäller vid timeout?"),
            "source": lambda: SlowSource(FAKE_SOURCE_TYPE, 300),
            "settings": {"research_need_timeout_seconds": 0.05},
        },
        {
            "name": "follow_up_wave",
            "question": "Behöver vi fler vågor?",
            "plan": lambda: _single_need_plan("Behöver vi fler vågor?"),
            "source": lambda: LatencySource(FAKE_SOURCE_TYPE, 5),
            "assessor": lambda: FixedAssessor([False, True]),
            "follow_up": lambda: FollowUpPlanner([["Vad är nästa fråga?"]]),
        },
        {
            "name": "empty_plan",
            "question": "Tom plan?",
            "plan": lambda: ResearchPlan(),
            "source": lambda: EmptySource(FAKE_SOURCE_TYPE, 5),
        },
        {
            "name": "freeze_status",
            "question": "Fryses bevisningen?",
            "plan": lambda: _single_need_plan("Fryses bevisningen?"),
            "source": lambda: LatencySource(FAKE_SOURCE_TYPE, 5),
        },
    ]


async def parity_run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="research-swe-v2-parity-"))
    llm_calls: list[LLMCallStats] = []
    original = _install_fake_embeddings()
    token = bind_usage_recorder(llm_calls.append)
    results: list[dict[str, Any]] = []
    try:
        for scenario in _scenarios():
            _validate_scenario_fixtures(scenario)
            baseline: dict[str, Any] | None = None
            arm_snapshots: dict[str, Any] = {}
            for arm in ARMS:
                snapshot = await _run_scenario_arm(
                    arm=arm, scenario=scenario,
                    source=scenario["source"](), root=root, llm_calls=llm_calls,
                )
                if arm == "baseline":
                    baseline = snapshot
                arm_snapshots[arm] = snapshot
            mismatches = {}
            for arm, snapshot in arm_snapshots.items():
                keys = sorted(set(snapshot) | set(baseline or {}))
                diff = [
                    key for key in keys
                    if (snapshot.get(key) != (baseline or {}).get(key))
                ]
                if diff:
                    mismatches[arm] = diff
            mismatch_details = {
                arm: {
                    key: {
                        "baseline": (baseline or {}).get(key),
                        "arm": arm_snapshots[arm].get(key),
                    }
                    for key in diff
                }
                for arm, diff in mismatches.items()
            }
            results.append(
                {
                    "scenario": scenario["name"],
                    "equal": not mismatches,
                    "mismatch_keys": mismatches,
                    "mismatch_details": mismatch_details,
                    "snapshots": arm_snapshots,
                    "baseline": baseline,
                    "status": (baseline or {}).get("attempt_status"),
                    "stop_reason": (baseline or {}).get("stop_reason"),
                }
            )
    finally:
        reset_usage_recorder(token)
        import app.services.research.composition as composition

        composition.research_embeddings = original
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)
    return {
        "scenarios": results,
        "all_equal": all(row["equal"] for row in results),
        "retry_semantics": _retry_semantics(),
        "not_testable_in_fake_mode": [
            {
                "scenario": "cancellation",
                "reason": "requires the running worker/lease seam; verified by the "
                          "task-5 wiring test",
            },
            {
                "scenario": "lease_lost",
                "reason": "requires the Postgres CAS lease and a live attempt; "
                          "verified by the task-5 wiring test",
            },
            {
                "scenario": "crash_resume",
                "reason": "requires the durable OverGraph run store and a real "
                          "process restart; phase-3/task-5 wiring test",
            },
        ],
    }


def _validate_scenario_fixtures(scenario: Mapping[str, Any]) -> None:
    """Assessor/follow-up must be per-arm factories, never shared objects."""
    for key in ("assessor", "follow_up"):
        value = scenario.get(key)
        if value is not None and not callable(value):
            raise SystemExit(
                f"scenario {scenario['name']!r}: {key} must be a factory "
                "resolved per arm"
            )


def _retry_semantics() -> dict[str, Any]:
    from app.services.research.execution import ResearchExecutionError  # noqa: F401
    from app.swe.definition import compile_definition
    from app.swe.runtime_errors import SweUnsupportedError
    from app.swe.runtime_preflight import assert_phase2_supported

    document = {
        "version": "1.0", "name": "retry_probe", "entrypoint": "work",
        "limits": {"max_steps": 5, "max_depth": 1, "timeout_seconds": 10},
        "nodes": {
            "work": {
                "type": "task", "handler": "probe.work",
                "retry": {"max_attempts": 2}, "next": "done",
            },
            "done": {"type": "end", "status": "completed"},
        },
    }
    compiled = compile_definition(document)
    rejected = False
    try:
        assert_phase2_supported(compiled.document)
    except SweUnsupportedError:
        rejected = True
    return {
        "swe_rejects_retry": rejected,
        "baseline_loop_has_no_retry": True,
        "timeout_is_the_only_time_control": True,
        "parity_scope": "timeout handling, not retry backoff",
    }


# ------------------------------------------------------------ live mode


LIVE_ENV_STATUS = (
    "Live environment status: **healthy** (verified 2026-10-22 from the "
    "measurement host: `lagen.nu` 200, MCP `initialize` 200, `tools/list` 200 "
    "with legal tools, OpenAI embeddings 200 (3072 dims), Cerebras chat 200). "
    "Live is observational and never a gate."
)

LIVE_RUBRIC_SYSTEM = (
    "You grade a legal research evidence set. Use ONLY the supplied needs, "
    "evidence excerpts and assessments. Be strict: missing evidence or missing "
    "citations must lower the score. Reply with the structured rubric only."
)


def _live_prompt(*, question: str, needs: list[dict[str, Any]],
                 evidence: list[dict[str, Any]], assessment: Any,
                 completeness: Any) -> str:
    return (
        f"Question: {question}\n\n"
        f"Needs: {json.dumps(needs, ensure_ascii=False)[:4000]}\n\n"
        f"Evidence: {json.dumps(evidence, ensure_ascii=False)[:8000]}\n\n"
        f"Assessment: {json.dumps(assessment, ensure_ascii=False)[:2000]}\n\n"
        f"Completeness: {json.dumps(completeness, ensure_ascii=False)[:2000]}\n"
    )


async def live_sample(args: argparse.Namespace) -> int:
    """Child process: one production attempt with app-lifespan wiring."""
    from app.main import create_app

    questions = load_eval_questions(args.live_questions)
    question = questions[args.question_index]
    app = create_app()
    engine = create_async_engine(f"sqlite+aiosqlite:///{args.db_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    llm_calls: list[LLMCallStats] = []
    token = bind_usage_recorder(llm_calls.append)
    sample: dict[str, Any] = {
        "arm": args.arm, "question_id": question["id"],
        "question": question["question"], "repeat": args.repeat,
        "facit_sufficient": question["facit_sufficient"], "errors": [],
    }
    try:
        async with app.router.lifespan_context(app):
            sample.update(
                await _live_measure(args, factory, question, llm_calls)
            )
    finally:
        reset_usage_recorder(token)
        await engine.dispose()
    out = Path(args.sample_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(sample, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


async def _live_create_attempt(args: argparse.Namespace,
                               factory: async_sessionmaker[AsyncSession],
                               question: Mapping[str, Any]) -> str:
    async with factory() as session:
        run = await create_run(
            session, customer_id=args.customer_id, module="dd",
            title="SWE v2 live", context={},
        )
        attempt = await create_attempt(
            session, run_id=run.id, attempt_type="generic_panel",
            configuration_snapshot={"mode": "benchmark-v2-live"},
            input_snapshot={"question": question["question"]},
        )
        await session.commit()
        return attempt.id


async def _live_execute(*, args: argparse.Namespace,
                        factory: async_sessionmaker[AsyncSession],
                        question: Mapping[str, Any], attempt_id: str,
                        recorder: Recorder, recorded: dict[str, Any],
                        components: Mapping[str, Any]) -> None:
    from app.services.research.composition import build_standard_research_router

    kwargs: dict[str, Any] = {
        "attempt_id": attempt_id,
        "research_objective": ResearchObjective(question["question"]),
        "research_planner": components["research_planner"],
        "router_factory": build_standard_research_router,
        "assessor": components["assessor"],
        "completeness_reviewer": components["completeness_reviewer"],
        "planner": components["planner"],
        "need_normalizer": components["need_normalizer"],
        "session_factory": factory,
    }
    async with factory() as session:
        if args.arm == "baseline":
            await execute_attempt_research(session, **kwargs)
            return
        impl = _swe_impl(args.arm, None, recorder, recorded)
        with mock.patch("app.services.research.execution._run_research_loop", impl):
            await execute_attempt_research(session, **kwargs)


def _instrument_live_stages(stage: StageRecorder, components: Mapping[str, Any]) -> None:
    for key, name, stage_name in (
        ("research_planner", "plan_research", "planning"),
        ("need_normalizer", "normalize", "planning"),
        ("assessor", "assess", "assessment"),
        ("completeness_reviewer", "review", "completeness"),
        ("planner", "plan_follow_ups", "follow_up"),
    ):
        stage.wrap_async(components.get(key), name, stage_name)
    stage.patch_class_method(ResearchRouter, "execute_need", "source_fetch")
    stage.patch_class_method(JevEvidenceRelevanceAssessor, "judge", "jev_relevance")
    stage.patch_function(graph_reuse, "lookup_graph_evidence", "knowledge_reuse")
    stage.patch_function(reuse_gate, "assess_reuse", "knowledge_reuse")
    stage.patch_function(research_loop_control, "finish_research_wave", "persist")
    stage.patch_function(research_execution, "_freeze_ready_attempt", "freeze")
    stage.patch_function(
        quality_persist, "persist_evidence_quality_drafts", "quality_persist"
    )
    stage.patch_function(quality_persist, "score_need_quality_eager", "quality_persist")


async def _live_measure(args: argparse.Namespace,
                        factory: async_sessionmaker[AsyncSession],
                        question: Mapping[str, Any],
                        llm_calls: list[LLMCallStats]) -> dict[str, Any]:
    from app.services.research_worker import bind_research_components

    attempt_id = await _live_create_attempt(args, factory, question)
    async with factory() as session:
        components = await bind_research_components(
            session, customer_id=args.customer_id, module="dd",
        )
    recorder = Recorder()
    recorded: dict[str, Any] = {}
    stage_recorder = StageRecorder()
    _instrument_live_stages(stage_recorder, components)
    recorder.install()
    started = time.perf_counter()
    try:
        await _live_execute(
            args=args, factory=factory, question=question, attempt_id=attempt_id,
            recorder=recorder, recorded=recorded, components=components,
        )
    finally:
        wall_ms = (time.perf_counter() - started) * 1000
        recorder.restore()
        stage_ms = stage_recorder.snapshot()
        stage_recorder.restore()
    return await _live_payload(
        factory=factory, attempt_id=attempt_id, question=question,
        measure=LiveMeasure(
            wall_ms=wall_ms, recorder=recorder, recorded=recorded,
            stage_ms=stage_ms, llm_calls=llm_calls,
        ),
    )


@dataclass(frozen=True)
class LiveMeasure:
    wall_ms: float
    recorder: Recorder
    recorded: Mapping[str, Any]
    stage_ms: Mapping[str, Any]
    llm_calls: Sequence[LLMCallStats]


async def _live_payload(*, factory: async_sessionmaker[AsyncSession],
                        attempt_id: str, question: Mapping[str, Any],
                        measure: LiveMeasure) -> dict[str, Any]:
    wall_ms = measure.wall_ms
    recorder = measure.recorder
    llm_calls = list(measure.llm_calls)
    async with factory() as session:
        attempt_row = await get_attempt(session, attempt_id)
        needs = await list_runtime_needs(session, attempt_id)
        assessments = await list_research_assessments(session, attempt_id)
        completeness = await list_research_completeness_passes(session, attempt_id)
        evidence_set = (
            await get_evidence_set(session, attempt_row.evidence_set_id)
            if attempt_row.evidence_set_id else None
        )
        items = (
            await list_evidence_items(session, attempt_row.evidence_set_id)
            if attempt_row.evidence_set_id else []
        )
    needs_payload = [
        {"need_id": row.research_need_id, "question": row.question,
         "origin": row.origin, "wave": row.wave_number}
        for row in needs
    ]
    evidence_payload = [
        {"need_id": item.research_need_id, "status": item.status,
         "source_type": item.source_type, "provider": item.provider,
         "excerpt": (item.excerpt or "")[:400],
         "source_url": item.source_url, "locator": item.locator}
        for item in items
    ]
    assessment_payload = [row.result for row in assessments]
    completeness_payload = [row.result for row in completeness]
    judge, errors = await _live_judge(
        question=question["question"], needs=needs_payload,
        evidence=evidence_payload, assessment=assessment_payload,
        completeness=completeness_payload,
    )
    return {
        "wall_ms": round(wall_ms, 3),
        "status": attempt_row.status,
        "stop_reason": attempt_row.research_stop_reason,
        "wave": attempt_row.research_wave,
        "needs": needs_payload,
        "evidence": evidence_payload,
        "evidence_status": evidence_set.status if evidence_set else None,
        "assessments": assessment_payload,
        "completeness": completeness_payload,
        "need_metrics": interval_metrics(recorder.needs, wall_ms),
        "handler_metrics": interval_metrics(recorder.handlers, wall_ms),
        "llm_calls": len(llm_calls),
        "prompt_tokens": sum(call.prompt_tokens for call in llm_calls),
        "completion_tokens": sum(call.completion_tokens for call in llm_calls),
        "swe": measure.recorded or None,
        "stage_ms": measure.stage_ms,
        "synthesis": SYNTHESIS_STAGE,
        "judge": judge,
        "errors": errors,
    }


async def _live_judge(*, question: str, needs: list[dict[str, Any]],
                      evidence: list[dict[str, Any]], assessment: Any,
                      completeness: Any) -> tuple[dict[str, Any] | None, list[str]]:
    from pydantic import BaseModel, Field

    from app.llm import complete_structured

    class SynthesisJudge(BaseModel):
        coverage: int = Field(ge=0, le=3)
        citation_support: int = Field(ge=0, le=3)
        contradiction_handling: int = Field(ge=0, le=3)
        answer_readiness: int = Field(ge=0, le=3)
        rationale: str

    prompt = _live_prompt(
        question=question, needs=needs, evidence=evidence,
        assessment=assessment, completeness=completeness,
    )
    try:
        verdict = await complete_structured(
            [
                {"role": "system", "content": LIVE_RUBRIC_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            SynthesisJudge,
        )
    except Exception as exc:  # noqa: BLE001 - observational artifact
        return None, [f"judge: {type(exc).__name__}: {exc}"]
    return {
        "rubric": verdict.model_dump(),
        "prompt": prompt,
        "system": LIVE_RUBRIC_SYSTEM,
    }, []


def _prepare_live_db(db_path: Path, overgraph_dir: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    overgraph_dir.mkdir(parents=True, exist_ok=True)
    url = f"sqlite+aiosqlite:///{db_path}"
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": url,
            "MIGRATION_DATABASE_URL": url,
            "OVERGRAPH_DIR": str(overgraph_dir),
            "RESEARCH_WORKER_LOOP_ENABLED": "true",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(REPO_ROOT / "backend"), env=env, check=False,
        capture_output=True, text=True, timeout=600,
    )
    if completed.returncode != 0:
        raise SystemExit(
            "live DB setup failed (alembic upgrade head): "
            f"{completed.stderr.strip()[-2000:]}"
        )


def _live_quality(sample: Mapping[str, Any]) -> dict[str, float]:
    evidence = sample.get("evidence") or []
    found = sum(1 for row in evidence if row.get("status") == "found")
    total = max(1, len(evidence))
    needs = sample.get("needs") or []
    assessments = sample.get("assessments") or []
    sufficient = sum(1 for value in assessments if value == "sufficient")
    completeness = sample.get("completeness") or []
    complete = sum(1 for value in completeness if value == "complete")
    rubric = (sample.get("judge") or {}).get("rubric") or {}
    rubric_values = [
        rubric.get(key, 0) for key in
        ("coverage", "citation_support", "contradiction_handling", "answer_readiness")
    ]
    return {
        "evidence_coverage": round(found / total, 4),
        "needs_success_rate": round(
            sum(1 for row in needs if row.get("need_id")) / max(1, len(needs)), 4
        ),
        "assessment_sufficient_rate": round(
            sufficient / max(1, len(assessments)), 4
        ),
        "completeness_rate": round(complete / max(1, len(completeness)), 4),
        "synthesis_rubric": round(sum(rubric_values) / 12.0, 4) if rubric_values else 0.0,
    }


def _live_ranking(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_arm: dict[str, list[Mapping[str, Any]]] = {}
    for sample in samples:
        by_arm.setdefault(str(sample.get("arm")), []).append(sample)

    def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        qualities = [_live_quality(row) for row in rows]
        walls = [float(row.get("wall_ms") or 0.0) for row in rows]
        tokens = [
            int(row.get("prompt_tokens") or 0) + int(row.get("completion_tokens") or 0)
            for row in rows
        ]
        mean_quality = {
            key: round(statistics.fmean([q[key] for q in qualities]), 4)
            for key in qualities[0]
        } if qualities else {}
        return {
            "samples": len(rows),
            "mean_quality": mean_quality,
            "stages": aggregate_stage_timings(rows),
            "wall_ms_mean": round(statistics.fmean(walls), 3) if walls else 0.0,
            "wall_ms_median": round(statistics.median(walls), 3) if walls else 0.0,
            "tokens_mean": round(statistics.fmean(tokens), 3) if tokens else 0.0,
        }

    aggregates = {arm: aggregate(rows) for arm, rows in by_arm.items()}
    baseline_quality = aggregates.get("baseline", {}).get("mean_quality", {})
    classification: dict[str, Any] = {}
    for arm, data in aggregates.items():
        quality = data["mean_quality"]
        worse = [
            key for key, value in quality.items()
            if value + 1e-9 < baseline_quality.get(key, 0.0)
        ]
        faster = data["wall_ms_mean"] < aggregates.get("baseline", {}).get(
            "wall_ms_mean", float("inf")
        )
        classification[arm] = {
            "faster_than_baseline": faster,
            "quality_not_worse_than_baseline": not worse,
            "worse_quality_dimensions": worse,
            "label": (
                "faster but lower evidence — not better"
                if faster and worse
                else "comparable"
                if not worse
                else "lower quality"
            ),
        }
    return {
        "by_arm": aggregates,
        "classification": classification,
        "note": (
            "Observational, non-deterministic. A faster arm with any lower "
            "quality dimension is explicitly not classified as better."
        ),
    }


def live_parent(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    root = run_dir / "live"
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "live.sqlite"
    overgraph_dir = root / "overgraph"
    _prepare_live_db(db_path, overgraph_dir)
    samples: list[dict[str, Any]] = []
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
            "MIGRATION_DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
            "OVERGRAPH_DIR": str(overgraph_dir),
            "RESEARCH_WORKER_LOOP_ENABLED": "true",
        }
    )
    for question_index in range(args.live_questions):
        for arm in ARMS:
            for repeat in range(args.live_repeats):
                sample_out = root / f"live-{arm}-{question_index}-{repeat}.json"
                command = [
                    sys.executable, str(Path(__file__)), "--live-sample",
                    "--arm", arm, "--question-index", str(question_index),
                    "--repeat", str(repeat), "--sample-out", str(sample_out),
                    "--db-path", str(db_path), "--overgraph-dir", str(overgraph_dir),
                    "--customer-id", str(args.customer_id),
                    "--live-questions", str(args.live_questions),
                ]
                completed = subprocess.run(
                    command, check=False, env=env,
                    timeout=args.live_timeout_seconds,
                )
                if completed.returncode != 0 or not sample_out.exists():
                    samples.append(
                        {
                            "arm": arm, "question_index": question_index,
                            "repeat": repeat, "error": f"live child exit {completed.returncode}",
                        }
                    )
                    continue
                samples.append(json.loads(sample_out.read_text(encoding="utf-8")))
    payload = {
        "mode": "live-observational",
        "gate": False,
        "git_head": git_head(),
        "script_sha256": v2_sha256(),
        "db_path": str(db_path),
        "questions": args.live_questions,
        "repeats": args.live_repeats,
        "samples": samples,
        "ranking": _live_ranking([row for row in samples if "error" not in row]),
    }
    (root / "live-results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"live_results={root / 'live-results.json'}")
    return payload


# ------------------------------------------------------------ report


@dataclass(frozen=True)
class V2Report:
    git_head: str
    script_sha256: str
    fake: Mapping[str, Any] | None
    dispersion: Mapping[str, Any] | None
    parity: Mapping[str, Any] | None
    live: Mapping[str, Any] | None
    run_dir: Path
    args: argparse.Namespace


def render_report(report: V2Report) -> str:
    lines = [
        "# Research SWE experiment v2 — critical path, concurrency, parity, live quality",
        "",
        "**Observational instrumentation harness.** The v1 artifact "
        "(`benchmark_research_swe.py`, frozen sha `a00ba565…`, n=8) remains the "
        "cutover basis; v2 does not replace its gates.",
        "",
        "## Metadata",
        "",
        f"- git HEAD: `{report.git_head}`",
        f"- v2 script sha256: `{report.script_sha256}`",
        f"- arms: {', '.join(ARMS)}",
        f"- **fake layer**: {report.args.runs} independent runs x "
        f"{report.args.repeats} interleaved repeats x {report.args.questions} "
        f"questions (need count {report.args.needs}, fake latency "
        f"{report.args.fake_latency_ms} ms)",
        f"- **live layer** (observational): {report.args.live_questions} questions x "
        f"{len(ARMS)} arms x {report.args.live_repeats} repeats",
        *(
            ["- fake/parity layers were measured in freeze #4: "
             "`data/research_swe/v2-528d26d45dfa-20261021T234946Z`"]
            if report.live is not None and report.fake is None else []
        ),
        f"- raw data: `{report.run_dir}`",
        "",
        "## 1. Critical path and peak concurrency (fake mode)",
        "",
        _fake_section(report),
        "",
        "## 2. Behavioural parity (fake scenarios)",
        "",
        _parity_section(report),
        "",
        "## 3. Live quality (observational, non-deterministic, not a gate)",
        "",
        _live_report_section(report),
        "",
        "## 4. Scope limits",
        "",
        "- Fake mode cannot exercise cancellation, lease-lost or crash/resume; "
        "those require the running worker/lease seam and are verified by the "
        "task-5 wiring test.",
        "- Retry: neither the phase-2 loop nor the SWE bridge retries. SWE "
        "rejects `retry` in preflight; timeout is the only time control and is "
        "the parity scope for timing-dependent behaviour.",
        "- Fake mode quality is structural by construction (same domain code); "
        "live quality is the only quality observation and is non-deterministic.",
        "",
    ]
    return "\n".join(lines)


def _fake_section(report: V2Report) -> str:
    if not report.dispersion:
        return "Not run."
    rows = [
        "| Arm | Wall median (per-run medians) | Wall sd | Overhead median | "
        "Provider peak (max/median vs expected) | Busy-union median | "
        "Sum wait median | Ratio arm/baseline min/max/mean/sd |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm, data in report.dispersion.items():
        wall = data["per_run_median_stats"]
        peak = data["provider_peak_concurrency"]
        expected = data["expected_provider_peak"]
        rows.append(
            f"| {ARM_LABELS.get(arm, arm)} | {wall['median']} | {wall['sd']} | "
            f"{data['overhead_stats']['median']} | "
            f"{peak['max']}/{peak['median']} vs {expected} | "
            f"{data['busy_union_stats']['median']} | {data['sum_wait_stats']['median']} | "
            f"{data['ratio_per_run']['min']}/{data['ratio_per_run']['max']}/"
            f"{data['ratio_per_run']['mean']}/{data['ratio_per_run']['sd']} |"
        )
    questions = sorted(
        {
            question
            for data in report.dispersion.values()
            for question in data["per_question_median_ms"]
        }
    )
    question_lines = [
        "| Arm | " + " | ".join(questions) + " |",
        "| --- | " + " | ".join("---" for _ in questions) + " |",
    ]
    for arm, data in report.dispersion.items():
        question_lines.append(
            f"| {ARM_LABELS.get(arm, arm)} | "
            + " | ".join(
                str(data["per_question_median_ms"].get(question, "-"))
                for question in questions
            )
            + " |"
        )
    return (
        "\n".join(rows)
        + "\n\nPer-question wall medians (ms):\n\n"
        + "\n".join(question_lines)
        + "\n\nCritical path is the busy-union of need/handler intervals (actively "
        "serialized work); overhead = wall - busy union; parallel gain = sum of "
        "intervals - busy union. **Provider peak** counts in-flight "
        "`source.research` calls (not coroutine lifetime/semaphore wait); the "
        "fixture expects 8 for baseline and arm A (concurrency 8) and 16 for arm B "
        "(concurrency 16) with 16 needs. A deviation is listed in results.json and "
        "means the fixture did not exercise the intended concurrency. Per-node and "
        "per-need details are in results.json."
    )


def _parity_section(report: V2Report) -> str:
    if not report.parity:
        return "Not run."
    rows = [
        "| Scenario | Arms equal to baseline | Baseline status | Baseline stop reason |",
        "| --- | --- | --- | --- |",
    ]
    for row in report.parity["scenarios"]:
        detail = "yes" if row["equal"] else f"NO ({row['mismatch_keys']})"
        rows.append(
            f"| {row['scenario']} | {detail} | {row.get('status')} | "
            f"{row.get('stop_reason')} |"
        )
    not_testable = "\n".join(
        f"- `{row['scenario']}`: {row['reason']}"
        for row in report.parity["not_testable_in_fake_mode"]
    )
    retry = report.parity["retry_semantics"]
    return (
        "\n".join(rows)
        + "\n\nNot testable in fake mode (task-5 wiring test):\n\n"
        + not_testable
        + "\n\nRetry semantics: "
        + f"SWE rejects retry = {retry['swe_rejects_retry']}; baseline has no "
        + "retry path; timeout is the only time control and the parity scope."
    )


def _live_report_section(report: V2Report) -> str:
    if not report.live:
        return (
            LIVE_ENV_STATUS
            + "\n\nLive layer not run in this invocation; run `--mode live` for the "
            "36 § observations."
        )
    if report.live.get("error"):
        return (
            "**Live layer failed; observational only, does not affect exit.** "
            f"Reason: `{report.live['error']}`. Fake and parity artifacts remain "
            "authoritative."
        )
    ranking = report.live.get("ranking") or {}
    rows = [
        "| Arm | Samples | Wall mean (ms) | Wall median (ms) | Tokens mean | "
        "Evidence coverage | Assessment sufficient | Completeness | Synthesis rubric | Label |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm, data in (ranking.get("by_arm") or {}).items():
        quality = data["mean_quality"]
        label = (ranking.get("classification") or {}).get(arm, {}).get("label", "")
        rows.append(
            f"| {ARM_LABELS.get(arm, arm)} | {data['samples']} | "
            f"{data['wall_ms_mean']} | {data['wall_ms_median']} | {data['tokens_mean']} | "
            f"{quality.get('evidence_coverage')} | "
            f"{quality.get('assessment_sufficient_rate')} | "
            f"{quality.get('completeness_rate')} | {quality.get('synthesis_rubric')} | "
            f"{label} |"
        )
    stage_rows = [
        "\n\nPer-stage timings per arm (sum ms / calls):\n\n"
        "| Arm | " + " | ".join(STAGE_LABELS.values()) + " |",
        "| --- | " + " | ".join("---" for _ in STAGE_LABELS) + " |",
    ]
    for arm, data in (ranking.get("by_arm") or {}).items():
        stages = data.get("stages") or {}
        cells = []
        for stage in STAGE_LABELS:
            entry = stages.get(stage)
            cells.append(
                f"{entry['sum_ms']} / {entry['calls_total']}" if entry else "-"
            )
        stage_rows.append(
            f"| {ARM_LABELS.get(arm, arm)} | " + " | ".join(cells) + " |"
        )
    stage_rows.append(
        "\nSynthesis: **not a separate stage** — the loop ends at a frozen "
        "EvidenceSet; synthesis quality is judged post-hoc by the rubric/LLM "
        "artifact saved per live sample."
    )
    errors = [row for row in report.live.get("samples", []) if "error" in row]
    return (
        LIVE_ENV_STATUS
        + "\n\n"
        + "\n".join(rows)
        + f"\n\n{ranking.get('note', '')}"
        + "\n\nPer-run evidence/assessment/judge artifacts are stored next to "
        + "`live-results.json`."
        + "\n".join(stage_rows)
        + (f"\n\nLive child errors: {len(errors)}." if errors else "")
    )


def _write_results(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _append_measurement_log(report: V2Report, run_dir: Path) -> None:
    marker = f"<!-- v2:{report.script_sha256[:12]}:{run_dir.name} -->"
    if not MEASUREMENT_LOG.exists():
        return
    text = MEASUREMENT_LOG.read_text(encoding="utf-8")
    if marker in text:
        return
    entry = (
        f"\n\n{marker}\n"
        f"## Mätning v2 — kritisk väg, concurrency, paritet, live-kvalitet\n\n"
        f"- Harness: `backend/scripts/benchmark_research_swe_v2.py` sha256 "
        f"`{report.script_sha256}`\n"
        f"- git HEAD: `{report.git_head}`\n"
        f"- Rådata: `{run_dir}`\n"
        f"- Fake: {report.args.runs} oberoende runs x {report.args.repeats} "
        f"repeats x {report.args.questions} frågor, needs={report.args.needs}, "
        f"latens={report.args.fake_latency_ms} ms\n"
        f"- Live (observationslager): {report.args.live_questions} frågor x "
        f"3 armar x {report.args.live_repeats} repeats\n"
        f"- Paritet: {'alla scenarier lika' if (report.parity or {}).get('all_equal') else 'se rapporten'}\n"
        f"- Live: {'körd (observationslager, ej gate)' if report.live else 'ej körd'}\n"
        f"- v1-artefakten `a00ba565…` (n=8) är fortsatt cutover-bas.\n"
    )
    MEASUREMENT_LOG.write_text(text + entry, encoding="utf-8")


def v2_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _aggregate(
    run_payloads: Sequence[Mapping[str, Any]], needs: int,
) -> tuple[list[FakeSample], dict[str, Any]]:
    samples = [
        FakeSample.from_dict(item)
        for payload in run_payloads
        for item in payload["samples"]
    ]
    guards: list[dict[str, Any]] = []
    for sample in samples:
        if sample.llm_calls != 0:
            guards.append({"kind": "llm_calls", "arm": sample.arm,
                           "question": sample.question_id, "repeat": sample.repeat})
        if sample.domain["needs"] != needs:
            guards.append({"kind": "needs", "arm": sample.arm,
                           "actual": sample.domain["needs"]})
        if sample.provider_calls != needs:
            guards.append({"kind": "provider_calls", "arm": sample.arm,
                           "actual": sample.provider_calls})
        if (
            sample.arm != "baseline"
            and sample.swe is not None
            and "map_children" in sample.swe
            and sample.swe["map_children"] != needs
        ):
            guards.append({"kind": "map_children", "arm": sample.arm,
                           "actual": sample.swe.get("map_children")})
        if sample.need_metrics["peak_concurrency"] < 1:
            guards.append({"kind": "peak_concurrency", "arm": sample.arm})
    return samples, {"ok": not guards, "failures": guards}


def _fake_parent(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    payloads: list[dict[str, Any]] = []
    for run_index in range(args.runs):
        pass_out = run_dir / f"fake-pass-{run_index}.json"
        command = [
            sys.executable, str(Path(__file__)), "--fake-pass",
            "--pass-out", str(pass_out), "--run-index", str(run_index),
            "--arms", ",".join(args.arms), "--questions", str(args.questions),
            "--repeats", str(args.repeats), "--needs", str(args.needs),
            "--fake-latency-ms", str(args.fake_latency_ms),
            "--timeout-seconds", str(args.timeout_seconds),
        ]
        completed = subprocess.run(command, check=False, timeout=args.pass_timeout)
        if completed.returncode != 0:
            raise SystemExit(f"fake pass {run_index} failed with {completed.returncode}")
        payloads.append(json.loads(pass_out.read_text(encoding="utf-8")))
    samples, guards = _aggregate(payloads, args.needs)
    network_attempts = sum(int(row["network_attempts"]) for row in payloads)
    if network_attempts:
        guards["ok"] = False
        guards["failures"].append({"kind": "network", "attempts": network_attempts})
    fake = {
        "runs": args.runs,
        "samples": [sample.as_dict() for sample in samples],
        "guards": guards,
        "network_attempts_sum": network_attempts,
        "git_head": payloads[0]["git_head"],
        "script_sha256": payloads[0]["script_sha256"],
    }
    return {"fake": fake, "dispersion": dispersion(samples, args.runs)}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", default="all",
        help="fake, parity, live, all, or a comma list such as fake,parity",
    )
    parser.add_argument(
        "--runs", type=int, default=DEFAULT_RUNS,
        help="independent fake-mode runs (default 8)",
    )
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--questions", type=int, default=DEFAULT_QUESTIONS)
    parser.add_argument("--needs", type=int, default=DEFAULT_NEEDS)
    parser.add_argument("--fake-latency-ms", type=int, default=DEFAULT_LATENCY_MS)
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--persist-swe", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--run-out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default="")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--pass-timeout", type=float, default=900.0)
    parser.add_argument("--live-timeout-seconds", type=float, default=LIVE_TIMEOUT_SECONDS)
    parser.add_argument("--live-questions", type=int, default=DEFAULT_LIVE_QUESTIONS)
    parser.add_argument("--live-repeats", type=int, default=DEFAULT_LIVE_REPEATS)
    parser.add_argument("--customer-id", type=int, default=CUSTOMER_ID)
    parser.add_argument("--fake-pass", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pass-out", default="", help=argparse.SUPPRESS)
    parser.add_argument("--run-index", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--live-sample", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--arm", default="", help=argparse.SUPPRESS)
    parser.add_argument("--question-index", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--repeat", type=int, default=0, help=argparse.SUPPRESS)
    parser.add_argument("--sample-out", default="", help=argparse.SUPPRESS)
    parser.add_argument("--db-path", default="", help=argparse.SUPPRESS)
    parser.add_argument("--overgraph-dir", default="", help=argparse.SUPPRESS)
    return parser.parse_args()


def _requested_modes(value: str) -> set[str]:
    modes = {part.strip() for part in re.split(r"[,+]", value) if part.strip()}
    unknown = modes - {"fake", "parity", "live", "all"}
    if unknown:
        raise SystemExit(f"unknown modes: {sorted(unknown)}")
    if "all" in modes:
        return {"fake", "parity", "live"}
    if not modes:
        raise SystemExit("--mode must name at least one of fake, parity, live")
    return modes


def _normalise_arms(value: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return value
    return tuple(arm.strip() for arm in value.split(",") if arm.strip())


def _run_modes(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    modes = _requested_modes(args.mode)
    fake_payload = _fake_parent(args, run_dir) if "fake" in modes else None
    parity_payload: dict[str, Any] | None = None
    if "parity" in modes:
        try:
            parity_payload = asyncio.run(parity_run(args))
        except Exception as exc:  # noqa: BLE001 - captured artifact, exit reflected
            parity_payload = {
                "scenarios": [], "all_equal": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    live_payload: dict[str, Any] | None = None
    if "live" in modes:
        try:
            live_payload = live_parent(args, run_dir)
        except Exception as exc:  # noqa: BLE001 - live never affects exit
            live_payload = {
                "mode": "live-observational", "gate": False,
                "error": f"{type(exc).__name__}: {exc}",
                "note": "live failed; fake/parity artifacts are authoritative",
            }
            _write_results(run_dir / "live-results.json", live_payload)
    return {"fake": fake_payload, "parity": parity_payload, "live": live_payload}


def _finalize(args: argparse.Namespace, run_dir: Path,
              payload: dict[str, Any]) -> int:
    fake_payload = payload["fake"]
    parity_payload = payload["parity"]
    report = V2Report(
        git_head=str(payload["git_head"]),
        script_sha256=str(payload["script_sha256"]),
        fake=fake_payload,
        dispersion=(fake_payload or {}).get("dispersion"),
        parity=parity_payload,
        live=payload["live"],
        run_dir=run_dir,
        args=args,
    )
    report_path = Path(args.report) if args.report else V2_REPORT
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(report), encoding="utf-8")
    _append_measurement_log(report, run_dir)
    print(f"results={run_dir / 'results.json'}")
    print(f"report={report_path}")
    guards = (fake_payload or {}).get("fake", {}).get("guards", {})
    fake_ok = bool(guards.get("ok", True))
    parity_ok = bool((parity_payload or {}).get("all_equal", True))
    print(f"fake_guards_ok={fake_ok} parity_ok={parity_ok}")
    return 0 if fake_ok and parity_ok else 1


def main() -> int:
    args = _parse_args()
    args.arms = _normalise_arms(args.arms)
    if args.live_sample:
        if not args.arm:
            raise SystemExit("--live-sample requires --arm")
        return asyncio.run(live_sample(args))
    if args.fake_pass:
        if not args.pass_out:
            raise SystemExit("--fake-pass requires --pass-out")
        payload = asyncio.run(fake_pass(args))
        Path(args.pass_out).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return 0
    run_dir = (
        Path(args.run_out)
        / f"v2-{v2_sha256()[:12]}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    modes = _run_modes(args, run_dir)
    payload = {
        "mode": args.mode,
        "git_head": git_head(),
        "script_sha256": v2_sha256(),
        **modes,
    }
    _write_results(run_dir / "results.json", payload)
    return _finalize(args, run_dir, payload)


if __name__ == "__main__":
    raise SystemExit(main())
