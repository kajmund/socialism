"""Run the research wave loop on SWE.

Cutover bridge. It does not reimplement research: every handler calls the
domain wave primitives, so a SWE run preserves the previous loop's plan
construction, need execution, evidence persistence, quality, assessment,
follow-up/completeness planning, decision policy and freeze.

What SWE owns is the loop shape: a `map` schedules every pending need execution
as a `research.execute_need` child, `research.finish_wave` runs the unchanged
wave body (barrier -> quality -> assessment -> decision -> follow-up planning),
and an expression `decision` routes either back to `research.run_wave` or to the
terminal `end`. The map has no wave-level cap because the phase-2 loop also
starts one worker per pending need; provider retrieval is bounded inside the
child handler by the attempt's `research_need_concurrency` semaphore, like the
deleted phase-2 fan-out shell did. Variants differ only in that retrieval
concurrency.

`run_research_loop_via_swe` is a drop-in for
`app.services.research.execution._run_research_loop` (same ``**kwargs``), the
single seam `execute_attempt_research` calls; the wiring tests patch it. The lease-lost event is passed as the
runner `cancel_event` (through `WorkflowResources`), so a lost research lease
cancels in-flight handlers; a terminal `cancelled` run re-raises
`asyncio.CancelledError` to match the pre-cutover write-fence semantics. The
durable OverGraph run store exists but is not production-wired in this cutover;
tests may pass one through `build_loop`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from functools import cache
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.observability.context import log_context
from app.swe.definition import CompiledDefinition, compile_definition
from app.swe.run_store import RunStore
from app.swe.runtime import RunResult, WorkflowResources, WorkflowRunner
from app.swe.runtime_dispatch import Handler
from app.services.research.models import ResearchNeed, ResearchPlan

if TYPE_CHECKING:
    from app.services.research.loop_control import ResearchWaveConfig

HANDLER_NAMES = frozenset(
    {"research.run_wave", "research.execute_need", "research.finish_wave"}
)

#: Variant B multiplies today's need concurrency; the cap keeps retrieval bounded.
PARALLEL_FANOUT_FACTOR = 2
PARALLEL_FANOUT_CAP = 16

#: The phase-2 loop starts one worker per pending need; `research_max_needs_per_attempt`
#: bounds the plan at 64, so this cap keeps the map effectively unbounded while
#: still protecting the machine from an accidental huge fan-out.
_MAP_CONCURRENCY = 64

_WORKFLOW_LIMITS = {"max_steps": 500, "max_depth": 4, "timeout_seconds": 1800}


def _execution_error(message: str) -> Exception:
    """Build the domain error lazily so importing the bridge stays cycle-free."""
    from app.services.research.execution import ResearchExecutionError

    return ResearchExecutionError(message)


@cache
def _workflow(concurrency: int) -> CompiledDefinition:
    """Wave-loop definition.

    ``concurrency`` is kept in the cache key because the measurement harness
    records one definition per arm; the map itself is not the retrieval bound.
    """
    document = {
        "version": "1.0",
        "name": "research_wave_loop",
        "entrypoint": "run_wave",
        "limits": dict(_WORKFLOW_LIMITS),
        "nodes": {
            "run_wave": {"type": "task", "handler": "research.run_wave", "next": "needs"},
            "needs": {
                "type": "map",
                "items": "$.run_wave.result.pending",
                "child": "execute_need",
                "concurrency": _MAP_CONCURRENCY,
                "next": "finish_wave",
            },
            "execute_need": {"type": "task", "handler": "research.execute_need"},
            "finish_wave": {
                "type": "task",
                "handler": "research.finish_wave",
                "next": "route",
            },
            "route": {
                "type": "decision",
                "evaluator": "expression",
                "condition": {"eq": [{"var": "$.finish_wave.result.done"}, {"const": True}]},
                "routes": {"true": "done", "false": "run_wave"},
            },
            "done": {"type": "end", "status": "completed"},
        },
    }
    return compile_definition(document, handlers=HANDLER_NAMES)


class SweResearchLoop:
    """One SWE-driven research wave loop for one attempt."""

    def __init__(
        self,
        config: ResearchWaveConfig,
        *,
        concurrency: int,
        cancel_event: asyncio.Event | None = None,
        run_store: RunStore | None = None,
    ) -> None:
        from app.services.research.evidence_screen import bind_attempt_relevance
        from app.services.research.execution import quality_descriptors
        from app.services.research.quality_persist import EagerQualityBind

        if concurrency < 1:
            raise ValueError("research sweep concurrency must be >= 1")
        _, relevance_assessor = bind_attempt_relevance(
            config.assessor, config.relevance_assessor,
        )
        self._config = replace(config, relevance_assessor=relevance_assessor)
        self._concurrency = concurrency
        self._cancel_event = cancel_event
        self._run_store = run_store
        self._persist_lock = asyncio.Lock()
        self._retrieve_slots = asyncio.Semaphore(concurrency)
        self._snapshot_plan: ResearchPlan | None = None
        self._needs_by_id: dict[str, ResearchNeed] = {}
        self._wave: int | None = None
        self._eager = EagerQualityBind(
            descriptors=quality_descriptors(config.router, config.provider_descriptors),
            relevance_assessor=relevance_assessor,
            reuse_assessor=config.assessor,
        )
        self.handlers: dict[str, Handler] = {
            "research.run_wave": self._run_wave,
            "research.execute_need": self._execute_need,
            "research.finish_wave": self._finish_wave,
        }

    async def run(self, *, snapshot_plan: ResearchPlan, run_id: str | None = None) -> RunResult:
        self._snapshot_plan = snapshot_plan
        runner = WorkflowRunner(
            _workflow(self._concurrency),
            self.handlers,
            resources=WorkflowResources(cancel_event=self._cancel_event),
            run_store=self._run_store,
        )
        return await runner.run({}, run_id=run_id)

    async def _run_wave(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        from app.services.execution.service import get_attempt
        from app.services.research.execution import pending_need_pairs, runtime_plan

        async with self._config.factory() as session:
            attempt = await get_attempt(session, self._config.attempt_id)
            pending = await pending_need_pairs(session, self._config.attempt_id)
            active_plan = await runtime_plan(session, self._config.attempt_id)
        self._wave = attempt.research_wave
        with log_context(wave_number=self._wave):
            if not active_plan.needs:
                active_plan = self._snapshot_plan
            if active_plan is None:
                raise _execution_error("research loop has no snapshot plan")
            self._needs_by_id = {need.id: need for need in active_plan.needs}
        return {
            "pending": [
                {"execution_id": execution_id, "need_id": need_id}
                for execution_id, need_id in pending
            ],
        }

    async def _execute_need(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from app.services.research.execution import (
            complete_timed_out_need,
            execute_one_need,
        )

        item = payload["item"]
        execution_id = str(item["execution_id"])
        need = self._needs_by_id.get(str(item["need_id"]))
        if need is None:
            raise _execution_error(
                f"pending need {item['need_id']!r} is not in the runtime plan"
            )
        with log_context(wave_number=self._wave):
            try:
                await asyncio.wait_for(
                    execute_one_need(
                        factory=self._config.factory,
                        persist_lock=self._persist_lock,
                        retrieve_slots=self._retrieve_slots,
                        execution_id=execution_id,
                        need=need,
                        context=self._config.context,
                        evidence_set_id=self._config.evidence_set_id,
                        router=self._config.router,
                        router_factory=self._config.router_factory,
                        question_graph=self._config.question_graph,
                        attempt_id=self._config.attempt_id,
                        eager=self._eager,
                    ),
                    timeout=settings.research_need_timeout_seconds,
                )
            except TimeoutError:
                await complete_timed_out_need(
                    self._config.factory,
                    self._persist_lock,
                    execution_id=execution_id,
                    need=need,
                    evidence_set_id=self._config.evidence_set_id,
                    attempt_id=self._config.attempt_id,
                )
        return {"execution_id": execution_id}

    async def _finish_wave(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        from app.services.execution.service import get_attempt
        from app.services.research.loop_control import finish_research_wave

        if self._snapshot_plan is None:
            raise _execution_error("research loop has no snapshot plan")
        async with self._config.factory() as session:
            attempt = await get_attempt(session, self._config.attempt_id)
            self._wave = attempt.research_wave
        with log_context(wave_number=self._wave):
            next_wave = await finish_research_wave(
                self._config,
                snapshot_plan=self._snapshot_plan,
                wave=self._wave,
            )
        return {"done": next_wave is None}


def build_loop(
    kwargs: Mapping[str, Any],
    *,
    concurrency: int,
    run_store: RunStore | None = None,
) -> tuple[SweResearchLoop, ResearchPlan]:
    """Build a bridge loop from the same kwargs the execution seam receives."""
    from app.services.research.loop_control import wave_config_from_kwargs

    config = wave_config_from_kwargs(dict(kwargs))
    snapshot_plan = kwargs["snapshot_plan"]
    if not isinstance(snapshot_plan, ResearchPlan):
        raise _execution_error("snapshot_plan must be a ResearchPlan")
    cancel_event = kwargs.get("lease_lost")
    if cancel_event is not None and not isinstance(cancel_event, asyncio.Event):
        raise _execution_error("lease_lost must be an asyncio.Event")
    return (
        SweResearchLoop(
            config,
            concurrency=concurrency,
            cancel_event=cancel_event,
            run_store=run_store,
        ),
        snapshot_plan,
    )


async def _assert_start_wave(loop: SweResearchLoop, kwargs: Mapping[str, Any]) -> None:
    """Keep the legacy `start_wave` argument honest against the persisted wave."""
    expected = kwargs.get("start_wave")
    if expected is None:
        return
    from app.services.execution.service import get_attempt

    async with loop._config.factory() as session:
        attempt = await get_attempt(session, loop._config.attempt_id)
    if attempt.research_wave != int(expected):
        raise _execution_error(
            "start_wave="
            f"{expected} does not match persisted research_wave={attempt.research_wave}"
            f" for attempt {loop._config.attempt_id}"
        )


async def _run_via_swe(kwargs: Mapping[str, Any], *, concurrency: int) -> None:
    loop, snapshot_plan = build_loop(kwargs, concurrency=concurrency)
    await _assert_start_wave(loop, kwargs)
    result = await loop.run(snapshot_plan=snapshot_plan)
    if result.status == "cancelled":
        raise asyncio.CancelledError
    if result.status != "completed":
        raise _execution_error(
            f"SWE research loop ended in status={result.status}: {result.error}"
        )


async def run_research_loop_via_swe(**kwargs: object) -> None:
    """Cutover loop: same need concurrency as the phase-2 loop."""
    from app.services.research.loop_control import wave_config_from_kwargs

    config = wave_config_from_kwargs(dict(kwargs))
    await _run_via_swe(kwargs, concurrency=config.concurrency)


async def run_research_loop_via_swe_parallel(**kwargs: object) -> None:
    """Variant with wider fan-out; not the cutover choice, kept for measurement."""
    from app.services.research.loop_control import wave_config_from_kwargs

    config = wave_config_from_kwargs(dict(kwargs))
    await _run_via_swe(
        kwargs,
        concurrency=min(config.concurrency * PARALLEL_FANOUT_FACTOR, PARALLEL_FANOUT_CAP),
    )
