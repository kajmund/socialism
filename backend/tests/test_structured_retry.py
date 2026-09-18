"""Shared structured-output retry seam and ExpertCompetency fail-close."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.llm import (
    StructuredOutputError,
    complete_structured_retry,
    set_structured_completer,
    set_text_completer,
    validation_category,
)
from app.llm.structured_retry import is_json_syntax_validation_error
from app.services.panel.competency import (
    UNASSESSABLE_PANEL_NOTE,
    UNASSESSABLE_REASON,
    ExpertCompetency,
    assess_expert_competency,
)
from app.services.panel.engine import run_generic_panel
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig, PanelSessionCreate
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.panel.synthesis import GenericPanelSynthesis
from app.services.prompt_catalog import default_prompts


def _truncated_competency_error() -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        ExpertCompetency.model_validate_json('{"has_domain_competence": true, "competence_reason": "Straff')
    return caught.value


def _schema_competency_error() -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        ExpertCompetency.model_validate({"competence_score": 999})
    return caught.value


def _slot() -> PanelExpertSlot:
    return PanelExpertSlot(
        slot_id="crime",
        label="Straffrättsjurist",
        profile="Straffrätt, Brottsbalken och nödvärn",
    )


def _config(*slots: PanelExpertSlot) -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        topic="Vad är rekvisiten för dråp vid självförsvar?",
        brief="Straffrättslig fråga om Brottsbalken 3:2 och nödvärn.",
        max_rounds=1,
        expert_slots=list(slots) or [_slot()],
    )


@pytest.mark.asyncio
async def test_truncated_json_retries_once_then_succeeds(caplog):
    calls = 0

    async def completer(messages, response_model):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise _truncated_competency_error()
        assert any(
            "complete JSON object" in (message.get("content") or "")
            or "komplett JSON" in (message.get("content") or "")
            for message in messages
        )
        return ExpertCompetency(
            has_domain_competence=True,
            competence_reason="Straffrätt är min kompetens.",
        )

    set_structured_completer(completer)
    with caplog.at_level("INFO"):
        parsed = await complete_structured_retry(
            [{"role": "user", "content": "bedöm"}],
            ExpertCompetency,
        )
    assert parsed.has_domain_competence is True
    assert calls == 2
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "schema=ExpertCompetency" in logged
    assert "attempt=1" in logged
    assert "category=json_invalid" in logged
    assert "Straffrätt" not in logged
    assert '{"has_domain_competence"' not in logged


@pytest.mark.asyncio
async def test_finish_reason_length_is_retried(monkeypatch):
    set_structured_completer(None)
    calls = {"n": 0}

    async def fake_create(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"has_domain_competence": true, "competence_reason": "Straff'
                        ),
                        finish_reason="length",
                    )
                ]
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            '{"has_domain_competence": false, "competence_score": 0, '
                            '"competence_reason": "ok"}'
                        )
                    ),
                    finish_reason="stop",
                )
            ]
        )

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    parsed = await complete_structured_retry(
        [{"role": "user", "content": "bedöm"}],
        ExpertCompetency,
    )
    assert parsed.has_domain_competence is False
    assert parsed.competence_reason == "ok"
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_non_json_schema_error_is_not_retried():
    calls = 0

    async def completer(messages, response_model):
        nonlocal calls
        calls += 1
        raise _schema_competency_error()

    set_structured_completer(completer)
    with pytest.raises(ValidationError) as caught:
        await complete_structured_retry(
            [{"role": "user", "content": "bedöm"}],
            ExpertCompetency,
        )
    assert not is_json_syntax_validation_error(caught.value)
    assert validation_category(caught.value) != "json_invalid"
    assert calls == 1


@pytest.mark.asyncio
async def test_timeout_propagates_without_retry():
    calls = 0

    async def completer(messages, response_model):
        nonlocal calls
        calls += 1
        raise TimeoutError("deadline")

    set_structured_completer(completer)
    with pytest.raises(TimeoutError, match="deadline"):
        await complete_structured_retry(
            [{"role": "user", "content": "bedöm"}],
            ExpertCompetency,
        )
    assert calls == 1


@pytest.mark.asyncio
async def test_provider_error_propagates_from_competency():
    calls = 0

    async def completer(messages, response_model):
        nonlocal calls
        calls += 1
        raise RuntimeError("provider 503")

    set_structured_completer(completer)
    with pytest.raises(RuntimeError, match="provider 503"):
        await assess_expert_competency(_slot(), _config(), default_prompts("sv"))
    assert calls == 1


@pytest.mark.asyncio
async def test_two_broken_competency_replies_fail_closed_and_panel_continues(client_db):
    _client, factory = client_db
    calls = 0

    async def structured(messages, response_model):
        nonlocal calls
        if response_model is ExpertCompetency:
            calls += 1
            raise _truncated_competency_error()
        if response_model is GenericPanelSynthesis:
            return GenericPanelSynthesis(summary="Lucka.", claims=[], unanswered=[])
        raise RuntimeError(f"Unexpected structured model {response_model}")

    async def text(messages, *, model=None):
        user = messages[-1]["content"]
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen."
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Fri analys."
        return "Svar"

    set_structured_completer(structured)
    set_text_completer(text)
    prompts = default_prompts("sv")
    async with factory() as db:
        created = await create_panel_session(db, PanelSessionCreate(config=_config()))
        row = await get_panel_session(db, created.id)
        assert row is not None
        await run_generic_panel(db, row, prompts, frozen_evidence=True)
        await db.commit()
        persisted = await get_panel_session(db, created.id)
    assert persisted is not None
    assert calls == 2
    assert persisted.status == "succeeded"
    assert persisted.result is not None
    assert persisted.result["claims"] == []
    assert persisted.result["unanswered"]
    assert UNASSESSABLE_PANEL_NOTE in persisted.result["unanswered"][0]
    assert persisted.result["competency"][0]["competent"] is False
    assert UNASSESSABLE_REASON in persisted.result["competency"][0]["reason"]
    assert persisted.result["unanswered_items"][0]["reason"] == "missing_expertise"
    transcript = persisted.transcript
    assert any(turn["phase"] == "unanswered" for turn in transcript)
    assert not any(turn["phase"] == "expert" for turn in transcript)


@pytest.mark.asyncio
async def test_length_error_is_classified():
    exc = StructuredOutputError("length", finish_reason="length")
    assert exc.category == "length"
    assert exc.finish_reason == "length"
