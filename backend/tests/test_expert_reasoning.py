"""Atomic Jev scoring, deterministic routing, and escalation."""

from __future__ import annotations

import asyncio
import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.jev.system import JevSystemOneResult, JevUsage
from app.llm.chat_model import chat_model_label
from app.llm.runtime_override import LlmResolution, LlmRuntimeView
from app.services.expert_async_tools import PlannedCall
from app.services.expert_reasoning_episode import trace_events
from app.services.expert_reasoning import (
    ReasoningScores,
    assess_expert_reasoning,
    higher_profile,
    route_scores,
    should_reassess_tools,
    spawn_should_expose,
)
from app.services.prompt_catalog import default_prompts


def _scores(**overrides: float) -> ReasoningScores:
    values = {
        "simple_operation": 0.1,
        "analysis": 0.1,
        "multi_step": 0.1,
        "comparison": 0.1,
        "synthesis": 0.1,
        "conflicting_information": 0.1,
        "decomposable": 0.1,
        "parallelizable": 0.1,
        **overrides,
    }
    return ReasoningScores(**values)


def test_router_matches_fast_balanced_and_deep_examples():
    assert route_scores(
        _scores(simple_operation=0.97, analysis=0.05, multi_step=0.13)
    ) == ("fast", "simple_operation")
    assert route_scores(
        _scores(analysis=0.82, multi_step=0.48, synthesis=0.41)
    ) == ("balanced", "uncertain")
    assert route_scores(
        _scores(analysis=0.96, multi_step=0.91, comparison=0.99, synthesis=0.88)
    )[0] == "deep"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("comparison", 0.81, "comparison"),
        ("synthesis", 0.71, "synthesis"),
        ("conflicting_information", 0.76, "conflicting_information"),
    ],
)
def test_each_strong_complex_signal_routes_deep(field, value, reason):
    profile, actual_reason = route_scores(_scores(**{field: value}))
    assert (profile, actual_reason) == ("deep", reason)


def test_ambiguous_fast_and_deep_signals_route_balanced():
    profile, reason = route_scores(
        _scores(simple_operation=0.95, analysis=0.95)
    )
    assert (profile, reason) == ("balanced", "ambiguous")


def test_escalation_is_monotonic_and_navigation_is_trivial():
    assert higher_profile("fast", "balanced") == "balanced"
    assert higher_profile("fast", "deep") == "deep"
    assert higher_profile("deep", "fast") == "deep"
    assert should_reassess_tools(["show_document", "focus_anchor"]) is False
    assert should_reassess_tools(["show_document", "search_knowledge"]) is True


def test_spawn_scores_do_not_change_profile():
    profile, reason = route_scores(
        _scores(analysis=0.91, comparison=0.96, decomposable=0.97, parallelizable=0.95)
    )
    assert (profile, reason) == ("deep", "comparison")
    profile, reason = route_scores(
        _scores(analysis=0.91, comparison=0.96, decomposable=0.32, parallelizable=0.18)
    )
    assert (profile, reason) == ("deep", "comparison")


def test_spawn_gate_requires_deep_and_both_signals():
    deep_split = _scores(decomposable=0.97, parallelizable=0.95)
    assert spawn_should_expose("deep", deep_split) is True
    assert spawn_should_expose("balanced", deep_split) is False
    assert spawn_should_expose("fast", deep_split) is False
    assert spawn_should_expose("deep", None) is False
    assert spawn_should_expose(
        "deep", _scores(decomposable=0.32, parallelizable=0.18)
    ) is False
    assert spawn_should_expose(
        "deep", _scores(decomposable=0.97, parallelizable=0.18)
    ) is False


class _FakeJev:
    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.questions: dict | None = None

    async def ask(self, *, state, questions, model, timeout_seconds):
        del state, model, timeout_seconds
        self.questions = questions
        return JevSystemOneResult(
            answers=self.answers,
            model="jev-test",
            latency_ms=1,
            input_chars=10,
            usage=JevUsage(),
            raw={},
        )


@pytest.mark.asyncio
async def test_assessment_batches_all_scores_in_one_call():
    answers = {
        key: {"noul": value}
        for key, value in {
            "simple_operation": 0.97,
            "analysis": 0.05,
            "multi_step": 0.13,
            "comparison": 0.01,
            "synthesis": 0.01,
            "conflicting_information": 0.01,
            "decomposable": 0.01,
            "parallelizable": 0.01,
        }.items()
    }
    jev = _FakeJev(answers)
    decision = await assess_expert_reasoning(
        prompts=default_prompts("sv"),
        state={"message": "Visa klausul 3."},
        jev=jev,
    )
    assert decision.profile == "fast"
    assert jev.questions is not None
    assert set(jev.questions) == set(answers)


@pytest.mark.asyncio
async def test_missing_spawn_signals_fall_back_to_balanced():
    prompts = default_prompts("sv")
    legacy = {
        key: json.loads(prompts["chat.expert.reasoning_assessment"])[key]
        for key in (
            "simple_operation",
            "analysis",
            "multi_step",
            "comparison",
            "synthesis",
            "conflicting_information",
        )
    }
    answers = {key: {"noul": 0.1} for key in legacy}
    answers["analysis"] = {"noul": 0.96}
    answers["multi_step"] = {"noul": 0.91}
    decision = await assess_expert_reasoning(
        prompts={"chat.expert.reasoning_assessment": json.dumps(legacy)},
        state={"message": "Förklara detta."},
        jev=_FakeJev(answers),
    )
    assert decision.fallback is True
    assert decision.profile == "balanced"
    assert decision.scores is None
    assert spawn_should_expose(decision.profile, decision.scores) is False


@pytest.mark.asyncio
async def test_invalid_assessment_falls_back_to_balanced():
    decision = await assess_expert_reasoning(
        prompts=default_prompts("sv"),
        state={"message": "Hej"},
        jev=_FakeJev({"simple_operation": {"noul": 1}}),
    )
    assert decision.profile == "balanced"
    assert decision.fallback is True
    assert decision.error_category == "schema_validation"


@pytest.mark.asyncio
async def test_jev_wait_does_not_hold_committed_database_connection(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/routing.db",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class _ConnectionProbeJev(_FakeJev):
        async def ask(self, *, state, questions, model, timeout_seconds):
            async with factory() as other:
                assert await asyncio.wait_for(
                    other.scalar(text("SELECT 1")), timeout=1
                ) == 1
            return await super().ask(
                state=state,
                questions=questions,
                model=model,
                timeout_seconds=timeout_seconds,
            )

    answers = {
        key: {"noul": 0.1}
        for key in (
            "simple_operation",
            "analysis",
            "multi_step",
            "comparison",
            "synthesis",
            "conflicting_information",
            "decomposable",
            "parallelizable",
        )
    }
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1"))
            await session.commit()
            decision = await assess_expert_reasoning(
                prompts=default_prompts("sv"),
                state={"message": "Förklara detta."},
                jev=_ConnectionProbeJev(answers),
            )
        assert decision.profile == "balanced"
    finally:
        await engine.dispose()


def test_trace_shows_context_message_tools_and_the_model() -> None:
    events = trace_events(
        [
            {"role": "system", "content": "Du är expert."},
            {"role": "user", "content": "Vad gäller?"},
        ],
        [{"type": "function", "function": {"name": "read_source"}}],
        "Jag läser.",
        (PlannedCall("c1", "read_source", {"source_id": "avtal"}),),
        model="Standard · deepseek-flash · balanced",
    )
    assert [event["kind"] for event in events] == [
        "context", "message", "tools", "message", "tool_call",
    ]
    assert events[0]["text"] == "Du är expert."
    assert events[1] == {
        "trace_id": events[1]["trace_id"],
        "kind": "message",
        "role": "user",
        "text": "Vad gäller?",
    }
    assert events[2]["text"] == "read_source"
    assert events[3]["model"] == "Standard · deepseek-flash · balanced"
    assert events[3]["text"] == "Jag läser."
    assert events[4]["name"] == "read_source"
    assert events[4]["arguments"] == {"source_id": "avtal"}


def test_chat_model_label_names_model_and_profile() -> None:
    resolution = LlmResolution(
        view=LlmRuntimeView(
            provider="cerebras",
            model="gpt-oss-120b",
            temperature=None,
            top_p=None,
            max_tokens=1024,
            reasoning_effort="medium",
            api_key="test",
            base_url="https://api.cerebras.ai/v1",
        ),
        prompt_key="chat.mode.interview",
        selection_mode="default",
        selected_configuration_id=None,
        auto_confidence=None,
        reason_code="default",
        fallback=False,
        call_kind="tools",
        speed_class="fast",
    )
    assert chat_model_label(resolution) == "gpt-oss-120b · fast"
    assert chat_model_label(None) == ""
