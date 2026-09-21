"""Default / fixed / Auto resolution, Jev fallbacks, and ContextVar isolation."""

from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.llm import complete_structured, set_structured_completer
from app.llm.jev import JevError, JevNeedDecision, parse_need_decision
from app.llm.runtime_override import (
    CachedLlmConfiguration,
    LlmRuntimeView,
    PromptLlmAssignmentView,
    current_resolution,
    current_runtime,
    set_runtime_selection_cache,
)
from app.llm.selection import (
    AUTO_REASON_ERROR,
    AUTO_REASON_INVALID,
    AUTO_REASON_LOW_CONFIDENCE,
    AUTO_REASON_NO_MATCH,
    AUTO_REASON_SELECTED,
    AUTO_REASON_UNAVAILABLE,
    TaskNeed,
    match_auto_configuration,
    resolve_llm_runtime,
    set_need_classifier,
)
from app.services.expertgranskning.schemas import WordExpertComment
from app.services.expertgranskning.word_structured import complete_word_structured
from app.services.prompt_catalog import default_prompts
from tests.word_review_helpers import word_expert_comment


def _view(model: str, *, provider: str = "cerebras") -> LlmRuntimeView:
    return LlmRuntimeView(
        provider=provider,
        model=model,
        temperature=0.2,
        top_p=0.9,
        max_tokens=1024,
        reasoning_effort="medium",
        api_key="test-key",
        base_url="https://example.test",
    )


def _config(
    config_id: int,
    *,
    model: str,
    role: str,
    is_default: bool = False,
    vision: bool = False,
    tools: bool = True,
    structured: bool = True,
    long_context: bool = False,
    enabled: bool = True,
    priority: int = 100,
) -> CachedLlmConfiguration:
    return CachedLlmConfiguration(
        id=config_id,
        name=f"config-{config_id}",
        is_default=is_default,
        selection_role=role,  # type: ignore[arg-type]
        capability_vision=vision,
        capability_tools=tools,
        capability_structured_output=structured,
        capability_long_context=long_context,
        enabled_for_auto=enabled,
        priority=priority,
        view=_view(model),
    )


@pytest.fixture(autouse=True)
def _selection_isolation():
    previous_key = settings.typesafe_api_key
    previous_threshold = settings.jev_confidence_threshold
    set_runtime_selection_cache(
        assignments={},
        configurations={},
        default_configuration_id=None,
    )
    set_need_classifier(None)
    set_structured_completer(None)
    yield
    settings.typesafe_api_key = previous_key
    settings.jev_confidence_threshold = previous_threshold
    set_need_classifier(None)
    set_structured_completer(None)
    set_runtime_selection_cache(
        assignments={},
        configurations={},
        default_configuration_id=None,
    )


def _install_catalog() -> dict[int, CachedLlmConfiguration]:
    configs = {
        1: _config(1, model="gpt-oss-120b", role="balanced", is_default=True),
        2: _config(2, model="qwen-3.8-27b", role="fast", vision=True, priority=10),
        3: _config(3, model="deepseek-v4-pro", role="deep", long_context=True, priority=20),
        4: _config(4, model="deepseek-flash", role="fast", vision=True, priority=50),
    }
    set_runtime_selection_cache(
        assignments={
            "help.system": PromptLlmAssignmentView(mode="default", configuration_id=None),
            "panel.expert.system": PromptLlmAssignmentView(
                mode="fixed", configuration_id=3
            ),
            "expertgranskning.word.expert.comment": PromptLlmAssignmentView(
                mode="fixed", configuration_id=3
            ),
            "expertgranskning.word.structured_retry": PromptLlmAssignmentView(
                mode="fixed", configuration_id=2
            ),
            "research.planner.system": PromptLlmAssignmentView(
                mode="auto", configuration_id=1
            ),
        },
        configurations=configs,
        default_configuration_id=1,
    )
    return configs


def test_match_auto_filters_capabilities_then_role_then_priority():
    configs = [
        _config(2, model="qwen-3.8-27b", role="fast", vision=True, priority=10),
        _config(4, model="deepseek-flash", role="fast", vision=True, priority=50),
        _config(5, model="no-vision", role="fast", vision=False, priority=1),
    ]
    matched = match_auto_configuration(
        TaskNeed(
            speed_class="fast",
            needs_vision=True,
            needs_tools=False,
            needs_structured_output=True,
            needs_long_context=False,
            confidence=0.9,
        ),
        configs,
    )
    assert matched is not None
    assert matched.id == 2


def test_match_auto_returns_none_when_role_missing():
    matched = match_auto_configuration(
        TaskNeed(
            speed_class="deep",
            needs_vision=False,
            needs_tools=False,
            needs_structured_output=True,
            needs_long_context=False,
            confidence=0.9,
        ),
        [_config(2, model="qwen-3.8-27b", role="fast")],
    )
    assert matched is None


@pytest.mark.asyncio
async def test_resolve_default_and_fixed():
    _install_catalog()
    defaulted = await resolve_llm_runtime(
        prompt_key="help.system",
        messages=[{"role": "user", "content": "hej"}],
        call_kind="text",
    )
    assert defaulted.selection_mode == "default"
    assert defaulted.selected_configuration_id == 1
    assert defaulted.view.model == "gpt-oss-120b"
    assert defaulted.fallback is False

    fixed = await resolve_llm_runtime(
        prompt_key="panel.expert.system",
        messages=[{"role": "user", "content": "kommentera"}],
        call_kind="structured",
    )
    assert fixed.selection_mode == "fixed"
    assert fixed.selected_configuration_id == 3
    assert fixed.view.model == "deepseek-v4-pro"


class _FakeNeedClassifier:
    def __init__(self, decision: JevNeedDecision | Exception) -> None:
        self.decision = decision
        self.calls = 0

    async def classify(self, **_kwargs):
        self.calls += 1
        if isinstance(self.decision, Exception):
            raise self.decision
        return self.decision


@pytest.mark.asyncio
async def test_resolve_auto_matches_jev_need():
    _install_catalog()
    set_need_classifier(
        _FakeNeedClassifier(
            JevNeedDecision(
                speed_class="fast",
                needs_vision=True,
                needs_tools=False,
                needs_structured_output=True,
                needs_long_context=False,
                confidence=0.91,
            )
        )
    )
    resolution = await resolve_llm_runtime(
        prompt_key="research.planner.system",
        messages=[{"role": "user", "content": "planera"}],
        call_kind="structured",
    )
    assert resolution.reason_code == AUTO_REASON_SELECTED
    assert resolution.selected_configuration_id == 2
    assert resolution.view.model == "qwen-3.8-27b"
    assert resolution.auto_confidence == 0.91
    assert resolution.fallback is False


@pytest.mark.asyncio
async def test_resolve_auto_falls_back_on_low_confidence_and_errors():
    _install_catalog()
    settings.jev_confidence_threshold = 0.7
    set_need_classifier(
        _FakeNeedClassifier(
            JevNeedDecision(
                speed_class="deep",
                needs_vision=False,
                needs_tools=False,
                needs_structured_output=True,
                needs_long_context=False,
                confidence=0.2,
            )
        )
    )
    low = await resolve_llm_runtime(
        prompt_key="research.planner.system",
        messages=[{"role": "user", "content": "planera"}],
        call_kind="structured",
    )
    assert low.reason_code == AUTO_REASON_LOW_CONFIDENCE
    assert low.selected_configuration_id == 1
    assert low.fallback is True

    set_need_classifier(_FakeNeedClassifier(JevError("invalid Jev speed_class: 'turbo'")))
    invalid = await resolve_llm_runtime(
        prompt_key="research.planner.system",
        messages=[{"role": "user", "content": "planera"}],
        call_kind="structured",
    )
    assert invalid.reason_code == AUTO_REASON_INVALID
    assert invalid.selected_configuration_id == 1

    set_need_classifier(_FakeNeedClassifier(JevError("TYPESAFE_API_KEY is not configured")))
    missing = await resolve_llm_runtime(
        prompt_key="research.planner.system",
        messages=[{"role": "user", "content": "planera"}],
        call_kind="structured",
    )
    assert missing.reason_code == AUTO_REASON_UNAVAILABLE

    set_need_classifier(_FakeNeedClassifier(RuntimeError("boom")))
    errored = await resolve_llm_runtime(
        prompt_key="research.planner.system",
        messages=[{"role": "user", "content": "planera"}],
        call_kind="structured",
    )
    assert errored.reason_code == AUTO_REASON_ERROR

    set_need_classifier(
        _FakeNeedClassifier(
            JevNeedDecision(
                speed_class="deep",
                needs_vision=True,
                needs_tools=False,
                needs_structured_output=True,
                needs_long_context=False,
                confidence=0.95,
            )
        )
    )
    unmatched = await resolve_llm_runtime(
        prompt_key="research.planner.system",
        messages=[{"role": "user", "content": "planera"}],
        call_kind="structured",
    )
    assert unmatched.reason_code == AUTO_REASON_NO_MATCH
    assert unmatched.selected_configuration_id == 1


@pytest.mark.asyncio
async def test_concurrent_auto_resolutions_do_not_leak_runtime():
    _install_catalog()

    class _ByMessage:
        async def classify(self, *, messages, **_kwargs):
            text = str(messages[0]["content"])
            role = "fast" if text == "fast-task" else "deep"
            return JevNeedDecision(
                speed_class=role,
                needs_vision=False,
                needs_tools=False,
                needs_structured_output=True,
                needs_long_context=role == "deep",
                confidence=0.93,
            )

    set_need_classifier(_ByMessage())

    async def run(content: str, expected_model: str, expected_id: int) -> None:
        resolution = await resolve_llm_runtime(
            prompt_key="research.planner.system",
            messages=[{"role": "user", "content": content}],
            call_kind="structured",
        )
        assert resolution.selected_configuration_id == expected_id
        from app.llm.runtime_override import bound_llm_resolution, bound_llm_runtime

        with bound_llm_runtime(resolution.view), bound_llm_resolution(resolution):
            await asyncio.sleep(0.02)
            assert current_runtime().model == expected_model
            assert current_resolution() is not None
            assert current_resolution().selected_configuration_id == expected_id

    await asyncio.gather(
        run("fast-task", "qwen-3.8-27b", 2),
        run("deep-task", "deepseek-v4-pro", 3),
    )


def test_parse_need_decision_rejects_unknown_speed_class():
    with pytest.raises(JevError, match="speed_class"):
        parse_need_decision(
            {
                "answers": {
                    "speed_class": {"choice": "turbo", "confidence": 0.9},
                    "needs_vision": {"noul": 0.1},
                    "needs_tools": {"noul": 0.1},
                    "needs_structured_output": {"noul": 0.9},
                    "needs_long_context": {"noul": 0.1},
                }
            }
        )


@pytest.mark.asyncio
async def test_word_structured_uses_task_prompt_key_not_retry_key():
    _install_catalog()
    seen: list[str] = []

    async def completer(_messages, _model):
        seen.append(current_runtime().model)
        return word_expert_comment(kommentar="ok", anchor_paragraph_index=1)

    set_structured_completer(completer)
    parsed = await complete_word_structured(
        [{"role": "user", "content": "kommentera"}],
        WordExpertComment,
        prompt_key="expertgranskning.word.expert.comment",
        prompts=default_prompts("sv"),
    )
    assert parsed.kommentar == "ok"
    assert seen == ["deepseek-v4-pro"]


@pytest.mark.asyncio
async def test_complete_structured_records_selection_on_stats():
    _install_catalog()
    from app.llm import LLMCallStats, bind_usage_recorder, reset_usage_recorder

    recorded: list[LLMCallStats] = []
    token = bind_usage_recorder(recorded.append)

    async def completer(_messages, _model):
        return word_expert_comment(kommentar="ok", anchor_paragraph_index=1)

    set_structured_completer(completer)
    try:
        await complete_structured(
            [{"role": "user", "content": "x"}],
            WordExpertComment,
            prompt_key="panel.expert.system",
        )
    finally:
        reset_usage_recorder(token)
    # Injected completers skip provider stats; resolution still binds for later calls.
    resolution = await resolve_llm_runtime(
        prompt_key="panel.expert.system",
        messages=[{"role": "user", "content": "x"}],
        call_kind="structured",
    )
    assert resolution.selected_configuration_id == 3
    assert resolution.selection_mode == "fixed"
