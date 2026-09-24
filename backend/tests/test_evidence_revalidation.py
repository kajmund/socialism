"""Frozen EvidenceSets are revalidated; the snapshot is not mutated."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.models import (
    CanonicalDocumentRecord,
    DocumentVersionRecord,
    EvidenceSetItem,
    EvidenceSetRevalidation,
    Kund,
    TextUnitRecord,
)
from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.execution import (
    add_evidence_items,
    create_evidence_set,
    create_run,
    freeze_evidence_set,
    get_evidence_set,
)
from app.services.knowledge.claims import (
    KnowledgeClaim,
    answer_research_need,
    knowledge_claim_id,
    persist_knowledge_claim,
)
from app.services.knowledge.events import CLAIM_ADDED, list_graph_events
from app.services.knowledge.revalidation import (
    REVALIDATION_CLEAR,
    REVALIDATION_IMPACTED,
    REVALIDATION_REQUIRED,
    REVALIDATION_UNKNOWN,
    RevalidationError,
    classify_revalidation_state,
    revalidate_after_event,
)
from app.services.research import research_evidence
from app.services.research.knowledge_question import research_question_key

QUESTION = "Jämkades villkoret enligt 36 §?"


class _ImpactJev:
    def __init__(self, noul: float) -> None:
        self.noul = noul
        self.calls = 0

    async def ask(self, *, state, questions, model, timeout_seconds):
        del state, questions, model, timeout_seconds
        self.calls += 1
        return JevSystemOneResult(
            answers={"material_change": {"noul": self.noul}},
            model="jev-test",
            latency_ms=1.0,
            input_chars=1,
            usage=JevUsage(),
            raw={},
        )


class _FailingJev:
    async def ask(self, *, state, questions, model, timeout_seconds):
        del state, questions, model, timeout_seconds
        raise JevClientError("jev down", category="transport")


class _InvalidJev:
    def __init__(self, answers: dict) -> None:
        self.answers = answers
        self.calls = 0

    async def ask(self, *, state, questions, model, timeout_seconds):
        del state, questions, model, timeout_seconds
        self.calls += 1
        return JevSystemOneResult(
            answers=self.answers,
            model="jev-test",
            latency_ms=1.0,
            input_chars=1,
            usage=JevUsage(),
            raw={},
        )


DEFAULT_BANDS = {"impact_threshold": 0.75, "clear_threshold": 0.25}


@pytest.mark.parametrize(
    ("noul", "expected"),
    [
        (0.75, REVALIDATION_IMPACTED),
        (1.0, REVALIDATION_IMPACTED),
        (0.749999, REVALIDATION_REQUIRED),
        (0.5, REVALIDATION_REQUIRED),
        (0.250001, REVALIDATION_REQUIRED),
        (0.25, REVALIDATION_CLEAR),
        (0.0, REVALIDATION_CLEAR),
        (float("nan"), REVALIDATION_UNKNOWN),
        (-0.01, REVALIDATION_UNKNOWN),
        (1.01, REVALIDATION_UNKNOWN),
    ],
)
def test_revalidation_bands_use_conservative_thresholds(noul, expected):
    assert classify_revalidation_state(noul, **DEFAULT_BANDS) == expected


def test_custom_thresholds_move_the_uncertain_band():
    assert (
        classify_revalidation_state(0.6, impact_threshold=0.9, clear_threshold=0.1)
        == REVALIDATION_REQUIRED
    )
    assert (
        classify_revalidation_state(0.6, impact_threshold=0.55, clear_threshold=0.2)
        == REVALIDATION_IMPACTED
    )
    with pytest.raises(RevalidationError, match="below"):
        classify_revalidation_state(0.5, impact_threshold=0.25, clear_threshold=0.25)


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


async def _setup_frozen_set(session: AsyncSession, *, excerpt: str = "old holding"):
    kund = Kund(name="acme", slug="acme-rev", available_modules=["dd"])
    session.add(kund)
    await session.flush()
    session.add(
        CanonicalDocumentRecord(
            id="doc-a",
            customer_id=kund.id,
            source_type="upload",
            canonical_uri="doc://a",
            title="A",
            extra={},
        )
    )
    session.add(
        DocumentVersionRecord(
            id="ver-a",
            document_id="doc-a",
            content_hash="hash",
            mime_type="text/plain",
            extra={},
        )
    )
    session.add(
        TextUnitRecord(
            id="tu-hold",
            document_version_id="ver-a",
            document_id="doc-a",
            section_id=None,
            ordinal=0,
            text="HD ansåg X",
            content_hash="tu-hold",
        )
    )
    session.add(
        TextUnitRecord(
            id="tu-other",
            document_version_id="ver-a",
            document_id="doc-a",
            section_id=None,
            ordinal=1,
            text="Irrelevant passage",
            content_hash="tu-other",
        )
    )
    await session.flush()
    run = await create_run(
        session,
        customer_id=kund.id,
        module="dd",
        title="Jämkning",
        context={"case_id": "case-1"},
    )
    evidence_set = await create_evidence_set(session, run_id=run.id)
    await add_evidence_items(
        session,
        evidence_set_id=evidence_set.id,
        items=[
            research_evidence(
                research_need_id="need-1",
                source_type="swedish_case_law",
                status="found",
                excerpt=excerpt,
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                metadata={
                    "answered_by_question_key": research_question_key(QUESTION),
                    "knowledge_claim_ids": ["prior-claim"],
                    "text_unit_ids": ["tu-hold"],
                },
            )
        ],
    )
    frozen = await freeze_evidence_set(session, evidence_set.id)
    return kund, frozen


async def _new_claim(session: AsyncSession, customer_id: int) -> str:
    value: dict[str, object] = {"value": False}
    claim = KnowledgeClaim(
        id=knowledge_claim_id(
            document_version_id="ver-a",
            predicate="legal.adjustment_granted",
            value=value,
        ),
        customer_id=customer_id,
        document_id="doc-a",
        document_version_id="ver-a",
        predicate="legal.adjustment_granted",
        value=value,
        supporting_text_unit_ids=("tu-hold",),
    )
    await persist_knowledge_claim(session, claim)
    await answer_research_need(
        session,
        research_need_id="need-2",
        question_key=research_question_key(QUESTION),
        claim_ids=[claim.id],
        source_type="swedish_case_law",
    )
    return claim.id


@pytest.mark.asyncio
async def test_jev_impact_marks_frozen_set_without_mutating_items(db):
    kund, frozen = await _setup_frozen_set(db)
    await _new_claim(db, kund.id)
    events = await list_graph_events(db, customer_id=kund.id, node_kind="claim")
    added = next(event for event in events if event.event_type == CLAIM_ADDED)
    before = list((await db.execute(select(EvidenceSetItem))).scalars().all())
    gate = _ImpactJev(0.81)
    decisions = await revalidate_after_event(db, added.id, jev=gate)
    after = list((await db.execute(select(EvidenceSetItem))).scalars().all())
    reloaded = await get_evidence_set(db, frozen.id)
    rows = list((await db.execute(select(EvidenceSetRevalidation))).scalars().all())
    assert gate.calls == 1
    assert [item.state for item in decisions] == [REVALIDATION_IMPACTED]
    assert decisions[0].evidence_set_id == frozen.id
    assert [row.state for row in rows] == [REVALIDATION_IMPACTED]
    assert reloaded.status == "frozen"
    assert reloaded.graph_revision_at_freeze == reloaded.frozen_at
    assert [item.excerpt for item in before] == [item.excerpt for item in after]


@pytest.mark.asyncio
async def test_low_impact_is_clear_and_unrelated_claim_skips_jev(db):
    kund, frozen = await _setup_frozen_set(db)
    await _new_claim(db, kund.id)
    events = await list_graph_events(db, customer_id=kund.id, node_kind="claim")
    added = next(event for event in events if event.event_type == CLAIM_ADDED)
    clear_gate = _ImpactJev(0.12)
    decisions = await revalidate_after_event(db, added.id, jev=clear_gate)
    assert [item.state for item in decisions] == [REVALIDATION_CLEAR]
    assert decisions[0].evidence_set_id == frozen.id

    other = KnowledgeClaim(
        id=knowledge_claim_id(
            document_version_id="ver-a",
            predicate="other.topic",
            value={"value": "nope"},
        ),
        customer_id=kund.id,
        document_id="doc-a",
        document_version_id="ver-a",
        predicate="other.topic",
        value={"value": "nope"},
        supporting_text_unit_ids=("tu-other",),
    )
    await persist_knowledge_claim(db, other)
    await answer_research_need(
        db,
        research_need_id="need-other",
        question_key=research_question_key("Helt annan fråga?"),
        claim_ids=[other.id],
        source_type="swedish_case_law",
    )
    other_events = await list_graph_events(
        db, customer_id=kund.id, node_kind="claim", node_id=other.id
    )
    unused = _ImpactJev(0.99)
    assert await revalidate_after_event(db, other_events[0].id, jev=unused) == []
    assert unused.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("noul", "expected"),
    [
        (0.75, REVALIDATION_IMPACTED),
        (0.25, REVALIDATION_CLEAR),
    ],
)
async def test_exact_threshold_scores_use_closed_bands(db, noul, expected):
    kund, _frozen = await _setup_frozen_set(db)
    await _new_claim(db, kund.id)
    events = await list_graph_events(db, customer_id=kund.id, node_kind="claim")
    added = next(event for event in events if event.event_type == CLAIM_ADDED)
    decisions = await revalidate_after_event(db, added.id, jev=_ImpactJev(noul))
    assert [item.state for item in decisions] == [expected]
    assert decisions[0].impact_noul == noul


@pytest.mark.asyncio
async def test_configured_thresholds_are_used(db):
    kund, _frozen = await _setup_frozen_set(db)
    await _new_claim(db, kund.id)
    events = await list_graph_events(db, customer_id=kund.id, node_kind="claim")
    added = next(event for event in events if event.event_type == CLAIM_ADDED)
    previous = (
        settings.revalidation_impact_threshold,
        settings.revalidation_clear_threshold,
    )
    settings.revalidation_impact_threshold = 0.9
    settings.revalidation_clear_threshold = 0.1
    try:
        decisions = await revalidate_after_event(db, added.id, jev=_ImpactJev(0.8))
    finally:
        (
            settings.revalidation_impact_threshold,
            settings.revalidation_clear_threshold,
        ) = previous
    assert [item.state for item in decisions] == [REVALIDATION_REQUIRED]


@pytest.mark.asyncio
async def test_uncertain_band_requires_revalidation(db):
    kund, frozen = await _setup_frozen_set(db)
    await _new_claim(db, kund.id)
    events = await list_graph_events(db, customer_id=kund.id, node_kind="claim")
    added = next(event for event in events if event.event_type == CLAIM_ADDED)
    before = list((await db.execute(select(EvidenceSetItem))).scalars().all())
    decisions = await revalidate_after_event(db, added.id, jev=_ImpactJev(0.5))
    after = list((await db.execute(select(EvidenceSetItem))).scalars().all())
    rows = list((await db.execute(select(EvidenceSetRevalidation))).scalars().all())
    assert [item.state for item in decisions] == [REVALIDATION_REQUIRED]
    assert decisions[0].impact_noul == 0.5
    assert [row.state for row in rows] == [REVALIDATION_REQUIRED]
    assert (await get_evidence_set(db, frozen.id)).status == "frozen"
    assert [item.excerpt for item in before] == [item.excerpt for item in after]


@pytest.mark.asyncio
async def test_jev_failure_is_unknown_never_clear(db):
    kund, frozen = await _setup_frozen_set(db)
    await _new_claim(db, kund.id)
    events = await list_graph_events(db, customer_id=kund.id, node_kind="claim")
    added = next(event for event in events if event.event_type == CLAIM_ADDED)
    before = list((await db.execute(select(EvidenceSetItem))).scalars().all())
    decisions = await revalidate_after_event(db, added.id, jev=_FailingJev())
    after = list((await db.execute(select(EvidenceSetItem))).scalars().all())
    rows = list((await db.execute(select(EvidenceSetRevalidation))).scalars().all())
    assert [item.state for item in decisions] == [REVALIDATION_UNKNOWN]
    assert decisions[0].impact_noul is None
    assert [row.state for row in rows] == [REVALIDATION_UNKNOWN]
    assert REVALIDATION_CLEAR not in {row.state for row in rows}
    assert (await get_evidence_set(db, frozen.id)).status == "frozen"
    assert [item.excerpt for item in before] == [item.excerpt for item in after]
    with pytest.raises(RevalidationError, match="missing"):
        await revalidate_after_event(db, "missing-event", jev=_ImpactJev(0.9))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answers",
    [
        {},
        {"material_change": {}},
        {"material_change": {"noul": "nope"}},
        {"material_change": {"noul": 1.5}},
        {"material_change": {"noul": float("nan")}},
    ],
)
async def test_invalid_jev_response_is_unknown_never_clear(db, answers):
    kund, frozen = await _setup_frozen_set(db)
    await _new_claim(db, kund.id)
    events = await list_graph_events(db, customer_id=kund.id, node_kind="claim")
    added = next(event for event in events if event.event_type == CLAIM_ADDED)
    gate = _InvalidJev(answers)
    decisions = await revalidate_after_event(db, added.id, jev=gate)
    rows = list((await db.execute(select(EvidenceSetRevalidation))).scalars().all())
    assert gate.calls == 1
    assert [item.state for item in decisions] == [REVALIDATION_UNKNOWN]
    assert decisions[0].impact_noul is None
    assert [row.state for row in rows] == [REVALIDATION_UNKNOWN]
    assert REVALIDATION_CLEAR not in {item.state for item in decisions}
    assert (await get_evidence_set(db, frozen.id)).status == "frozen"
