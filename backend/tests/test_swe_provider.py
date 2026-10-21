"""SWE phase 4: provider decisions, prompt rendering, exact cache, jev adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

pytest.importorskip("swe_native")

from app.config import settings
from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.overgraph.jev_cache import JevDecisionCache, decision_cache_key
from app.swe.definition import CompiledDefinition, compile_definition
from app.swe.providers import make_jev_provider
from app.swe.runtime import WorkflowResources, run_workflow
from app.swe.runtime_errors import SwePreflightError
from tests.swe.runtime_helpers import swe_tasks

pytestmark = pytest.mark.swe_runtime

PROMPT_KEY = "research.assessment.user"
PROMPTS = {PROMPT_KEY: "Question: {plan_json}. Evidence: {evidence_json}"}
INPUT = {"plan_json": '{"objective": "x"}', "evidence_json": "[]"}

SUFFICIENT_ANSWERS = {
    "answerable_now": {"noul": 0.95},
    "material_gap": {"noul": 0.05},
    "contradiction": {"noul": 0.05},
    "follow_up_change": {"noul": 0.05},
    "additional_source": {"noul": 0.05},
}


def _provider_document(
    *,
    cache_policy: str = "off",
    choices: tuple[str, ...] = ("sufficient", "insufficient", "uncertain"),
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    routes = {
        choice: ("done" if choice == "sufficient" else "incomplete")
        for choice in choices
    }
    return {
        "version": "1.0",
        "name": "provider_fixture",
        "entrypoint": "evaluate",
        "limits": {
            "max_steps": 10,
            "max_depth": 2,
            "timeout_seconds": timeout_seconds,
        },
        "nodes": {
            "evaluate": {
                "type": "decision",
                "evaluator": "provider",
                "provider": "fake",
                "prompt_key": PROMPT_KEY,
                "input": {
                    "plan_json": "$.input.plan_json",
                    "evidence_json": "$.input.evidence_json",
                },
                "choices": list(choices),
                "routes": routes,
                "cache_policy": cache_policy,
            },
            "done": {"type": "end", "status": "completed"},
            "incomplete": {"type": "end", "status": "incomplete"},
        },
    }


def _compile(**kwargs: Any) -> CompiledDefinition:
    return compile_definition(
        _provider_document(**kwargs),
        providers=frozenset({"fake"}),
    )


def _resources(
    provider: Any,
    *,
    cache: JevDecisionCache | None = None,
    prompts: Mapping[str, str] | None = PROMPTS,
) -> WorkflowResources:
    return WorkflowResources(
        providers={"fake": provider},
        prompts=prompts,
        cache=cache,
    )


class _FakeJev:
    def __init__(self, answers: Mapping[str, Any]) -> None:
        self.answers = answers
        self.calls = 0

    async def ask(
        self,
        *,
        state: object,
        questions: dict[str, Any],
        model: str,
        timeout_seconds: float,
    ) -> JevSystemOneResult:
        self.calls += 1
        return JevSystemOneResult(
            answers=dict(self.answers),
            model=model,
            latency_ms=1.0,
            input_chars=len(str(state)),
            usage=JevUsage(),
            raw={},
        )


async def test_provider_decision_runs_end_to_end() -> None:
    seen: dict[str, Any] = {}

    async def provider(request: Mapping[str, Any]) -> dict[str, Any]:
        seen["request"] = request
        return {"choice": "sufficient", "confidence": 0.9}

    result = await run_workflow(
        _compile(),
        {},
        INPUT,
        resources=_resources(provider),
    )

    assert result.status == "completed"
    assert result.output["evaluate"]["choice"] == "sufficient"
    assert result.output["evaluate"]["confidence"] == 0.9
    assert seen["request"]["provider"] == "fake"
    assert seen["request"]["prompt"] == 'Question: {"objective": "x"}. Evidence: []'
    types = [event["type"] for event in result.events]
    assert "ProviderInvoked" in types
    assert "ProviderCompleted" in types
    assert "DecisionTaken" in types


async def test_unregistered_provider_fails_preflight() -> None:
    with pytest.raises(SwePreflightError, match="decision provider"):
        await run_workflow(
            _compile(),
            {},
            INPUT,
            resources=WorkflowResources(prompts=PROMPTS),
        )


async def test_missing_active_prompt_fails_preflight() -> None:
    async def provider(_request: Mapping[str, Any]) -> str:
        return "sufficient"

    with pytest.raises(SwePreflightError, match="active prompt"):
        await run_workflow(
            _compile(),
            {},
            INPUT,
            resources=_resources(provider, prompts={}),
        )


async def test_provider_choice_outside_declared_choices_fails_run() -> None:
    async def provider(_request: Mapping[str, Any]) -> str:
        return "maybe"

    result = await run_workflow(_compile(), {}, INPUT, resources=_resources(provider))

    assert result.status == "failed"
    assert result.error is not None
    assert "outside the declared choices" in result.error["message"]


async def test_provider_exception_fails_run() -> None:
    async def provider(_request: Mapping[str, Any]) -> str:
        raise RuntimeError("provider exploded")

    result = await run_workflow(_compile(), {}, INPUT, resources=_resources(provider))

    assert result.status == "failed"
    assert result.error is not None
    assert "provider exploded" in result.error["message"]


async def test_hanging_provider_hits_deadline() -> None:
    async def provider(_request: Mapping[str, Any]) -> str:
        await asyncio.Event().wait()
        return "sufficient"

    result = await run_workflow(
        _compile(timeout_seconds=1),
        {},
        INPUT,
        resources=_resources(provider),
    )

    assert result.status == "failed"
    assert result.error is not None
    assert "timeout" in result.error["message"]
    assert swe_tasks() == []


async def test_exact_cache_reports_hit_and_miss(tmp_path: Any) -> None:
    calls: list[int] = []

    async def provider(_request: Mapping[str, Any]) -> str:
        calls.append(1)
        return "sufficient"

    cache = JevDecisionCache(root=tmp_path / "jev")
    resources = _resources(provider, cache=cache)
    try:
        first = await run_workflow(_compile(cache_policy="exact"), {}, INPUT, resources=resources)
        second = await run_workflow(_compile(cache_policy="exact"), {}, INPUT, resources=resources)
    finally:
        await cache.close()

    assert first.status == "completed"
    assert second.status == "completed"
    assert len(calls) == 1
    assert first.output["evaluate"]["cache"] == "miss"
    assert second.output["evaluate"]["cache"] == "hit"


async def test_exact_cache_without_cache_fails_preflight() -> None:
    async def provider(_request: Mapping[str, Any]) -> str:
        return "sufficient"

    with pytest.raises(SwePreflightError, match="requires a provider cache"):
        await run_workflow(
            _compile(cache_policy="exact"),
            {},
            INPUT,
            resources=_resources(provider),
        )


async def test_cache_key_changes_with_prompt_and_input() -> None:
    base = {
        "provider": "fake",
        "prompt_key": PROMPT_KEY,
        "prompt": "same",
        "input_data": {"a": 1},
        "choices": ["yes", "no"],
        "params": {},
    }
    key = decision_cache_key(**base)
    assert key == decision_cache_key(**base)
    assert key != decision_cache_key(**{**base, "prompt": "other"})
    assert key != decision_cache_key(**{**base, "input_data": {"a": 2}})


async def test_single_flight_coalesces_concurrent_resolves(tmp_path: Any) -> None:
    cache = JevDecisionCache(root=tmp_path / "jev")
    calls = 0

    async def compute() -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"choice": "sufficient"}

    try:
        results = await asyncio.gather(
            *(
                cache.resolve(
                    "same-key",
                    compute,
                    provider="fake",
                    prompt_key=PROMPT_KEY,
                )
                for _ in range(4)
            )
        )
    finally:
        await cache.close()

    assert calls == 1
    assert sum(1 for _answer, hit in results if not hit) == 1
    assert all(answer["choice"] == "sufficient" for answer, _hit in results)


async def test_l2_cache_survives_a_new_instance(tmp_path: Any) -> None:
    root = tmp_path / "jev"
    key = decision_cache_key(
        provider="fake",
        prompt_key=PROMPT_KEY,
        prompt="deterministic",
        input_data={"a": 1},
        choices=["yes", "no"],
        params={},
    )
    calls = 0

    async def compute() -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        return {"choice": "yes"}

    first = JevDecisionCache(root=root)
    try:
        answer, hit = await first.resolve(
            key, compute, provider="fake", prompt_key=PROMPT_KEY
        )
    finally:
        await first.close()
    assert answer["choice"] == "yes"
    assert hit is False
    assert calls == 1

    async def forbidden() -> Mapping[str, Any]:
        raise AssertionError("provider must not run on an L2 hit")

    second = JevDecisionCache(root=root)
    try:
        answer, hit = await second.resolve(
            key, forbidden, provider="fake", prompt_key=PROMPT_KEY
        )
    finally:
        await second.close()
    assert hit is True
    assert answer["choice"] == "yes"
    assert second.l2_hits == 1


async def test_jev_provider_maps_answers_to_a_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "research_jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "test-typesafe-key")
    client = _FakeJev(SUFFICIENT_ANSWERS)
    provider = make_jev_provider(client=client)

    result = await run_workflow(
        _compile(),
        {},
        INPUT,
        resources=_resources(provider),
    )

    assert result.status == "completed"
    assert result.output["evaluate"]["choice"] == "sufficient"
    assert result.output["evaluate"]["provider"] == "jev"
    assert client.calls == 1


async def test_jev_provider_rejects_out_of_contract_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "research_jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "test-typesafe-key")
    client = _FakeJev(SUFFICIENT_ANSWERS)
    provider = make_jev_provider(client=client)

    with pytest.raises(JevClientError, match="not a declared choice"):
        await provider(
            {
                "provider": "jev",
                "prompt_key": PROMPT_KEY,
                "prompt": "rendered",
                "input": {},
                "choices": ("yes", "no"),
                "cache_policy": "off",
            }
        )
