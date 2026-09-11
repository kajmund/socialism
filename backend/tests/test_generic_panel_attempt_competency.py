"""Frozen-evidence Attempts must competency-gate without running ResearchPlan."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Kund, PanelSession
from app.llm import set_structured_completer, set_text_completer, set_tools_completer
from app.services.execution import (
    add_evidence_items,
    create_attempt,
    create_evidence_set,
    create_run,
    freeze_evidence_set,
    get_attempt,
    mark_ready,
)
from app.services.panel.attempt_execution import execute_generic_panel_attempt
from app.services.panel.competency import ExpertCompetency
from app.services.panel.research import empty_research_structured
from app.services.panel.result import MISSING_EXPERTISE_REASON
from app.services.panel.synthesis import GenericPanelSynthesis, SynthesizedClaim
from app.services.prompt_catalog import default_prompts
from app.services.research.models import research_evidence

PROMPTS = default_prompts("sv")
CRIMINAL_QUESTION = "Vad är rekvisiten för dråp vid självförsvar?"

WRONG_PANEL = {
    "topic": CRIMINAL_QUESTION,
    "brief": "Straffrättslig fråga om Brottsbalken 3:2 och nödvärn.",
    "max_rounds": 1,
    "expert_slots": [
        {
            "slot_id": "dd",
            "label": "Nils",
            "profile": "Due diligence / M&A-transaktioner",
        },
        {
            "slot_id": "val",
            "label": "Rolf",
            "profile": "Bolagsvärdering och finansiell analys",
        },
        {
            "slot_id": "mkt",
            "label": "Mira",
            "profile": "Marknadsanalys och konkurrens",
        },
        {
            "slot_id": "pmo",
            "label": "Pia",
            "profile": "PMO, ERP och integrationsprocesser",
        },
    ],
}

CRIME_SLOT = {
    "slot_id": "crime",
    "label": "Straffrättsjurist",
    "profile": "Straffrätt, Brottsbalken och nödvärn",
}

CRIMINAL_EXCERPT = (
    "Brottsbalken 3 kap. 2 § dråp. Nödvärn enligt 24 kap. 1 §. "
    "Rekvisit: uppsåt, gärning och att nödvärn inte är uppenbart oförsvarligt."
)


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _ready_criminal_attempt(session: AsyncSession, *, slug: str, config: dict):
    kund = Kund(name=slug, slug=slug, available_modules=["dd"])
    session.add(kund)
    await session.flush()
    run = await create_run(
        session, customer_id=kund.id, module="dd", title="Dråp"
    )
    evidence_set = await create_evidence_set(session, run_id=run.id)
    await add_evidence_items(
        session,
        evidence_set_id=evidence_set.id,
        items=[
            research_evidence(
                research_need_id="research_1",
                source_type="swedish_law",
                status="found",
                title="Straffrätt — dråp och nödvärn",
                excerpt=CRIMINAL_EXCERPT,
                locator="BrB 3:2",
                source_id="brb-3-2",
                source_url="https://example.test/brb",
                provider="swedish_law",
                score=0.99,
                retrieved_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
                metadata={"document_id": "do-not-leak"},
            )
        ],
    )
    frozen = await freeze_evidence_set(session, evidence_set.id)
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot=config,
        input_snapshot={"question": CRIMINAL_QUESTION},
        evidence_set_id=frozen.id,
    )
    attempt = await mark_ready(session, attempt.id)
    await session.commit()
    return attempt


def _competency_for_label(
    identity: str,
    mapping: dict[str, ExpertCompetency],
) -> ExpertCompetency:
    for label, decision in mapping.items():
        if f"som {label} i en expertpanel" in identity:
            return decision
    return ExpertCompetency(
        has_domain_competence=False,
        competence_reason="missing expertise / requires domain expert",
    )


def _install_attempt_llm(
    *,
    competency: dict[str, ExpertCompetency] | ExpertCompetency,
    raise_replies: dict[str, str] | str = "JA",
    scratchpad: str = "Rekvisit: uppsåt, gärning och nödvärn.",
    expert_turns: dict[str, str] | str = "Rekvisiten följer BrB 3:2 och 24:1.",
    unanswered: str = "Huvudfrågan är unanswered: missing expertise. Kräver straffrätt.",
    synthesis: GenericPanelSynthesis | None = None,
    captured: list[list[dict]] | None = None,
) -> None:
    async def _complete(messages, *, model=None):
        if captured is not None:
            captured.append([dict(item) for item in messages])
        user = messages[-1]["content"]
        identity = "".join(
            item["content"] for item in messages if item.get("role") == "system"
        )
        if "JA eller NEJ" in user or "YES or NO" in user:
            if isinstance(raise_replies, str):
                return raise_replies
            for label, reply in raise_replies.items():
                if f"som {label} i en expertpanel" in identity:
                    return reply
            return "JA"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return scratchpad
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            if isinstance(expert_turns, str):
                return expert_turns
            for label, reply in expert_turns.items():
                if f"som {label} i en expertpanel" in identity:
                    return reply
            return "Sakbedömning."
        if "missing expertise" in user and "Ingen expert" in user:
            return unanswered
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Fri analys."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen. Vad är rekvisiten för dråp vid självförsvar?"
        return "Svar"

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    async def _structured(messages, response_model):
        if captured is not None:
            captured.append([dict(item) for item in messages])
        if response_model is ExpertCompetency:
            if isinstance(competency, ExpertCompetency):
                return competency
            identity = "".join(
                item["content"] for item in messages if item.get("role") == "system"
            )
            return _competency_for_label(identity, competency)
        if response_model is GenericPanelSynthesis:
            return synthesis or GenericPanelSynthesis(
                summary="Lucka.",
                claims=[
                    SynthesizedClaim(
                        claim="Rekvisiten är uppsåt och gärning.",
                        evidence="Fryst underlag [E1].",
                        judgment="Fabricerad slutsats utan kompetent expert.",
                    )
                ],
                unanswered=[],
            )
        empty = empty_research_structured(response_model)
        if empty is not None:
            raise AssertionError("research-plan models must not run on this path")
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_completer(_complete)
    set_tools_completer(_tools)
    set_structured_completer(_structured)


def _incompetent(reason: str = "missing expertise / requires domain expert") -> ExpertCompetency:
    return ExpertCompetency(has_domain_competence=False, competence_reason=reason)


def _competent(reason: str = "Straffrätt är min kärnkompetens.") -> ExpertCompetency:
    return ExpertCompetency(has_domain_competence=True, competence_reason=reason)


def _wrong_competency() -> dict[str, ExpertCompetency]:
    fake = _incompetent()
    return {"Nils": fake, "Rolf": fake, "Mira": fake, "Pia": fake}


def _phases(panel: PanelSession) -> list[str]:
    return [row["phase"] for row in panel.transcript]


def _turns(panel: PanelSession, phase: str) -> list[dict]:
    return [row for row in panel.transcript if row["phase"] == phase]


def _competency_blobs(captured: list[list[dict]]) -> list[str]:
    blobs: list[str] = []
    for batch in captured:
        user = batch[-1]["content"]
        if "has_domain_competence" in user and "Din profil" in user:
            blobs.append("\n".join(item["content"] for item in batch))
    return blobs


@pytest.mark.asyncio
async def test_frozen_wrong_panel_is_missing_expertise_not_failed(db):
    captured: list[list[dict]] = []
    _install_attempt_llm(competency=_wrong_competency(), captured=captured)
    attempt = await _ready_criminal_attempt(db, slug="wrong-co", config=WRONG_PANEL)

    result = await execute_generic_panel_attempt(
        db, attempt_id=attempt.id, prompts=PROMPTS
    )
    reloaded = await get_attempt(db, attempt.id)
    panel = await db.get(PanelSession, result.panel_session_id)

    assert result.status == "completed"
    assert reloaded.status == "completed"
    assert panel is not None
    assert "research_need" not in _phases(panel)
    assert "research_plan" not in _phases(panel)
    assert _turns(panel, "raise_hand") == []
    assert _turns(panel, "scratchpad") == []
    assert _turns(panel, "expert") == []
    assert result.panel_result is not None
    assert result.panel_result.claims == []
    assert result.panel_result.competency
    assert all(not row.competent for row in result.panel_result.competency)
    reasons = [item.reason for item in result.panel_result.unanswered_items]
    assert MISSING_EXPERTISE_REASON in reasons
    assert any("missing expertise" in note for note in result.panel_result.unanswered)
    for blob in _competency_blobs(captured):
        assert CRIMINAL_EXCERPT not in blob
        assert "[E1]" not in blob


@pytest.mark.asyncio
async def test_frozen_criminal_lawyer_is_competent(db):
    _install_attempt_llm(
        competency={"Straffrättsjurist": _competent()},
        synthesis=GenericPanelSynthesis(
            summary="Straffrättsexperten identifierade rekvisiten.",
            claims=[
                SynthesizedClaim(
                    claim="Rekvisiten följer BrB 3:2 och 24:1.",
                    evidence="Expertens tur och [E1].",
                    judgment="Bedömd slutsats.",
                    evidence_refs=["E1"],
                )
            ],
            unanswered=[],
        ),
    )
    config = {
        **WRONG_PANEL,
        "expert_slots": [CRIME_SLOT],
    }
    attempt = await _ready_criminal_attempt(db, slug="crime-co", config=config)

    result = await execute_generic_panel_attempt(
        db, attempt_id=attempt.id, prompts=PROMPTS
    )
    panel = await db.get(PanelSession, result.panel_session_id)
    assert result.status == "completed"
    assert panel is not None
    assert [turn["content"] for turn in _turns(panel, "raise_hand")] == ["JA"]
    assert _turns(panel, "expert")
    assert _turns(panel, "unanswered") == []
    assert result.panel_result is not None
    assert result.panel_result.competency[0].competent is True
    assert not any(
        item.reason == MISSING_EXPERTISE_REASON
        for item in result.panel_result.unanswered_items
    )


@pytest.mark.asyncio
async def test_frozen_mixed_panel_only_criminal_lawyer_is_eligible(db):
    captured: list[list[dict]] = []
    _install_attempt_llm(
        competency={
            **_wrong_competency(),
            "Straffrättsjurist": _competent(),
        },
        raise_replies="JA",
        captured=captured,
        synthesis=GenericPanelSynthesis(
            summary="Bara straffrättsexperten bedömde.",
            claims=[],
            unanswered=[],
        ),
    )
    config = {
        **WRONG_PANEL,
        "expert_slots": [*WRONG_PANEL["expert_slots"], CRIME_SLOT],
    }
    attempt = await _ready_criminal_attempt(db, slug="mixed-co", config=config)

    result = await execute_generic_panel_attempt(
        db, attempt_id=attempt.id, prompts=PROMPTS
    )
    panel = await db.get(PanelSession, result.panel_session_id)
    assert panel is not None
    raise_hands = _turns(panel, "raise_hand")
    assert [turn["slot_id"] for turn in raise_hands] == ["crime"]
    assert [turn["slot_id"] for turn in _turns(panel, "scratchpad")] == ["crime"]
    assert [turn["slot_id"] for turn in _turns(panel, "expert")] == ["crime"]
    assert result.panel_result is not None
    competent = {row.slot_id for row in result.panel_result.competency if row.competent}
    assert competent == {"crime"}
    assert not any(
        item.reason == MISSING_EXPERTISE_REASON
        for item in result.panel_result.unanswered_items
    )
    blob = "\n".join(item["content"] for batch in captured for item in batch)
    assert "privata anteckningar" in blob or "private notes" in blob.lower()


@pytest.mark.asyncio
async def test_competent_raise_nej_is_not_missing_expertise(db):
    _install_attempt_llm(
        competency={"Straffrättsjurist": _competent()},
        raise_replies="NEJ",
        synthesis=GenericPanelSynthesis(
            summary="Kompetent expert avstod.",
            claims=[],
            unanswered=["Ingen expert valde att svara."],
        ),
    )
    config = {**WRONG_PANEL, "expert_slots": [CRIME_SLOT]}
    attempt = await _ready_criminal_attempt(db, slug="abstain-co", config=config)

    result = await execute_generic_panel_attempt(
        db, attempt_id=attempt.id, prompts=PROMPTS
    )
    panel = await db.get(PanelSession, result.panel_session_id)
    assert result.status == "completed"
    assert panel is not None
    assert [turn["content"] for turn in _turns(panel, "raise_hand")] == ["NEJ"]
    assert _turns(panel, "scratchpad") == []
    assert _turns(panel, "expert") == []
    assert _turns(panel, "unanswered") == []
    assert result.panel_result is not None
    assert result.panel_result.competency[0].competent is True
    assert result.panel_result.unanswered == ["Ingen expert valde att svara."]
    assert not any(
        item.reason == MISSING_EXPERTISE_REASON
        for item in result.panel_result.unanswered_items
    )
