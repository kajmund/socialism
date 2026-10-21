"""Run the research wave loop on SWE.

Phase 5 bridge. It does not reimplement research: every handler calls the same
private wave primitives the phase-2 loop in `loop_control` calls, so a SWE run
and `run_research_loop` share plan construction, need execution, evidence
persistence, quality, assessment, follow-up/completeness planning, decision
policy and freeze.

What SWE owns is the loop shape: a `map` fans pending need executions out to
`research.execute_need` children with a bounded concurrency, `research.finish_wave`
runs the unchanged wave body (barrier -> quality -> assessment -> decision ->
follow-up planning), and an expression `decision` routes either back to
`research.run_wave` or to the terminal `end`. Two compiled definitions differ
only in fan-out concurrency, so a differential run can compare wave structure
without changing semantics.

`run_research_loop_via_swe` is a drop-in for
`app.services.research.execution._run_research_loop` (same ``**kwargs``), which
is the seam the differential tests patch. Production cutover is a later PR.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from functools import cache
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.swe.definition import CompiledDefinition, compile_definition
from app.swe.run_store import RunStore
from app.swe.runtime import RunResult, WorkflowRunner
from app.swe.runtime_dispatch import Handler
from app.services.research.models import ResearchNeed, ResearchPlan

if TYPE_CHECKING:
    from app.services.research.loop_control import ResearchLoopConfig

HANDLER_NAMES = frozenset(
    {"research.run_wave", "research.execute_need", "research.finish_wave"}
)

#: Variant B multiplies today's need concurrency; the cap keeps fan-out bounded.
PARALLEL_FANOUT_FACTOR = 2
PARALLEL_FANOUT_CAP = 16

_WORKFLOW_LIMITS = {"max_steps": 500, "max_depth": 4, "timeout_seconds": 1800}


def _execution_error(message: str) -> Exception:
    """Build the domain error lazily so importing the bridge stays cycle-free."""
    from app.services.research.execution import ResearchExecutionError

    return ResearchExecutionError(message)


@cache
def _workflow(concurrency: int) -> CompiledDefinition:
    """Wave-loop definition; only the map concurrency changes between variants."""
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
                "concurrency": concurrency,
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
        config: ResearchLoopConfig,
        *,
        concurrency: int,
        run_store: RunStore | None = None,
    ) -> None:
        from app.services.research.evidence_screen import bind_attempt_relevance
        from app.services.research.execution import _quality_descriptors
        from app.services.research.quality_persist import EagerQualityBind

        if concurrency < 1:
            raise ValueError("research sweep concurrency must be >= 1")
        _, relevance_assessor = bind_attempt_relevance(
            config.assessor, config.relevance_assessor,
        )
        self._config = replace(config, relevance_assessor=relevance_assessor)
        self._concurrency = concurrency
        self._run_store = run_store
        self._persist_lock = asyncio.Lock()
        self._retrieve_slots = asyncio.Semaphore(concurrency)
        self._snapshot_plan: ResearchPlan | None = None
        self._needs_by_id: dict[str, ResearchNeed] = {}
        self._eager = EagerQualityBind(
            descriptors=_quality_descriptors(config.router, config.provider_descriptors),
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
            run_store=self._run_store,
        )
        return await runner.run({}, run_id=run_id)

    async def _run_wave(self, _payload: Mapping[str, Any]) -> dict[str, Any]:
        from app.services.research.execution import _pending_need_pairs, _runtime_plan

        async with self._config.factory() as session:
            pending = await _pending_need_pairs(session, self._config.attempt_id)
            runtime_plan = await _runtime_plan(session, self._config.attempt_id)
        if not runtime_plan.needs:
            runtime_plan = self._snapshot_plan
        if runtime_plan is None:
            raise _execution_error("research loop has no snapshot plan")
        self._needs_by_id = {need.id: need for need in runtime_plan.needs}
        return {
            "pending": [
                {"execution_id": execution_id, "need_id": need_id}
                for execution_id, need_id in pending
            ],
        }

    async def _execute_need(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from app.services.research.execution import (
            _complete_timed_out_need,
            _execute_one_need,
        )

        item = payload["item"]
        execution_id = str(item["execution_id"])
        need = self._needs_by_id.get(str(item["need_id"]))
        if need is None:
            raise _execution_error(
                f"pending need {item['need_id']!r} is not in the runtime plan"
            )
        try:
            await asyncio.wait_for(
                _execute_one_need(
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
            await _complete_timed_out_need(
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
        from app.services.research.loop_control import _finish_research_wave

        if self._snapshot_plan is None:
            raise _execution_error("research loop has no snapshot plan")
        async with self._config.factory() as session:
            attempt = await get_attempt(session, self._config.attempt_id)
            wave = attempt.research_wave
        next_wave = await _finish_research_wave(
            self._config,
            snapshot_plan=self._snapshot_plan,
            wave=wave,
        )
        return {"done": next_wave is None}


def build_loop(
    kwargs: Mapping[str, Any],
    *,
    concurrency: int,
    run_store: RunStore | None = None,
) -> tuple[SweResearchLoop, ResearchPlan]:
    """Build a bridge loop from the same kwargs `run_research_loop` receives."""
    from app.services.research.loop_control import _loop_config

    config = _loop_config(dict(kwargs))
    snapshot_plan = kwargs["snapshot_plan"]
    if not isinstance(snapshot_plan, ResearchPlan):
        raise _execution_error("snapshot_plan must be a ResearchPlan")
    return SweResearchLoop(config, concurrency=concurrency, run_store=run_store), snapshot_plan


async def _run_via_swe(kwargs: Mapping[str, Any], *, concurrency: int) -> None:
    loop, snapshot_plan = build_loop(kwargs, concurrency=concurrency)
    result = await loop.run(snapshot_plan=snapshot_plan)
    if result.status != "completed":
        raise _execution_error(
            f"SWE research loop ended in status={result.status}: {result.error}"
        )


async def run_research_loop_via_swe(**kwargs: object) -> None:
    """Variant A: same need concurrency as the phase-2 loop."""
    from app.services.research.loop_control import _loop_config

    config = _loop_config(dict(kwargs))
    await _run_via_swe(kwargs, concurrency=config.concurrency)


async def run_research_loop_via_swe_parallel(**kwargs: object) -> None:
    """Variant B: wider fan-out, identical research semantics."""
    from app.services.research.loop_control import _loop_config

    config = _loop_config(dict(kwargs))
    await _run_via_swe(
        kwargs,
        concurrency=min(config.concurrency * PARALLEL_FANOUT_FACTOR, PARALLEL_FANOUT_CAP),
    )
