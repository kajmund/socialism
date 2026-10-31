"""Research loop experiment: baseline wave loop vs the SWE bridge variants.

Fake mode (default) is deterministic and offline: fake research source with a
fixed per-need latency, fake embeddings, programmatic assessor/completeness.
It measures orchestration and knowledge reuse, never research quality.

Measurement contract (frozen before the final runs):

* three independent child processes ("runs"), each with n interleaved repeats per
  arm, one at a time, arms rotated;
* parallel fixture: 16 needs, 40 ms fake latency per need. Arm A keeps today's
  ``research_need_concurrency`` (default 8 -> two waves); arm B doubles it
  (capped at 16 -> one wave). Domain parity is expected to stay exact;
* reuse fixture: objective + one child need, cold and warm, to exercise exact
  saved-answer reuse (``research.result.reused``);
* hard gates: exact domain parity across arms, fake guards (zero LLM calls,
  expected needs/provider calls/map children, no network attempt, no timeout),
  and performance gates (upper 95% CI of the per-run median ratio arm/baseline
  <= 1.10 and nearest-rank p95 of paired ratios <= 1.25).

Cutover-safe winner is arm A (same concurrency as today) when the gates pass.
Arm B is the fastest arm; its gain is concurrency (8 -> 16), not workflow shape,
and needs live rate-limit validation before it is used as a config change. It is
never the cutover recommendation.

`--strict` exits 1 when the cutover gates fail. `--live` is an observational,
non-deterministic arm loop (no gates) for the same three arms.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.llm import LLMCallStats, bind_usage_recorder, reset_usage_recorder
from app.services.execution import (
    get_attempt,
    get_evidence_set,
    list_evidence_items,
    list_evidence_quality,
    list_research_assessments,
    list_research_completeness_passes,
    list_runtime_needs,
)
from app.services.overgraph.workflows import WorkflowRunStore
from app.services.research import swe_bridge
from app.services.research.execution import execute_attempt_research
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.planner import (
    FakeResearchPlanner,
    ResearchNeedDraft,
    ResearchObjective,
)
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.registry import ResearchSourceRegistry
from app.services.research.result_execution import REUSE_KEY
from app.services.research.router import ResearchRouter
from app.services.swe_host import WorkflowHostContext
from scripts.benchmark_research_loop import (
    CUSTOMER_ID,
    OwnerBinding,
    _install_fake_embeddings,
    _new_attempt,
    _open_database,
    _open_runtime,
    close_owner_binding,
    open_owner_for_runtime,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_FILE = REPO_ROOT / "docs" / "guides" / "research-36-eval.json"
DEFAULT_OUT = REPO_ROOT / "data" / "research_swe"
REPORT_FILE = REPO_ROOT / "docs" / "guides" / "research-swe-experiment.md"
ARMS = ("baseline", "swe_a", "swe_b")
ARM_LABELS = {
    "baseline": "baseline (phase-2 wave loop)",
    "swe_a": "SWE arm A (same concurrency)",
    "swe_b": "SWE arm B (wider fan-out)",
}
FAKE_SOURCE_TYPE = "case_knowledge"
DEFAULT_NEEDS = 16
DEFAULT_LATENCY_MS = 40
DEFAULT_RUNS = 3
DEFAULT_REPEATS = 6
DEFAULT_QUESTIONS = 2
DEFAULT_TIMEOUT_SECONDS = 120.0
T_CRITICAL_975 = {2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365}


# ---------------------------------------------------------------- fixtures


def load_eval_questions(limit: int) -> list[dict[str, Any]]:
    payload = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    questions = payload["topics"]["questions"]
    facit = payload["topics"]["assessment"]["needs"]
    return [
        {
            "id": question_id,
            "question": text,
            "facit_sufficient": facit.get(question_id),
        }
        for question_id, text in list(questions.items())[:limit]
    ]


def _swe_concurrency(arm: str) -> int:
    base = int(settings.research_need_concurrency)
    if arm == "swe_b":
        return min(
            base * swe_bridge.PARALLEL_FANOUT_FACTOR,
            swe_bridge.PARALLEL_FANOUT_CAP,
        )
    return base


def parallel_plan(question: Mapping[str, Any], needs: int) -> ResearchPlan:
    """N provider-backed needs without a main lookup; provider calls are exact."""
    return ResearchPlan(
        needs=[
            ResearchNeed(
                id=f"research_{index + 1}",
                question=f"{question['question']} – del {index + 1}",
                why_needed=f"parallel fixture need {index + 1}",
                requested_by=["experiment"],
                source_types=[FAKE_SOURCE_TYPE],
            )
            for index in range(needs)
        ]
    )


def reuse_planner(question: str) -> FakeResearchPlanner:
    return FakeResearchPlanner(
        [
            ResearchNeedDraft(
                question=f"{question} – underfråga",
                why_needed="reuse fixture child need",
                source_types=[FAKE_SOURCE_TYPE],
            )
        ]
    )


class LatencySource:
    """Deterministic research source with a fixed per-call latency."""

    provider_id = "benchmark-fake"

    def __init__(self, source_type: str, latency_ms: int) -> None:
        self.source_type = source_type
        self.latency_s = latency_ms / 1000.0
        self.calls = 0

    async def research(self, need: Any, _context: Any) -> list[Any]:
        from app.services.research.models import research_evidence

        self.calls += 1
        await asyncio.sleep(self.latency_s)
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


class SocketGuard:
    """Block and count every outbound socket connect attempt."""

    def __init__(self) -> None:
        self.attempts = 0
        self._original_connect = socket.socket.connect
        self._original_connect_ex = socket.socket.connect_ex
        self._original_create = socket.create_connection

    def __enter__(self) -> SocketGuard:
        def forbidden(*_args: Any, **_kwargs: Any) -> Any:
            self.attempts += 1
            raise RuntimeError("network access is forbidden in fake mode")

        socket.socket.connect = forbidden  # type: ignore[method-assign]
        socket.socket.connect_ex = forbidden  # type: ignore[method-assign]
        socket.create_connection = forbidden  # type: ignore[assignment]
        return self

    def __exit__(self, *_exc: object) -> None:
        socket.socket.connect = self._original_connect  # type: ignore[method-assign]
        socket.socket.connect_ex = self._original_connect_ex  # type: ignore[method-assign]
        socket.create_connection = self._original_create  # type: ignore[assignment]


# ---------------------------------------------------------------- metrics


@dataclass
class Sample:
    run_index: int
    arm: str
    fixture: str
    question_id: str
    repeat: int
    phase: str
    wall_ms: float
    cpu_ms: float
    status: str
    stop_reason: str | None
    wave: int
    needs: int
    found: int
    not_found: int
    errors: int
    evidence: list[tuple[str, str, str, str, str]]
    assessments: list[tuple[int, str]]
    completeness: list[tuple[int, str]]
    quality_rows: int
    provider_calls: int
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    reused_answer_id: str | None
    reuse_match: str | None
    swe_steps_used: int | None
    swe_events: int | None
    swe_map_children: int | None
    swe_sha: str | None
    swe_concurrency: int | None
    timed_out: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_index": self.run_index, "arm": self.arm, "fixture": self.fixture,
            "question_id": self.question_id, "repeat": self.repeat,
            "phase": self.phase, "wall_ms": round(self.wall_ms, 3),
            "cpu_ms": round(self.cpu_ms, 3), "status": self.status,
            "stop_reason": self.stop_reason, "wave": self.wave,
            "needs": self.needs, "found": self.found,
            "not_found": self.not_found, "errors": self.errors,
            "evidence": [list(item) for item in self.evidence],
            "assessments": [list(item) for item in self.assessments],
            "completeness": [list(item) for item in self.completeness],
            "quality_rows": self.quality_rows,
            "provider_calls": self.provider_calls,
            "llm_calls": self.llm_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "reused_answer_id": self.reused_answer_id,
            "reuse_match": self.reuse_match,
            "swe_steps_used": self.swe_steps_used,
            "swe_events": self.swe_events,
            "swe_map_children": self.swe_map_children,
            "swe_sha": self.swe_sha,
            "swe_concurrency": self.swe_concurrency,
            "timed_out": self.timed_out,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> Sample:
        return cls(
            run_index=int(raw["run_index"]), arm=str(raw["arm"]),
            fixture=str(raw["fixture"]), question_id=str(raw["question_id"]),
            repeat=int(raw["repeat"]), phase=str(raw["phase"]),
            wall_ms=float(raw["wall_ms"]), cpu_ms=float(raw["cpu_ms"]),
            status=str(raw["status"]), stop_reason=raw["stop_reason"],
            wave=int(raw["wave"]), needs=int(raw["needs"]),
            found=int(raw["found"]), not_found=int(raw["not_found"]),
            errors=int(raw["errors"]),
            evidence=[tuple(item) for item in raw["evidence"]],
            assessments=[tuple(item) for item in raw["assessments"]],
            completeness=[tuple(item) for item in raw["completeness"]],
            quality_rows=int(raw["quality_rows"]),
            provider_calls=int(raw["provider_calls"]),
            llm_calls=int(raw["llm_calls"]),
            prompt_tokens=int(raw["prompt_tokens"]),
            completion_tokens=int(raw["completion_tokens"]),
            reused_answer_id=raw["reused_answer_id"],
            reuse_match=raw["reuse_match"],
            swe_steps_used=raw["swe_steps_used"],
            swe_events=raw["swe_events"],
            swe_map_children=raw["swe_map_children"],
            swe_sha=raw["swe_sha"],
            swe_concurrency=raw["swe_concurrency"],
            timed_out=bool(raw["timed_out"]),
        )

    def domain_key(self) -> tuple[Any, ...]:
        return (
            self.status, self.stop_reason, self.wave, self.needs, self.found,
            self.not_found, self.errors, tuple(self.evidence),
            tuple(self.assessments), tuple(self.completeness),
            self.quality_rows, self.provider_calls,
        )

    def perf_key(self) -> tuple[str, str, int, int, str]:
        return (self.fixture, self.question_id, self.run_index, self.repeat, self.phase)


@dataclass(frozen=True)
class Env:
    engine: Any
    factory: async_sessionmaker[AsyncSession]
    router: ResearchRouter
    source: LatencySource
    run_store: WorkflowRunStore | None
    llm_calls: list[LLMCallStats]
    owner_binding: OwnerBinding


@dataclass
class PassReport:
    run_index: int
    git_head: str
    script_sha256: str
    arms: list[str]
    repeats: int
    questions: int
    needs: int
    latency_ms: int
    persist_swe: bool
    concurrency_a: int
    concurrency_b: int
    samples: list[dict[str, Any]]
    network_attempts: int
    warmup: dict[str, Any] = field(default_factory=dict)
    started_at: str = ""


# ---------------------------------------------------------------- execution


def _swe_loop_impl(arm: str, store: WorkflowRunStore | None, recorded: dict[str, Any]):
    async def impl(**kwargs: object) -> None:
        concurrency = _swe_concurrency(arm)
        loop, snapshot_plan = swe_bridge.build_loop(
            dict(kwargs), concurrency=concurrency, run_store=store,
        )
        result = await loop.run(snapshot_plan=snapshot_plan)
        counts = Counter(event["type"] for event in result.events)
        # steps_used: every scheduled node plus every join/map-join satisfaction
        # (schedule.rs consume_step, complete.rs satisfy_join/finish_map). The
        # fixture has no joins, so it equals NodeScheduled here.
        recorded.update(
            {
                "status": result.status,
                "concurrency": concurrency,
                "sha256": swe_bridge._workflow(concurrency).sha256,
                "events": len(result.events),
                "steps_used": counts["NodeScheduled"] + counts["JoinSatisfied"],
                "map_children": counts["BranchSpawned"],
                "error": result.error,
            }
        )
        if result.status != "completed":
            from app.services.research.execution import ResearchExecutionError

            raise ResearchExecutionError(
                f"SWE research loop ended status={result.status}: {result.error}"
            )

    return impl


async def _execute(
    env: Env,
    arm: str,
    attempt_id: str,
    *,
    plan: ResearchPlan | None,
    objective: ResearchObjective | None,
    recorded: dict[str, Any],
) -> Any:
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
        kwargs["research_planner"] = reuse_planner(objective.objective)
    async with env.factory() as session:
        if arm == "baseline":
            return await execute_attempt_research(session, **kwargs)
        impl = _swe_loop_impl(arm, env.run_store, recorded)
        with mock.patch("app.services.research.execution._run_research_loop", impl):
            return await execute_attempt_research(session, **kwargs)


async def _signals(
    factory: async_sessionmaker[AsyncSession], attempt_id: str, result: Any,
) -> dict[str, Any]:
    async with factory() as session:
        attempt = await get_attempt(session, attempt_id)
        needs = await list_runtime_needs(session, attempt_id)
        assessments = await list_research_assessments(session, attempt_id)
        completeness = await list_research_completeness_passes(session, attempt_id)
        evidence_set = (
            await get_evidence_set(session, result.evidence_set_id)
            if result.evidence_set_id is not None
            else None
        )
        items = (
            await list_evidence_items(session, result.evidence_set_id)
            if result.evidence_set_id is not None
            else []
        )
        quality = (
            await list_evidence_quality(session, evidence_set.id)
            if evidence_set is not None
            else []
        )
    return {
        "attempt": attempt,
        "needs": len(needs),
        "assessments": [(row.assessment_pass, row.result) for row in assessments],
        "completeness": [(row.completeness_pass, row.result) for row in completeness],
        "quality_rows": len(quality),
        "evidence": sorted(
            (
                str(item.research_need_id or ""), str(item.source_type),
                str(item.status), str(item.provider),
                str(item.original_evidence_id or item.id),
            )
            for item in items
        ),
    }


@dataclass(frozen=True)
class SampleSpec:
    run_index: int
    arm: str
    fixture: str
    question: Mapping[str, Any]
    repeat: int
    phase: str
    plan: ResearchPlan | None = None
    objective: ResearchObjective | None = None


async def _sample(*, spec: SampleSpec, env: Env, timeout_seconds: float) -> Sample:
    question = spec.question
    attempt_id = await _new_attempt(env.factory, question["question"])
    provider_before = env.source.calls
    llm_before = len(env.llm_calls)
    recorded: dict[str, Any] = {}
    cpu_started = time.process_time()
    started = time.perf_counter()
    timed_out = False
    result: Any = None
    try:
        result = await asyncio.wait_for(
            _execute(env, spec.arm, attempt_id, plan=spec.plan,
                     objective=spec.objective, recorded=recorded),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        timed_out = True
    wall_ms = (time.perf_counter() - started) * 1000
    cpu_ms = (time.process_time() - cpu_started) * 1000
    new_calls = env.llm_calls[llm_before:]
    common = dict(
        run_index=spec.run_index, arm=spec.arm, fixture=spec.fixture,
        question_id=question["id"], repeat=spec.repeat, phase=spec.phase,
        wall_ms=wall_ms, cpu_ms=cpu_ms,
        provider_calls=env.source.calls - provider_before,
        llm_calls=len(new_calls),
        prompt_tokens=sum(call.prompt_tokens for call in new_calls),
        completion_tokens=sum(call.completion_tokens for call in new_calls),
    )
    if result is None:
        return Sample(
            **common, status="timeout", stop_reason=None, wave=0, needs=0,
            found=0, not_found=0, errors=0, evidence=[], assessments=[],
            completeness=[], quality_rows=0, reused_answer_id=None,
            reuse_match=None, swe_steps_used=None, swe_events=None,
            swe_map_children=None, swe_sha=None, swe_concurrency=None,
            timed_out=True,
        )
    signals = await _signals(env.factory, attempt_id, result)
    reuse = signals["attempt"].input_snapshot.get(REUSE_KEY) or {}
    return Sample(
        **common,
        status=result.status,
        stop_reason=signals["attempt"].research_stop_reason,
        wave=signals["attempt"].research_wave,
        needs=signals["needs"], found=result.found_count,
        not_found=result.not_found_count, errors=result.error_count,
        evidence=signals["evidence"], assessments=signals["assessments"],
        completeness=signals["completeness"], quality_rows=signals["quality_rows"],
        reused_answer_id=reuse.get("answer_fact_id"),
        reuse_match=reuse.get("match"),
        swe_steps_used=recorded.get("steps_used") if recorded else None,
        swe_events=recorded.get("events") if recorded else None,
        swe_map_children=recorded.get("map_children") if recorded else None,
        swe_sha=recorded.get("sha256") if recorded else None,
        swe_concurrency=recorded.get("concurrency") if recorded else None,
        timed_out=timed_out,
    )


async def _open_env(
    *, arm: str, work_root: Path, latency_ms: int, persist_swe: bool,
    llm_calls: list[LLMCallStats], tag: str,
) -> Env:
    env_root = work_root / tag
    env_root.mkdir(parents=True, exist_ok=True)
    runtime = _open_runtime(env_root / "overgraph")
    owner_binding = await open_owner_for_runtime(runtime)
    engine, factory = await _open_database(env_root / "research.sqlite")
    source = LatencySource(FAKE_SOURCE_TYPE, latency_ms)
    registry = ResearchSourceRegistry()
    registry.register(source)
    run_store = (
        WorkflowRunStore.open(
            env_root / "swe",
            WorkflowHostContext(customer_id=str(CUSTOMER_ID), feature_id="research"),
        )
        if arm != "baseline" and persist_swe
        else None
    )
    return Env(
        engine=engine, factory=factory, router=ResearchRouter(registry),
        source=source, run_store=run_store, llm_calls=llm_calls,
        owner_binding=owner_binding,
    )


async def _close_env(env: Env) -> None:
    if env.run_store is not None:
        env.run_store.close()
    await close_owner_binding(env.owner_binding)
    from app.services.overgraph.catalogs import set_runtime

    set_runtime(None)
    await env.engine.dispose()


# ------------------------------------------------- single independent pass


async def _warmup(args: argparse.Namespace, questions: list[dict[str, Any]],
                  work_root: Path, llm_calls: list[LLMCallStats]) -> dict[str, Any]:
    warmup: dict[str, Any] = {}
    for arm in args.arms:
        env = await _open_env(
            arm=arm, work_root=work_root, latency_ms=args.fake_latency_ms,
            persist_swe=args.persist_swe, llm_calls=llm_calls,
            tag=f"warmup-{arm}",
        )
        try:
            warmup[arm] = (
                await _sample(
                    spec=SampleSpec(
                        run_index=args.run_index, arm=arm, fixture="warmup",
                        question=questions[0], repeat=-1, phase="cold",
                        plan=parallel_plan(questions[0], 1),
                    ),
                    env=env, timeout_seconds=args.timeout_seconds,
                )
            ).wall_ms
        finally:
            await _close_env(env)
    return warmup


async def _parallel_samples(args: argparse.Namespace, questions: list[dict[str, Any]],
                            work_root: Path, llm_calls: list[LLMCallStats]) -> list[Sample]:
    samples: list[Sample] = []
    for repeat in range(args.repeats):
        for question in questions:
            for arm in _rotated_arms(args.arms, repeat + len(question["id"])):
                env = await _open_env(
                    arm=arm, work_root=work_root, latency_ms=args.fake_latency_ms,
                    persist_swe=args.persist_swe, llm_calls=llm_calls,
                    tag=f"parallel-{arm}-{question['id']}-{repeat}",
                )
                try:
                    samples.append(
                        await _sample(
                            spec=SampleSpec(
                                run_index=args.run_index, arm=arm,
                                fixture="parallel", question=question,
                                repeat=repeat, phase="cold",
                                plan=parallel_plan(question, args.needs),
                            ),
                            env=env, timeout_seconds=args.timeout_seconds,
                        )
                    )
                finally:
                    await _close_env(env)
    return samples


async def _reuse_samples(args: argparse.Namespace, question: Mapping[str, Any],
                         work_root: Path, llm_calls: list[LLMCallStats]) -> list[Sample]:
    samples: list[Sample] = []
    for arm in args.arms:
        env = await _open_env(
            arm=arm, work_root=work_root, latency_ms=args.fake_latency_ms,
            persist_swe=args.persist_swe, llm_calls=llm_calls,
            tag=f"reuse-{arm}",
        )
        try:
            for phase in ("cold", "warm"):
                samples.append(
                    await _sample(
                        spec=SampleSpec(
                            run_index=args.run_index, arm=arm, fixture="reuse",
                            question=question, repeat=0, phase=phase,
                            objective=ResearchObjective(question["question"]),
                        ),
                        env=env, timeout_seconds=args.timeout_seconds,
                    )
                )
        finally:
            await _close_env(env)
    return samples


async def run_single_pass(args: argparse.Namespace) -> PassReport:
    questions = load_eval_questions(args.questions)
    work_root = Path(tempfile.mkdtemp(prefix="research-swe-pass-"))
    llm_calls: list[LLMCallStats] = []
    original_embeddings = _install_fake_embeddings()
    token = bind_usage_recorder(llm_calls.append)
    samples: list[Sample] = []
    with SocketGuard() as guard:
        try:
            warmup = await _warmup(args, questions, work_root, llm_calls)
            samples.extend(
                await _parallel_samples(args, questions, work_root, llm_calls)
            )
            samples.extend(
                await _reuse_samples(args, questions[0], work_root, llm_calls)
            )
        finally:
            reset_usage_recorder(token)
            import app.services.research.composition as composition

            composition.research_embeddings = original_embeddings
            if not args.keep:
                shutil.rmtree(work_root, ignore_errors=True)
    return PassReport(
        run_index=args.run_index,
        git_head=git_head(),
        script_sha256=script_sha256(),
        arms=list(args.arms),
        repeats=args.repeats,
        questions=args.questions,
        needs=args.needs,
        latency_ms=args.fake_latency_ms,
        persist_swe=args.persist_swe,
        concurrency_a=int(settings.research_need_concurrency),
        concurrency_b=_swe_concurrency("swe_b"),
        samples=[sample.as_dict() for sample in samples],
        network_attempts=guard.attempts,
        warmup=warmup,
        started_at=datetime.now(UTC).isoformat(),
    )


def _rotated_arms(arms: tuple[str, ...] | list[str], offset: int) -> list[str]:
    ordered = list(arms)
    shift = offset % len(ordered)
    return ordered[shift:] + ordered[:shift]


def git_head() -> str:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def script_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# ---------------------------------------------------------------- gates


def _ci_upper(values: list[float]) -> float:
    if len(values) < 2:
        return values[0] if values else 0.0
    critical = T_CRITICAL_975.get(len(values) - 1, 1.96)
    return statistics.fmean(values) + critical * statistics.stdev(values) / math.sqrt(
        len(values)
    )


def _p95_nearest_rank(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _expected(fixture: str, phase: str, needs: int) -> tuple[int, int]:
    if fixture == "parallel":
        return needs, needs
    if fixture == "reuse" and phase == "cold":
        return 2, 1
    if fixture == "reuse" and phase == "warm":
        return 1, 0
    return -1, -1


def _sample_guards(sample: Sample, needs: int) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    expected_needs, expected_calls = _expected(sample.fixture, sample.phase, needs)
    if sample.timed_out:
        failures.append({"kind": "timeout", "key": list(sample.perf_key())})
    if sample.llm_calls != 0:
        failures.append({"kind": "llm_calls", "key": list(sample.perf_key())})
    if sample.needs != expected_needs:
        failures.append({"kind": "needs", "key": list(sample.perf_key()),
                         "expected": expected_needs, "actual": sample.needs})
    if sample.provider_calls != expected_calls:
        failures.append({"kind": "provider_calls", "key": list(sample.perf_key()),
                         "expected": expected_calls, "actual": sample.provider_calls})
    if (
        sample.fixture == "parallel"
        and sample.phase == "cold"
        and sample.arm != "baseline"
        and sample.swe_map_children != needs
    ):
        failures.append({"kind": "map_children", "key": list(sample.perf_key()),
                         "expected": needs, "actual": sample.swe_map_children})
    if sample.fixture == "reuse" and sample.phase == "warm":
        if sample.reused_answer_id is None or sample.reuse_match != "exact":
            failures.append({"kind": "reuse", "key": list(sample.perf_key())})
    return failures


def _performance(samples: list[Sample]) -> dict[str, Any]:
    samples = [
        row for row in samples if row.fixture == "parallel" and row.phase == "cold"
    ]
    runs = sorted({row.run_index for row in samples})
    by_key = {
        (row.run_index, row.question_id, row.repeat): row.wall_ms
        for row in samples
        if row.arm == "baseline"
    }
    baseline_median_by_run = {
        run_index: _median(
            [row.wall_ms for row in samples
             if row.arm == "baseline" and row.run_index == run_index]
        )
        for run_index in runs
    }
    out: dict[str, Any] = {
        "baseline": {
            "median_ms": round(_median(
                [row.wall_ms for row in samples if row.arm == "baseline"]
            ), 3),
            "median_ratio": 1.0, "ci_upper_median_ratio": 1.0,
            "p95_paired_ratio": 1.0,
            "median_gate_ok": True, "p95_gate_ok": True, "trivial": True,
        }
    }
    for arm in ("swe_a", "swe_b"):
        per_run: list[float] = []
        paired: list[float] = []
        for run_index in runs:
            values = [row.wall_ms for row in samples
                      if row.arm == arm and row.run_index == run_index]
            baseline_median = baseline_median_by_run[run_index]
            if values and baseline_median:
                per_run.append(_median(values) / baseline_median)
            for row in samples:
                if row.arm != arm or row.run_index != run_index:
                    continue
                baseline = by_key.get((run_index, row.question_id, row.repeat))
                if baseline:
                    paired.append(row.wall_ms / baseline)
        ci_upper = _ci_upper(per_run) if per_run else float("inf")
        p95 = _p95_nearest_rank(paired)
        out[arm] = {
            "median_ms": round(_median([row.wall_ms for row in samples if row.arm == arm]), 3),
            "median_ratio": round(_median(per_run), 4) if per_run else None,
            "ci_upper_median_ratio": round(ci_upper, 4),
            "p95_paired_ratio": round(p95, 4),
            "median_gate_ok": ci_upper <= 1.10,
            "p95_gate_ok": p95 <= 1.25,
        }
    return out


def evaluate(
    samples: list[Sample],
    *,
    needs: int,
    arms: list[str],
    network_attempts: int = 0,
) -> dict[str, Any]:
    guards: list[dict[str, Any]] = []
    if network_attempts:
        guards.append({"kind": "network", "attempts": network_attempts})
    for sample in samples:
        guards.extend(_sample_guards(sample, needs))
    parallel = [row for row in samples if row.fixture == "parallel"]
    baseline_by_key = {
        row.perf_key(): row for row in parallel if row.arm == "baseline"
    }
    parity: list[dict[str, Any]] = []
    for sample in parallel:
        if sample.arm == "baseline":
            continue
        baseline = baseline_by_key.get(sample.perf_key())
        if baseline is not None and sample.domain_key() != baseline.domain_key():
            parity.append({"key": list(sample.perf_key())})
    performance = _performance(samples)
    cutover_gates = (
        not parity and not guards
        and performance["baseline"]["median_gate_ok"]
        and performance["swe_a"]["median_gate_ok"]
        and performance["swe_a"]["p95_gate_ok"]
    )
    fastest_ok = (
        performance["swe_b"]["median_gate_ok"] and performance["swe_b"]["p95_gate_ok"]
    )
    return {
        "domain_parity_ok": not parity,
        "parity_mismatches": parity,
        "guards_ok": not guards,
        "guard_failures": guards,
        "performance": performance,
        "cutover_gate_ok": cutover_gates,
        "fastest_gate_ok": fastest_ok,
        "all_gates_ok": cutover_gates and fastest_ok,
    }


def _winner(gates: Mapping[str, Any]) -> dict[str, Any]:
    cutover = "swe_a" if gates["cutover_gate_ok"] else None
    fastest = "swe_b" if gates["fastest_gate_ok"] else None
    return {
        "cutover_safe_winner": cutover,
        "fastest_arm": fastest,
        "note": (
            "Cutover-safe winner is arm A (same concurrency as today). Arm B is "
            "only the fastest arm: its gain is concurrency 8 -> 16, to be "
            "validated live and shipped as a config follow-up, never as the "
            "cutover choice."
        ),
    }


# ---------------------------------------------------------------- report


@dataclass(frozen=True)
class ReportData:
    passes: list[PassReport]
    samples: list[Sample]
    gates: Mapping[str, Any]
    winners: Mapping[str, Any]
    question_rows: list[dict[str, Any]]
    run_dir: Path | None
    args: argparse.Namespace
    reproduce: str
    live: Mapping[str, Any] | None = None


def render_report(data: ReportData) -> str:
    passes, gates = data.passes, data.gates
    performance = gates["performance"]
    status = (
        "CUTOVER GATES PASSED — arm A is the cutover-safe winner"
        if gates["cutover_gate_ok"]
        else "NO APPROVED VARIANT — a cutover gate failed"
    )
    winner_text = (
        f"**Cutover-safe winner: {ARM_LABELS['swe_a']}** — same concurrency and "
        "loop shape as today; this is the parity-PR variant.\n\n"
        f"**Fastest: {ARM_LABELS['swe_b']}** — the gain is concurrency 8 -> 16, "
        "not workflow shape. Ship it as a separate config follow-up "
        "(`research_need_concurrency` 8 -> 16) after live rate-limit validation. "
        "Do not use it as the cutover choice."
        if gates["cutover_gate_ok"] and gates["fastest_gate_ok"]
        else (
            "**Cutover-safe winner: arm A**; arm B did not pass its speed gate, so "
            "no speed recommendation is made."
            if gates["cutover_gate_ok"]
            else "**No winner.** Cutover must be discussed with the Lead before any "
            "variant is approved."
        )
    )
    table = _performance_table(performance)
    reproduce = data.reproduce
    samples_per_arm = len(
        [
            row
            for row in data.samples
            if row.fixture == "parallel" and row.phase == "cold" and row.arm == "swe_a"
        ]
    )
    expected_result = (
        "exit 0, `status=gates_passed`"
        if gates["cutover_gate_ok"]
        else "exit 1, `status=no_approved_variant` (with `--strict`)"
    )
    metadata = (
        f"- git HEAD: `{passes[0].git_head}`\n"
        f"- script sha256: `{passes[0].script_sha256}`\n"
        f"- independent runs: {len(passes)} (separate processes)\n"
        f"- repeats per run: {passes[0].repeats}\n"
        f"- eval questions: {passes[0].questions}\n"
        f"- parallel fixture: {passes[0].needs} needs, "
        f"{passes[0].latency_ms} ms fake latency per need\n"
        f"- concurrency: A={passes[0].concurrency_a} (two waves), "
        f"B={passes[0].concurrency_b} (one wave)\n"
        f"- persist-swe: {passes[0].persist_swe} "
        "(optional durability, not production-wired)\n"
        f"- fake mode: yes — 0 LLM calls enforced, no network, hard gates\n"
        f"- raw data: `{data.run_dir}`\n"
    )
    return f"""# Research SWE experiment

**{status}**

Generated by `backend/scripts/benchmark_research_swe.py` on
{datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}.

## Metadata

{metadata}

Expected result of this exact command on the frozen harness: **{expected_result}**,
with **{samples_per_arm} parallel-cold samples per arm** (3 arms) plus the warm
reuse samples. `--strict` exits 1 when a cutover gate fails.

Reproduce exactly:

```bash
{reproduce}
```

## Gates

| Gate | Result |
| --- | --- |
| Domain parity (exact, all arms, evidence + provider calls) | {"pass" if gates["domain_parity_ok"] else "FAIL"} |
| Fake guards (LLM calls, needs, provider calls, map children, reuse, network, timeout) | {"pass" if gates["guards_ok"] else "FAIL"} |
| Performance, arm A (CI95 median +10%, nearest-rank p95 paired +25%) | {"pass" if gates["cutover_gate_ok"] else "FAIL"} |
| Performance, arm B (same gates) | {"pass" if gates["fastest_gate_ok"] else "FAIL"} |

{table}

The baseline row is trivial by definition (ratio 1.0). The median gate uses the
upper 95% CI of the per-run median ratio across the independent runs; the
single-run gate uses the nearest-rank p95 of paired ratios, not the maximum.

{winner_text}

## Fixture and interpretation

- **Parallel fixture**: {passes[0].needs} needs per arm, each provider call has a
  deterministic {passes[0].latency_ms} ms fake latency (`asyncio.sleep`), so the
  need semaphore actually bounds waves. Arm A uses today's
  `research_need_concurrency` ({passes[0].concurrency_a}) -> two waves; arm B
  doubles it ({passes[0].concurrency_b}) -> one wave. Raw JSON records
  `swe_map_children == {passes[0].needs}` per cold SWE run.
- **Reuse fixture**: objective + one child need, cold then warm in the same
  environment. Cold expects 2 needs and exactly 1 provider call; warm expects 1
  need, 0 provider calls and an exact saved answer (`reused_answer_id` set).
- **Warmup**: each independent run performs one discarded cold run per arm for
  `questions[0]` only; it removes first-use import cost and is excluded from
  every metric.
- **Domain parity** compares status, stop_reason, wave, needs, evidence ids,
  assessments, completeness, quality rows and provider calls exactly across
  arms. Fake mode uses the same router, assessor and plan for every arm, so the
  expected result is exact equality; any mismatch fails the gate.
- **Quality parity is guaranteed by construction**: every arm executes the same
  domain code (planning, retrieval, persistence, quality, assessment,
  completeness); fake mode only swaps the wave loop. The measured quality
  columns are therefore structural, not a research-quality judgment.
- **Fake mode measures orchestration, not research quality.** No LLM is called
  (`llm_calls == 0` guard) and outbound sockets are blocked and counted. The
  quality columns are structural and identical by construction.

## Reuse

{_reuse_table(data.samples)}

## Live mode (observational, not a gate)

{_live_section(data)}

Live mode runs the same three arms through the same entry point and patching as
fake mode, with production router/planner/assessor/completeness. It is
non-deterministic and **cannot approve a workflow**; it records wall time,
LLM calls/tokens (from `app.llm.bind_usage_recorder`), domain signals and facit
context from `research-36-eval.json`. Set `--input-price-per-1m` and
`--output-price-per-1m` to print a cost estimate. It writes runs/attempts to the
configured database and fails loud when model/provider keys are missing.
"""


def _performance_table(performance: Mapping[str, Any]) -> str:
    rows = [
        "| Arm | Median (ms) | Median ratio | CI95 upper | p95 paired ratio | "
        "Median gate | p95 gate |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for arm, row in performance.items():
        rows.append(
            f"| {ARM_LABELS.get(arm, arm)} | {row['median_ms']} | {row['median_ratio']} | "
            f"{row['ci_upper_median_ratio']} | {row['p95_paired_ratio']} | "
            f"{'pass' if row['median_gate_ok'] else 'FAIL'} | "
            f"{'pass' if row['p95_gate_ok'] else 'FAIL'} |"
        )
    return "\n".join(rows)


def _reuse_table(samples: list[Sample]) -> str:
    rows = [
        "| Arm | Cold wall (ms) | Warm wall (ms) | Cold provider calls | Warm reuse |",
        "| --- | --- | --- | --- | --- |",
    ]
    for arm in ARMS:
        cold = [row for row in samples
                if row.arm == arm and row.fixture == "reuse" and row.phase == "cold"]
        warm = [row for row in samples
                if row.arm == arm and row.fixture == "reuse" and row.phase == "warm"]
        if not cold or not warm:
            continue
        rows.append(
            f"| {ARM_LABELS[arm]} | {_median([row.wall_ms for row in cold])} | "
            f"{_median([row.wall_ms for row in warm])} | "
            f"{_median([row.provider_calls for row in cold])} | "
            f"{sum(1 for row in warm if row.reused_answer_id)}/{len(warm)} |"
        )
    return "\n".join(rows)


def _live_section(data: ReportData) -> str:
    if not data.live:
        return (
            "Live layer not run for this report: **documented follow-up, not a gate.**\n\n"
            "Blockers found when the frozen harness attempted it (2026-10-21):\n\n"
            "- `app.services.research.composition.ResearchCompositionError: "
            "KnowledgeVectorStore is not configured; refusing to use an empty "
            "in-memory test store` — the script does not run the application "
            "lifespan/wiring, so the vector store and OverGraph runtime are not "
            "configured.\n"
            "- The dev SQLite database (`backend/data/opinionssimulator.db`) is at "
            "revision `105_enable_postgres_rls` and cannot be migrated to head: "
            "migration `111_raw_domain_claims` fails with "
            "`ValueError: dictionary update sequence element #0 has length 1; "
            "2 is required`.\n\n"
            "Live mode therefore requires (a) application lifecycle wiring of the "
            "vector store + OverGraph runtime, and (b) a database at head with "
            "prompt defaults. Until then live is observational only and "
            "**cannot approve a workflow**; the fake-mode gates above remain the "
            "approval basis.\n\n"
            "Command once the prerequisites exist:\n\n"
            "```bash\ncd backend && uv run python scripts/benchmark_research_swe.py "
            f"--live --db-path DB --customer-id {CUSTOMER_ID} --questions 2 --repeats 1\n```"
        )
    rows = data.live.get("rows", [])
    lines = [
        "**Observational, not gate.** The live layer ran "
        f"{len(rows)} arm/question combinations; it cannot approve a workflow.",
        "",
        "| Arm | Question | Wall (ms) | LLM calls | Prompt tokens | Completion tokens | "
        "Status | Stop reason | Needs | Facit sufficient |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('arm')} | {row.get('question_id')} | {row.get('wall_ms')} | "
            f"{row.get('llm_calls')} | {row.get('prompt_tokens')} | "
            f"{row.get('completion_tokens')} | {row.get('status')} | "
            f"{row.get('stop_reason')} | {row.get('needs')} | "
            f"{row.get('facit_sufficient')} |"
        )
    lines.append("")
    lines.append(
        f"Total LLM calls: {data.live.get('total_llm_calls')}; estimated cost units: "
        f"{data.live.get('estimated_cost_units')} (price flags as set)."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------- orchestration


def _reproduce_command(args: argparse.Namespace) -> str:
    """Exact measurement command, including --strict when it was used."""
    command = (
        "cd backend && uv run python scripts/benchmark_research_swe.py "
        f"--runs {args.runs} --repeats {args.repeats} "
        f"--questions {args.questions} --needs {args.needs} "
        f"--fake-latency-ms {args.fake_latency_ms} "
        f"--arms {','.join(ARMS)}"
    )
    if args.persist_swe:
        command += " --persist-swe"
    if args.keep:
        command += " --keep"
    if args.strict:
        command += " --strict"
    return command


def _write_json(
    out_dir: Path,
    *,
    passes: list[PassReport],
    samples: list[Sample],
    gates: Mapping[str, Any],
    winners: Mapping[str, Any],
    question_rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = out_dir / f"frozen-{passes[0].script_sha256[:12]}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "fake-gated-orchestration-measurement",
        "status": "gates_passed" if gates["cutover_gate_ok"] else "no_approved_variant",
        "git_head": passes[0].git_head,
        "script_sha256": passes[0].script_sha256,
        "arms": passes[0].arms,
        "runs": len(passes),
        "repeats": passes[0].repeats,
        "questions": question_rows,
        "needs": passes[0].needs,
        "fake_latency_ms": passes[0].latency_ms,
        "persist_swe": passes[0].persist_swe,
        "concurrency": {
            "a": passes[0].concurrency_a,
            "b": passes[0].concurrency_b,
        },
        "fake_mode": True,
        "reproduce": _reproduce_command(args),
        "gates": gates,
        "winners": winners,
        "passes": [
            {"run_index": report.run_index, "warmup": report.warmup,
             "network_attempts": report.network_attempts,
             "started_at": report.started_at}
            for report in passes
        ],
        "samples": [sample.as_dict() for sample in samples],
    }
    (run_dir / "results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return run_dir


def _run_pass(args: argparse.Namespace, pass_out: Path) -> None:
    report = asyncio.run(run_single_pass(args))
    payload = {
        "run_index": report.run_index,
        "git_head": report.git_head,
        "script_sha256": report.script_sha256,
        "arms": report.arms,
        "repeats": report.repeats,
        "questions": report.questions,
        "needs": report.needs,
        "latency_ms": report.latency_ms,
        "persist_swe": report.persist_swe,
        "concurrency_a": report.concurrency_a,
        "concurrency_b": report.concurrency_b,
        "network_attempts": report.network_attempts,
        "warmup": report.warmup,
        "started_at": report.started_at,
        "samples": report.samples,
    }
    pass_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _load_pass(path: Path) -> tuple[PassReport, list[Sample]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    report = PassReport(
        run_index=int(raw["run_index"]), git_head=str(raw["git_head"]),
        script_sha256=str(raw["script_sha256"]), arms=list(raw["arms"]),
        repeats=int(raw["repeats"]), questions=int(raw["questions"]),
        needs=int(raw["needs"]), latency_ms=int(raw["latency_ms"]),
        persist_swe=bool(raw["persist_swe"]),
        concurrency_a=int(raw["concurrency_a"]),
        concurrency_b=int(raw["concurrency_b"]), samples=raw["samples"],
        network_attempts=int(raw["network_attempts"]),
        warmup=dict(raw["warmup"]), started_at=str(raw["started_at"]),
    )
    return report, [Sample.from_dict(item) for item in raw["samples"]]


def _sweep(args: argparse.Namespace) -> int:
    script_sha = script_sha256()
    head = git_head()
    work = Path(tempfile.mkdtemp(prefix="research-swe-runs-"))
    passes: list[PassReport] = []
    samples: list[Sample] = []
    try:
        for run_index in range(args.runs):
            pass_out = work / f"pass-{run_index}.json"
            command = [
                sys.executable, str(Path(__file__)), "--single-pass",
                "--pass-out", str(pass_out), "--run-index", str(run_index),
                "--arms", ",".join(args.arms), "--questions", str(args.questions),
                "--repeats", str(args.repeats), "--needs", str(args.needs),
                "--fake-latency-ms", str(args.fake_latency_ms),
                "--timeout-seconds", str(args.timeout_seconds),
                "--run-out", str(args.run_out),
            ]
            if args.persist_swe:
                command.append("--persist-swe")
            if args.keep:
                command.append("--keep")
            completed = subprocess.run(command, check=False, timeout=args.pass_timeout)
            if completed.returncode != 0:
                raise SystemExit(
                    f"measurement run {run_index} failed with exit "
                    f"{completed.returncode}; no report is written"
                )
            report, run_samples = _load_pass(pass_out)
            if report.script_sha256 != script_sha or report.git_head != head:
                raise SystemExit(
                    "frozen harness changed during measurement "
                    f"(script {report.script_sha256} != {script_sha} or "
                    f"head {report.git_head} != {head})"
                )
            passes.append(report)
            samples.extend(run_samples)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    gates = evaluate(
        samples,
        needs=args.needs,
        arms=args.arms,
        network_attempts=sum(report.network_attempts for report in passes),
    )
    winners = _winner(gates)
    questions = load_eval_questions(args.questions)
    run_dir = _write_json(
        Path(args.run_out), passes=passes, samples=samples, gates=gates,
        winners=winners, question_rows=questions, args=args,
    )
    report_path = Path(args.report) if args.report else REPORT_FILE
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        render_report(ReportData(
            passes=passes, samples=samples, gates=gates, winners=winners,
            question_rows=questions, run_dir=run_dir, args=args,
            reproduce=_reproduce_command(args),
        )),
        encoding="utf-8",
    )
    print(f"status={'gates_passed' if gates['cutover_gate_ok'] else 'no_approved_variant'}")
    print(f"gates={json.dumps(gates['performance'])}")
    print(f"winners={json.dumps(winners)}")
    print(f"results={run_dir}")
    print(f"report={report_path}")
    if args.strict and not gates["cutover_gate_ok"]:
        return 1
    return 0


def _load_live(run_dir: Path) -> dict[str, Any] | None:
    candidates = sorted(run_dir.glob("live-observational-*.json"))
    if not candidates:
        return None
    return json.loads(candidates[-1].read_text(encoding="utf-8"))


def _render_existing(args: argparse.Namespace) -> int:
    run_dir = Path(args.render_run)
    payload = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    passes = [
        PassReport(
            run_index=int(pass_row["run_index"]),
            git_head=payload["git_head"],
            script_sha256=payload["script_sha256"],
            arms=list(payload["arms"]),
            repeats=int(payload["repeats"]),
            questions=len(payload["questions"]),
            needs=int(payload["needs"]),
            latency_ms=int(payload["fake_latency_ms"]),
            persist_swe=bool(payload["persist_swe"]),
            concurrency_a=int(payload["concurrency"]["a"]),
            concurrency_b=int(payload["concurrency"]["b"]),
            samples=[],
            network_attempts=0,
            warmup=dict(pass_row.get("warmup") or {}),
            started_at=str(pass_row.get("started_at") or ""),
        )
        for pass_row in payload["passes"]
    ]
    samples = [Sample.from_dict(item) for item in payload["samples"]]
    args.runs = int(payload["runs"])
    args.repeats = int(payload["repeats"])
    args.questions = len(payload["questions"])
    args.needs = int(payload["needs"])
    args.fake_latency_ms = int(payload["fake_latency_ms"])
    args.persist_swe = bool(payload["persist_swe"])
    args.arms = tuple(payload["arms"])
    gates = evaluate(
        samples,
        needs=int(payload["needs"]),
        arms=list(payload["arms"]),
        network_attempts=sum(
            int(row.get("network_attempts") or 0) for row in payload["passes"]
        ),
    )
    winners = _winner(gates)
    report_path = Path(args.report) if args.report else REPORT_FILE
    report_path.write_text(
        render_report(ReportData(
            passes=passes, samples=samples, gates=gates, winners=winners,
            question_rows=payload["questions"], run_dir=run_dir,
            args=args,
            reproduce=str(payload.get("reproduce") or _reproduce_command(args)),
            live=_load_live(run_dir),
        )),
        encoding="utf-8",
    )
    print(f"report={report_path}")
    return 0 if gates["cutover_gate_ok"] else 1


async def _run_live_arm(
    *,
    arm: str,
    question: Mapping[str, Any],
    factory: async_sessionmaker[AsyncSession],
    components: Mapping[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    from app.services.execution import create_attempt, create_run
    from app.services.research.composition import build_standard_research_router

    async with factory() as session:
        run = await create_run(
            session, customer_id=int(1), module="dd",
            title="SWE live observational", context={},
        )
        attempt = await create_attempt(
            session, run_id=run.id, attempt_type="generic_panel",
            configuration_snapshot={"mode": "benchmark-live"},
            input_snapshot={"question": question["question"]},
        )
        await session.commit()
        attempt_id = attempt.id
    recorded: dict[str, Any] = {}
    started = time.perf_counter()
    async with factory() as session:
        kwargs = {
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
        if arm == "baseline":
            await asyncio.wait_for(
                execute_attempt_research(session, **kwargs), timeout=timeout_seconds,
            )
        else:
            impl = _swe_loop_impl(arm, None, recorded)
            with mock.patch("app.services.research.execution._run_research_loop", impl):
                await asyncio.wait_for(
                    execute_attempt_research(session, **kwargs),
                    timeout=timeout_seconds,
                )
    wall_ms = (time.perf_counter() - started) * 1000
    async with factory() as session:
        attempt_row = await get_attempt(session, attempt_id)
        needs = await list_runtime_needs(session, attempt_id)
        assessments = await list_research_assessments(session, attempt_id)
        completeness = await list_research_completeness_passes(session, attempt_id)
    return {
        "arm": arm,
        "question_id": question["id"],
        "facit_sufficient": question["facit_sufficient"],
        "wall_ms": round(wall_ms, 3),
        "status": attempt_row.status,
        "stop_reason": attempt_row.research_stop_reason,
        "wave": attempt_row.research_wave,
        "needs": len(needs),
        "assessments": [row.result for row in assessments],
        "completeness": [row.result for row in completeness],
        "swe_steps_used": recorded.get("steps_used"),
        "swe_events": recorded.get("events"),
        "swe_sha": recorded.get("sha256"),
        "swe_concurrency": recorded.get("concurrency"),
    }


async def _run_live(args: argparse.Namespace) -> int:
    if not args.db_path:
        raise SystemExit(
            "--live requires --db-path to a configured database; it is "
            "observational, not a gate"
        )
    missing = [
        name
        for name in ("cerebras_api_key", "openai_api_key", "typesafe_api_key")
        if not str(getattr(settings, name, "") or "").strip()
    ]
    if missing:
        raise SystemExit(f"--live requires configured model keys: {missing}")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.services.research_worker import bind_research_components

    questions = load_eval_questions(args.questions)
    engine = create_async_engine(f"sqlite+aiosqlite:///{args.db_path}")
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    llm_calls: list[LLMCallStats] = []
    token = bind_usage_recorder(llm_calls.append)
    rows: list[dict[str, Any]] = []
    try:
        for question in questions:
            for arm in args.arms:
                async with factory() as session:
                    components = await bind_research_components(
                        session, customer_id=int(1), module="dd",
                    )
                before = len(llm_calls)
                row = await _run_live_arm(
                    arm=arm, question=question, factory=factory,
                    components=components, timeout_seconds=args.timeout_seconds,
                )
                calls = llm_calls[before:]
                row["llm_calls"] = len(calls)
                row["prompt_tokens"] = sum(call.prompt_tokens for call in calls)
                row["completion_tokens"] = sum(
                    call.completion_tokens for call in calls
                )
                rows.append(row)
                print(f"live arm={arm} question={question['id']} llm_calls={len(calls)}")
    finally:
        reset_usage_recorder(token)
        await engine.dispose()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.run_out)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"live-observational-{stamp}.json"
    payload = {
        "mode": "live-observational",
        "gate": False,
        "note": (
            "Observational and non-deterministic. Not part of the fake-mode gates; "
            "cannot approve a workflow."
        ),
        "git_head": git_head(),
        "script_sha256": script_sha256(),
        "db_path": args.db_path,
        "customer_id": int(1),
        "arms": list(args.arms),
        "questions": args.questions,
        "rows": rows,
        "total_llm_calls": len(llm_calls),
        "estimated_cost_units": sum(
            row["prompt_tokens"] / 1e6 * args.input_price_per_1m
            + row["completion_tokens"] / 1e6 * args.output_price_per_1m
            for row in rows
        ),
    }
    out.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"live_observational={out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--questions", type=int, default=DEFAULT_QUESTIONS)
    parser.add_argument("--needs", type=int, default=DEFAULT_NEEDS)
    parser.add_argument("--fake-latency-ms", type=int, default=DEFAULT_LATENCY_MS)
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--persist-swe", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--run-out", default=str(DEFAULT_OUT))
    parser.add_argument("--report", default="")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--pass-timeout", type=float, default=900.0)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--db-path", default="")
    parser.add_argument("--customer-id", type=int, default=CUSTOMER_ID)
    parser.add_argument("--input-price-per-1m", type=float, default=0.0)
    parser.add_argument("--output-price-per-1m", type=float, default=0.0)
    parser.add_argument("--render-run", default="", help="rerender report from a run dir")
    parser.add_argument("--single-pass", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pass-out", default="", help=argparse.SUPPRESS)
    parser.add_argument("--run-index", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.arms = tuple(arm.strip() for arm in args.arms.split(",") if arm.strip())
    unknown = [arm for arm in args.arms if arm not in ARMS]
    if unknown:
        raise SystemExit(f"unknown arms: {unknown}")
    if len(args.arms) != len(ARMS):
        print(
            "WARNING: --arms subset. Pareto and winner require all three arms; "
            "cutover approval requires arm A.",
        )
    if args.render_run:
        return _render_existing(args)
    if args.single_pass:
        if not args.pass_out:
            raise SystemExit("--single-pass requires --pass-out")
        _run_pass(args, Path(args.pass_out))
        return 0
    if args.live:
        return asyncio.run(_run_live(args))
    if not 2 <= args.questions <= 4:
        raise SystemExit("--questions must be 2-4 (research-36 eval slice)")
    if args.runs < 3:
        print("WARNING: fewer than 3 independent runs; the CI gate is not meaningful")
    if args.repeats < 6:
        print("WARNING: fewer than 6 repeats; the p95 gate is not meaningful")
    return _sweep(args)


if __name__ == "__main__":
    raise SystemExit(main())
