"""Context-aware STT correction for Socialism live speech."""

from dataclasses import replace

import pytest

from app.services.live_speech_correction import (
    CORRECTION_PROMPT_KEY,
    SttCorrectionDecision,
    conversation_block,
    correct_transcript,
)
from app.services.live_speech_runtime import LiveSpeechRuntime
from app.services.live_speech_scope import LiveSpeechScope
from app.schemas.workspace import WorkspaceState


def test_conversation_block_formats_and_caps_turns() -> None:
    turns = [
        ("user" if i % 2 == 0 else "assistant", f"text-{i}") for i in range(8)
    ]
    block = conversation_block(turns)
    assert "text-7" in block
    assert "text-1" not in block
    assert "Expert: text-7" in block
    assert "User: text-6" in block
    assert conversation_block([]) == ""


@pytest.mark.asyncio
async def test_correct_transcript_applies_a_changed_verdict(monkeypatch) -> None:
    async def fake_complete(messages, response_model, **_kwargs):
        assert response_model is SttCorrectionDecision
        assert messages[0]["role"] == "system"
        assert "Avtalslagen" in messages[1]["content"]
        return SttCorrectionDecision(
            corrected_text="Avtalslagen paragraf tre.",
            changed=True,
        )

    monkeypatch.setattr(
        "app.services.live_speech_correction.complete_structured", fake_complete,
    )
    decision = await correct_transcript(
        "prompt",
        [("user", "Vad gäller?"), ("assistant", "Avtalslagen paragraf tre.")],
        "Avtalslagen paragraf tre",
        timeout=2.0,
    )
    assert decision is not None
    assert decision.corrected_text == "Avtalslagen paragraf tre."
    assert decision.changed is True


@pytest.mark.asyncio
async def test_correct_transcript_returns_none_on_failure_and_empty_prompt(
    monkeypatch,
) -> None:
    from openai import OpenAIError

    async def failing(_messages, _model, **_kwargs):
        raise OpenAIError("provider down")

    monkeypatch.setattr(
        "app.services.live_speech_correction.complete_structured", failing,
    )
    assert await correct_transcript("prompt", [], "text", timeout=2.0) is None
    assert await correct_transcript("", [], "text", timeout=2.0) is None
    assert await correct_transcript("prompt", [], "  ", timeout=2.0) is None


def _correcting_runtime() -> LiveSpeechRuntime:
    runtime = LiveSpeechRuntime.__new__(LiveSpeechRuntime)
    runtime._offline_task = None
    runtime._commit_at = 1.0
    runtime._correction_history = []
    runtime._metrics = _CorrectionMetrics()
    runtime.scope = LiveSpeechScope(
        user_id="user",
        customer_id=1,
        workspace_id="workspace",
        expert_id="expert",
        language="sv",
        voice_id="voice",
        workspace_state=WorkspaceState(expert_id="expert"),
        prompts={CORRECTION_PROMPT_KEY: "prompt"},
        correction_enabled=True,
        correction_timeout=2.0,
    )
    return runtime


class _CorrectionMetrics:
    def add(self, phase: str, milliseconds: float) -> None:
        return None


@pytest.mark.asyncio
async def test_canonical_text_applies_the_correction(monkeypatch) -> None:
    async def fake_correct(prompt, conversation, text, *, timeout):
        assert prompt == "prompt"
        assert conversation == []
        assert timeout == 2.0
        return SttCorrectionDecision(corrected_text="Rättad text.", changed=True)

    monkeypatch.setattr(
        "app.services.live_speech_runtime.correct_transcript", fake_correct,
    )
    runtime = _correcting_runtime()
    assert await runtime._canonical_text("Fel text.") == "Rättad text."


@pytest.mark.asyncio
async def test_canonical_text_skips_correction_when_disabled_or_unchanged(
    monkeypatch,
) -> None:
    calls = 0

    async def fake_correct(_prompt, _conversation, _text, *, timeout):
        nonlocal calls
        calls += 1
        return SttCorrectionDecision(corrected_text="", changed=False)

    monkeypatch.setattr(
        "app.services.live_speech_runtime.correct_transcript", fake_correct,
    )
    runtime = _correcting_runtime()
    assert await runtime._canonical_text("Behåll mig.") == "Behåll mig."
    assert calls == 1

    runtime.scope = replace(runtime.scope, correction_enabled=False)
    assert await runtime._canonical_text("Också behåll mig.") == "Också behåll mig."
    assert calls == 1
