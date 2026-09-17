"""Expertgranskning execution bridge — resume ready research without re-running."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession
from app.llm import set_text_completer, set_tools_completer
from app.services.execution import (
    add_evidence_items,
    create_attempt,
    create_evidence_set,
    create_run,
    freeze_evidence_set,
    get_attempt,
    mark_ready,
)
from app.services.expertgranskning import MODULE_ID
from app.services.expertgranskning.execution import run_expertgranskning_with_research
from app.services.panel.schemas import PanelExpertSlot, PanelSessionConfig
from app.services.research.composition import set_knowledge_vector_store_factory
from app.services.research.models import research_evidence
from tests.conftest import TEST_CUSTOMER_ID


def _panel_config() -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        module=MODULE_ID,
        topic="Höstens kampanjlinje",
        brief="Detta PM föreslår en ny kommunikationslinje.",
        max_rounds=1,
        research_before_review=True,
        expert_slots=[
            PanelExpertSlot(slot_id="legal", label="Jurist", profile="Avtalsrätt"),
        ],
    )


async def _ready_attempt(session: AsyncSession):
    run = await create_run(
        session,
        customer_id=TEST_CUSTOMER_ID,
        module=MODULE_ID,
        title="Höstens kampanjlinje",
        context={"consumer": "expertgranskning"},
    )
    evidence_set = await create_evidence_set(session, run_id=run.id)
    await add_evidence_items(
        session,
        evidence_set_id=evidence_set.id,
        items=[
            research_evidence(
                research_need_id="research_1",
                source_type="customer_knowledge",
                status="found",
                title="Kundunderlag",
                excerpt="Relevant bakgrund för dokumentgranskningen.",
                provider="test",
            )
        ],
    )
    frozen = await freeze_evidence_set(session, evidence_set.id)
    config = _panel_config()
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot=config.model_dump(mode="json"),
        input_snapshot={"topic": config.topic, "brief": config.brief},
        evidence_set_id=frozen.id,
    )
    attempt = await mark_ready(session, attempt.id)
    await session.commit()
    return run, attempt


@pytest.fixture
def mock_panel_llm():
    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            return "JA"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return "Anteckning"
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            return "Inlägg med [E1]."
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Syntes: dokumentet är tydligt."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen."
        return "Svar"

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    set_text_completer(_complete)
    set_tools_completer(_tools)
    yield
    set_text_completer(None)
    set_tools_completer(None)


@pytest.mark.asyncio
async def test_expertgranskning_resumes_ready_attempt_without_research(
    client_db,
    mock_panel_llm,
    monkeypatch,
):
    _client, factory = client_db
    async with factory() as session:
        run, attempt = await _ready_attempt(session)
        config = _panel_config()
        panel = PanelSession(
            id="eg-resume-ready",
            protocol="generic_panel",
            status="failed",
            config={
                **config.model_dump(mode="json"),
                "execution_run_id": run.id,
                "execution_attempt_id": attempt.id,
            },
        )
        session.add(panel)
        await session.commit()

    claim = AsyncMock()
    monkeypatch.setattr(
        "app.services.expertgranskning.execution.run_research_claim",
        claim,
    )

    result_id = await run_expertgranskning_with_research(
        factory,
        session_id="eg-resume-ready",
        customer_id=TEST_CUSTOMER_ID,
    )

    claim.assert_not_awaited()
    assert result_id == attempt.id
    async with factory() as check:
        reloaded_attempt = await get_attempt(check, attempt.id)
    assert reloaded_attempt.status == "completed"


@pytest.mark.asyncio
async def test_expertgranskning_creates_new_attempt_when_prior_failed(
    client_db,
    mock_panel_llm,
    monkeypatch,
):
    _client, factory = client_db
    async with factory() as session:
        run, attempt = await _ready_attempt(session)
        attempt.status = "failed"
        config = _panel_config()
        panel = PanelSession(
            id="eg-new-after-failed",
            protocol="generic_panel",
            status="failed",
            config={
                **config.model_dump(mode="json"),
                "execution_run_id": run.id,
                "execution_attempt_id": attempt.id,
            },
        )
        session.add(panel)
        await session.commit()
        failed_attempt_id = attempt.id

    async def _skip_research(attempt_id: str) -> None:
        async with factory() as inner:
            row = await get_attempt(inner, attempt_id)
            assert row.status == "created"

    monkeypatch.setattr(
        "app.services.expertgranskning.execution.run_research_claim",
        _skip_research,
    )
    set_knowledge_vector_store_factory(lambda: object())
    try:
        with pytest.raises(RuntimeError, match="did not become ready"):
            await run_expertgranskning_with_research(
                factory,
                session_id="eg-new-after-failed",
                customer_id=TEST_CUSTOMER_ID,
            )
    finally:
        set_knowledge_vector_store_factory(None)

    async with factory() as check:
        panel = await check.get(PanelSession, "eg-new-after-failed")
    assert panel is not None
    assert panel.config["execution_attempt_id"] != failed_attempt_id
