"""Database-backed tests for the GLiNER2 span-proposal step and wave body."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.models import (
    Base,
    ExecutionAttempt,
    ExecutionRun,
    Kund,
    ResearchAssessment,
    ResearchRuntimeNeed,
)
from app.services.execution.service import (
    add_evidence_items,
    list_evidence_quality,
    persist_research_assessment,
    persist_runtime_needs,
    runtime_need_from_row,
)
from app.services.execution.snapshots import EvidenceItemSnapshot
from app.services.knowledge.models import KnowledgeScope
from app.services.research.assessment import (
    ResearchAssessmentDraft,
    ResearchNeedAssessment,
)
from app.services.research.followup import RuntimeResearchNeed, runtime_needs_from_plan
from app.services.research.gliner import service
from app.services.research.gliner.proposer import (
    SpanProposal,
    UnitProposals,
)
from app.services.research.models import ResearchContext, ResearchPlan
from tests.gliner_test_helpers import (
    FakeAssessor,
    StepAssessor,
    _seed_research,
    _gliner_items,
    CountingJev,
    fake_propose,
    make_assessment_row,
    make_attempt,
    make_need,
    run_step,
)

BT17_CLAUSE = "Syntetisk tidsklausul: Avtalet gäller i 6 månader med 2 veckors uppsägningstid"


@pytest.fixture
async def db_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine, factory
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_persists_verified_findings(db_factory):
    engine, factory = db_factory
    item_ids = await _seed_research(factory, excerpt1=BT17_CLAUSE)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    jev = CountingJev("YES")
    propose = fake_propose({item_ids[0]: [("6 månader", "Tidsperiod")]})
    try:
        result = await run_step(factory, need=need, jev=jev, propose=propose)
        assert result is not None
        report = result.report
        assert report.units_scanned == 1
        assert report.inferences == 1
        assert report.jev_calls == 1
        assert report.findings_persisted == 1
        items = await _gliner_items(factory)
        assert len(items) == 1
        provenance = items[0].provenance
        assert provenance["verified_spans"][0]["span"] == "6 månader"
        assert (
            provenance["verified_spans"][0]["prompt_version"]
            == "span-need-contrast-v1"
        )
        assert provenance["verified_spans"][0]["unit_id"] == item_ids[0]
        async with factory() as session:
            rows = (
                await session.execute(
                    select(ResearchAssessment)
                    .where(ResearchAssessment.attempt_id == "at-1")
                    .order_by(ResearchAssessment.assessment_pass)
                )
            ).scalars().all()
        assert [row.assessment_pass for row in rows] == [1]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_two_competing_units_become_ambiguous(db_factory):
    engine, factory = db_factory
    item_ids = await _seed_research(
        factory,
        excerpt1="Betalning erläggs inom 30 dagar efter erhållen faktura.",
        excerpt2="Leverans sker inom 60 dagar från order.",
    )
    need = make_need("n1", span_types=["PERIOD"], span_role="DEADLINE")
    jev = CountingJev("YES")
    propose = fake_propose(
        {
            item_ids[0]: [("30 dagar", "Tidsperiod")],
            item_ids[1]: [("60 dagar", "Tidsperiod")],
        }
    )
    try:
        result = await run_step(factory, need=need, jev=jev, propose=propose)
        assert result is not None
        assert result.report.jev_calls == 2
        items = await _gliner_items(factory)
        assert len(items) == 1
        provenance = items[0].provenance
        assert provenance["verified_spans"] == []
        assert len(provenance["conflicting_spans"]) == 2
        assert "Motstridigt" in items[0].excerpt
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_all_rejected_persists_checkpoint_and_retry_skips(db_factory):
    engine, factory = db_factory
    item_ids = await _seed_research(factory, excerpt1=BT17_CLAUSE)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    first = await run_step(
        factory,
        need=need,
        jev=CountingJev("NO"),
        propose=fake_propose({item_ids[0]: [("6 månader", "Tidsperiod")]}),
    )
    assert first is not None
    items = await _gliner_items(factory)
    assert len(items) == 1
    assert items[0].status == "not_found"
    assert len(items[0].provenance["rejected_spans"]) == 1
    calls = {"propose": 0, "jev": 0}

    async def fail_propose(units, labels):
        calls["propose"] += 1
        raise AssertionError("retry after a rejected checkpoint must not run")

    class FailJev:
        async def ask(self, **kwargs):
            calls["jev"] += 1
            raise AssertionError("retry after a rejected checkpoint must not run")

    try:
        second = await run_step(factory, need=need, jev=FailJev(), propose=fail_propose)
        assert second is None
        assert calls == {"propose": 0, "jev": 0}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_zero_proposals_persists_checkpoint_and_reruns_on_new_evidence(
    db_factory,
):
    engine, factory = db_factory
    await _seed_research(factory, excerpt1=BT17_CLAUSE)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    calls = {"propose": 0}

    async def no_proposals(units, labels):
        calls["propose"] += 1
        return []

    first = await run_step(
        factory, need=need, jev=CountingJev("YES"), propose=no_proposals
    )
    assert first is not None
    assert first.report.findings_persisted == 1
    items = await _gliner_items(factory)
    assert len(items) == 1
    assert items[0].status == "not_found"
    assert items[0].provenance["empty_proposals"] is True
    assert items[0].provenance["input_fingerprint"]
    second = await run_step(
        factory, need=need, jev=CountingJev("YES"), propose=no_proposals
    )
    assert second is None
    assert calls["propose"] == 1
    async with factory() as session:
        await add_evidence_items(
            session,
            evidence_set_id="es-1",
            items=[
                EvidenceItemSnapshot(
                    research_need_id="n1",
                    source_type="swedish_law",
                    status="found",
                    title="t2",
                    excerpt="Avtalet gäller i sex månader.",
                    locator=None,
                    source_id="s9",
                    source_url=None,
                    provider="test",
                    score=None,
                    provenance={},
                    retrieved_at=datetime.now(timezone.utc),
                )
            ],
        )
        await session.commit()
    try:
        third = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=no_proposals
        )
        assert third is not None
        assert calls["propose"] == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_retry_never_reproposes(db_factory):
    engine, factory = db_factory
    item_ids = await _seed_research(factory, excerpt1=BT17_CLAUSE)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    first = await run_step(
        factory,
        need=need,
        jev=CountingJev("YES"),
        propose=fake_propose({item_ids[0]: [("6 månader", "Tidsperiod")]}),
    )
    assert first is not None
    calls = {"propose": 0, "jev": 0}

    async def fail_propose(units, labels):
        calls["propose"] += 1
        raise AssertionError("retry must not call the model again")

    class FailJev:
        async def ask(self, **kwargs):
            calls["jev"] += 1
            raise AssertionError("retry must not call Jev again")

    try:
        second = await run_step(factory, need=need, jev=FailJev(), propose=fail_propose)
        assert second is None
        assert calls == {"propose": 0, "jev": 0}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_jev_budget_is_enforced_and_reported(db_factory):
    engine, factory = db_factory
    item_ids = await _seed_research(
        factory,
        excerpt1="Betalning inom 30 dagar.",
        excerpt2="Leverans inom 60 dagar.",
    )
    need = make_need("n1", span_types=["PERIOD"], span_role="DEADLINE")
    jev = CountingJev("YES")
    propose = fake_propose(
        {
            item_ids[0]: [("30 dagar", "Tidsperiod")],
            item_ids[1]: [("60 dagar", "Tidsperiod")],
        }
    )
    import app.services.research.gliner.proposal as proposal_mod
    import app.services.research.gliner.service as svc

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(settings.gliner_span_proposer, "max_jev_calls_per_need", 1)
    monkeypatch.setattr(svc, "HttpJevSystemOne", lambda: jev)
    monkeypatch.setattr(proposal_mod, "propose_spans", propose)
    try:
        async with factory() as session:
            result = await svc.maybe_run_gliner_step(
                SimpleNamespace(
                    factory=factory,
                    evidence_set_id="es-1",
                    assessor=StepAssessor(),
                    router=None,
                    provider_descriptors=None,
                    relevance_assessor=None,
                ),
                session,
                attempt=make_attempt(opted_in=True),
                plan=ResearchPlan(needs=[need]),
                assessment=make_assessment_row([need]),
                wave=0,
            )
        assert result is not None
        assert result.report.jev_calls == 1
        assert result.report.jev_budget_truncated is True
        items = await _gliner_items(factory)
        provenance = items[0].provenance
        # A truncated need has not seen every candidate: never usable evidence.
        assert items[0].status == "not_found"
        assert provenance["incomplete"] is True
        assert provenance["verified_spans"] == []
        assert len(provenance["unprocessed_candidates"]) == 1
        assert provenance["derived_claims"] == []
        assert "Ofullständig verifiering" in items[0].excerpt
    finally:
        monkeypatch.undo()
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_cancellation_invalidates_the_wave_assessment(db_factory, monkeypatch):
    """A checkpoint committed before a cancellation must never leave a stale
    assessment: the row is deleted in the same transaction as the item."""
    engine, factory = db_factory
    item_ids = await _seed_research(factory, excerpt1=BT17_CLAUSE)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    async with factory() as session:
        await persist_research_assessment(
            session,
            attempt_id="at-1",
            evidence_set_id="es-1",
            draft=ResearchAssessmentDraft(
                result="insufficient",
                rationale="before",
                need_assessments=[
                    ResearchNeedAssessment(research_need_id="n1", sufficient=False)
                ],
                considered_evidence_ids=[],
            ),
            evidence_fingerprint="before",
            assessment_pass=1,
        )
        await session.commit()

    import app.services.research.gliner.proposal as proposal_mod
    import app.services.research.gliner.service as svc

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(svc, "HttpJevSystemOne", lambda: CountingJev("YES"))
    monkeypatch.setattr(
        proposal_mod,
        "propose_spans",
        fake_propose({item_ids[0]: [("6 månader", "Tidsperiod")]}),
    )
    monkeypatch.setattr(svc, "refresh_assessment", cancelled)
    try:
        async with factory() as session:
            with pytest.raises(asyncio.CancelledError):
                await svc.maybe_run_gliner_step(
                    SimpleNamespace(
                        factory=factory,
                        evidence_set_id="es-1",
                        assessor=StepAssessor(),
                        router=None,
                        provider_descriptors=None,
                        relevance_assessor=None,
                    ),
                    session,
                    attempt=make_attempt(opted_in=True),
                    plan=ResearchPlan(needs=[need]),
                    assessment=make_assessment_row([need]),
                    wave=0,
                )
        items = await _gliner_items(factory)
        assert len(items) == 1
        async with factory() as session:
            rows = (
                await session.execute(
                    select(ResearchAssessment).where(
                        ResearchAssessment.attempt_id == "at-1"
                    )
                )
            ).scalars().all()
        assert rows == []  # stale assessment invalidated with the checkpoint
        from app.services.research.execution import _assess_persisted_evidence

        assessor = FakeAssessor()
        async with factory() as session:
            await _assess_persisted_evidence(
                session,
                attempt=SimpleNamespace(id="at-1"),
                evidence_set_id="es-1",
                plan=ResearchPlan(needs=[need]),
                assessor=assessor,
                assessment_pass=1,
            )
            await session.commit()
        assert assessor.calls == [2]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_all_span_types_reach_the_model(db_factory):
    engine, factory = db_factory
    await _seed_research(factory, excerpt1=BT17_CLAUSE)
    need = make_need(
        "n1", span_types=["DATE", "PERIOD", "MONEY", "PARTY"], span_role=""
    )
    captured: dict[str, tuple[str, ...]] = {}

    async def capture(units, labels):
        captured["labels"] = labels
        return []

    try:
        result = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=capture
        )
        assert result is not None
        assert set(captured["labels"]) == {
            "Datum",
            "Tidsperiod",
            "Belopp",
            "Avtalspart",
        }
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_invalid_jev_choice_fails_loudly(db_factory):
    engine, factory = db_factory
    item_ids = await _seed_research(factory, excerpt1=BT17_CLAUSE)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")

    class BadJev:
        async def ask(self, **kwargs):
            return SimpleNamespace(answers={"evidence": {"choice": "MAYBE"}})

    try:
        with pytest.raises(service.GlinerStepError, match="invalid choice"):
            await run_step(
                factory,
                need=need,
                jev=BadJev(),
                propose=fake_propose({item_ids[0]: [("6 månader", "Tidsperiod")]}),
            )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------- runtime needs


@pytest.mark.asyncio
async def test_runtime_needs_from_plan_keeps_span_declaration():
    plan = ResearchPlan(
        needs=[make_need("n1", span_types=["PERIOD"], span_role="DURATION")]
    )
    rows = runtime_needs_from_plan(plan)
    assert rows[0].span_types == ["PERIOD"]
    assert rows[0].span_role == "DURATION"


@pytest.mark.asyncio
async def test_inventory_persists_span_declaration(db_factory):
    """Full path: ResearchPlan -> _ensure_research_inventory -> runtime plan."""
    from app.services.research.execution import _ensure_research_inventory
    from tests.question_graph_memory import InMemoryQuestionEvidenceGraph

    engine, factory = db_factory
    async with factory() as session:
        session.add(Kund(id=1, name="Test", slug="test", available_modules=[]))
        session.add(
            ExecutionRun(id="run-1", customer_id=1, module="dd", title="t", context={})
        )
        session.add(
            ExecutionAttempt(
                id="at-1",
                run_id="run-1",
                attempt_type="research",
                status="created",
                configuration_snapshot={"gliner_span_proposer": True},
                input_snapshot={},
                research_wave=0,
            )
        )
        await session.commit()
        attempt = await session.get(ExecutionAttempt, "at-1")
        run = await session.get(ExecutionRun, "run-1")
        plan = ResearchPlan(
            needs=[make_need("n1", span_types=["PERIOD"], span_role="DURATION")]
        )
        await _ensure_research_inventory(
            session,
            attempt=attempt,
            run=run,
            plan=plan,
            question_graph=InMemoryQuestionEvidenceGraph(),
            context=ResearchContext(
                scope=KnowledgeScope(customer_id=1), limit=10, attempt_id="at-1"
            ),
        )
        await session.commit()
        from app.services.research.execution import runtime_plan

        active = await runtime_plan(session, "at-1")
    try:
        assert active.needs[0].span_types == ["PERIOD"]
        assert active.needs[0].span_role == "DURATION"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_need_roundtrip_keeps_span_fields(db_factory):
    engine, factory = db_factory
    await _seed_research(factory, excerpt1=BT17_CLAUSE)
    async with factory() as session:
        await persist_runtime_needs(
            session,
            attempt_id="at-1",
            needs=[
                RuntimeResearchNeed(
                    research_need_id="n2",
                    question="Vilken uppsägningstid gäller?",
                    why_needed="test",
                    source_types=["swedish_law"],
                    span_types=["NOTICE_PERIOD"],
                    span_role="NOTICE",
                )
            ],
        )
        await session.commit()
        rows = (
            await session.execute(
                select(ResearchRuntimeNeed)
                .where(ResearchRuntimeNeed.attempt_id == "at-1")
                .order_by(ResearchRuntimeNeed.wave_number)
            )
        ).scalars().all()
    try:
        by_id = {row.research_need_id: row for row in rows}
        assert by_id["n1"].span_types == ["PERIOD"]
        converted = runtime_need_from_row(by_id["n2"])
        assert converted.span_types == ["NOTICE_PERIOD"]
        assert converted.span_role == "NOTICE"
        assert converted.as_need().span_types == ["NOTICE_PERIOD"]
        assert converted.as_need().span_role == "NOTICE"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------- wave body


class WaveAssessor:
    def __init__(self) -> None:
        self.calls: list[int] = []

    async def assess(self, plan, evidence):
        self.calls.append(len(evidence))
        return ResearchAssessmentDraft(
            result="insufficient",
            rationale="test",
            need_assessments=[
                ResearchNeedAssessment(research_need_id=need.id, sufficient=False)
                for need in plan.needs
            ],
            considered_evidence_ids=[item.evidence_id for item in evidence],
        )


@pytest.mark.asyncio
async def test_finish_wave_runs_gliner_and_refreshes_assessment(db_factory, monkeypatch):
    """End-to-end through finish_research_wave: persisted runtime needs carry
    span declarations, two competing TextUnits become a visible conflict, the
    new evidence is scored and re-assessed before the decision, and a retry
    never repeats model or Jev calls."""
    import app.services.research.loop_control as loop_control
    from app.services.research.loop_control import ResearchWaveConfig, finish_research_wave

    engine, factory = db_factory
    await _seed_research(
        factory,
        excerpt1="Betalning erläggs inom 30 dagar efter erhållen faktura.",
        excerpt2="Leverans sker inom 60 dagar från order.",
    )
    need = make_need(
        "n1", span_types=["PERIOD"], span_role="DEADLINE"
    )  # runtime needs carry the same declaration
    plan = ResearchPlan(needs=[need])
    assessor = WaveAssessor()
    jev = CountingJev("YES")
    calls = {"propose": 0}

    async def propose(units, labels):
        calls["propose"] += 1
        out = []
        for unit in units:
            span = "30 dagar" if "30 dagar" in unit.text else "60 dagar"
            out.append(
                UnitProposals(
                    unit_id=unit.unit_id,
                    proposals=(SpanProposal(span=span, label="Tidsperiod"),),
                )
            )
        return out

    import app.services.research.gliner.proposal as proposal_mod

    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(service, "HttpJevSystemOne", lambda: jev)
    monkeypatch.setattr(proposal_mod, "propose_spans", propose)

    async def no_decision(*args, **kwargs):
        return None

    monkeypatch.setattr(loop_control, "_decide_research_wave", no_decision)

    config = ResearchWaveConfig(
        factory=factory,
        attempt_id="at-1",
        evidence_set_id="es-1",
        context=ResearchContext(
            scope=KnowledgeScope(customer_id=1), limit=10, attempt_id="at-1"
        ),
        router=None,
        router_factory=None,
        question_graph=SimpleNamespace(),
        assessor=assessor,
        planner=SimpleNamespace(),
        completeness_reviewer=SimpleNamespace(),
        relevance_assessor=None,
        provider_descriptors=(),
        concurrency=1,
        max_follow_up_waves=0,
        max_needs=4,
        max_completeness_passes=1,
        need_normalizer=None,
    )
    try:
        result = await finish_research_wave(config, snapshot_plan=plan, wave=0)
        assert result is None
        items = await _gliner_items(factory)
        assert len(items) == 1
        assert len(items[0].provenance["conflicting_spans"]) == 2
        assert items[0].provenance["verified_spans"] == []
        assert "Motstridigt" in items[0].excerpt
        async with factory() as session:
            quality = await list_evidence_quality(session, "es-1")
            passes = (
                await session.execute(
                    select(ResearchAssessment)
                    .where(ResearchAssessment.attempt_id == "at-1")
                    .order_by(ResearchAssessment.assessment_pass)
                )
            ).scalars().all()
        assert any(row.evidence_set_item_id == items[0].id for row in quality)
        assert [row.assessment_pass for row in passes] == [1]
        assert assessor.calls == [2, 3]  # first wave saw 2 items, refresh sees 3
        propose_calls = calls["propose"]
        jev_calls = jev.calls
        await finish_research_wave(config, snapshot_plan=plan, wave=1)
        assert calls["propose"] == propose_calls
        assert jev.calls == jev_calls
    finally:
        await engine.dispose()
