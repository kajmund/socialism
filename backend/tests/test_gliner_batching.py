"""Batch, truncation and cross-batch aggregation tests for the GLiNER2 step."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.models import Base
from app.services.execution.service import add_evidence_items
from app.services.execution.snapshots import EvidenceItemSnapshot
from app.services.research.gliner import service
from app.services.research.models import ResearchPlan
from tests.gliner_test_helpers import (
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
        assert result.report.truncation_reasons == ("per_need_jev_budget",)
        items = await _gliner_items(factory)
        provenance = items[0].provenance
        # A truncated need has not seen every candidate: never usable evidence.
        assert items[0].status == "not_found"
        assert provenance["incomplete"] is True
        assert provenance["incomplete_reason"] == "truncated"
        assert provenance["truncation_reasons"] == ["per_need_jev_budget"]
        assert provenance["verified_spans"] == []
        assert len(provenance["unprocessed_candidates"]) == 1
        assert provenance["derived_claims"] == []
        assert "JEV-budgeten för behovet" in items[0].excerpt
    finally:
        monkeypatch.undo()
        await engine.dispose()

@pytest.mark.asyncio
async def test_step_span_cap_is_per_unit(db_factory):
    """The per-unit span cap: two units at exactly the cap are NOT truncation."""
    import app.services.research.gliner.proposal as proposal_mod
    import app.services.research.gliner.service as svc

    engine, factory = db_factory
    item_ids = await _seed_research(
        factory,
        excerpt1="Betalning inom 30 dagar.",
        excerpt2="Betalning inom 30 dagar efter fakturadatum.",
    )
    need = make_need("n1", span_types=["PERIOD"], span_role="DEADLINE")
    propose = fake_propose(
        {
            item_ids[0]: [("30 dagar", "Tidsperiod")],
            item_ids[1]: [("30 dagar", "Tidsperiod")],
        }
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(settings.gliner_span_proposer, "max_spans_per_unit", 1)
    monkeypatch.setattr(svc, "HttpJevSystemOne", lambda: CountingJev("YES"))
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
        assert result.report.truncation_reasons == ()
        items = await _gliner_items(factory)
        assert items[0].status == "found"
        assert items[0].provenance["incomplete"] is False
        assert len(items[0].provenance["verified_spans"]) == 2
    finally:
        monkeypatch.undo()
        await engine.dispose()

@pytest.mark.asyncio
async def test_step_span_cap_overflow_is_typed_truncation(db_factory):
    """A unit with cap+1 proposals is truncated with reason span_cap."""
    import app.services.research.gliner.proposal as proposal_mod
    import app.services.research.gliner.service as svc

    engine, factory = db_factory
    item_ids = await _seed_research(factory, excerpt1="Betalning inom 30 dagar.")
    need = make_need("n1", span_types=["PERIOD"], span_role="DEADLINE")
    propose = fake_propose(
        {item_ids[0]: [("30 dagar", "Tidsperiod"), ("60 dagar", "Tidsperiod")]}
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(settings.gliner_span_proposer, "max_spans_per_unit", 1)
    monkeypatch.setattr(svc, "HttpJevSystemOne", lambda: CountingJev("YES"))
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
        assert result.report.truncation_reasons == ("span_cap",)
        items = await _gliner_items(factory)
        provenance = items[0].provenance
        assert items[0].status == "not_found"
        assert provenance["incomplete"] is True
        assert provenance["truncation_reasons"] == ["span_cap"]
        assert provenance["verified_spans"] == []
        assert len(provenance["unprocessed_candidates"]) == 1
        assert "spann-taket per enhet" in items[0].excerpt
    finally:
        monkeypatch.undo()
        await engine.dispose()

@pytest.mark.asyncio
async def test_step_batches_beyond_the_unit_limit(db_factory):
    """Units beyond max_units_per_need are processed in later deterministic
    batches, and late evidence is never blocked by an old checkpoint."""
    engine, factory = db_factory
    await _seed_research(
        factory,
        excerpt1="Betalning inom 30 dagar.",
        excerpt2="Leverans inom 60 dagar.",
    )
    need = make_need("n1", span_types=["PERIOD"], span_role="DEADLINE")
    calls = {"propose": 0}

    async def no_proposals(units, labels):
        calls["propose"] += 1
        return []

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(settings.gliner_span_proposer, "max_units_per_need", 1)
    try:
        first = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=no_proposals
        )
        assert first is not None
        assert calls["propose"] == 1
        second = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=no_proposals
        )
        assert second is not None
        assert calls["propose"] == 2  # the second unit is a new batch
        third = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=no_proposals
        )
        assert third is None  # everything is processed
        assert calls["propose"] == 2
        # A later wave with new evidence becomes the next unprocessed batch.
        async with factory() as session:
            await add_evidence_items(
                session,
                evidence_set_id="es-1",
                items=[
                    EvidenceItemSnapshot(
                        research_need_id="n1",
                        source_type="swedish_law",
                        status="found",
                        title="t3",
                        excerpt="Avtalet gäller i sex månader.",
                        locator=None,
                        source_id="s3",
                        source_url=None,
                        provider="test",
                        score=None,
                        provenance={},
                        retrieved_at=datetime.now(timezone.utc),
                    )
                ],
            )
            await session.commit()
        fourth = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=no_proposals
        )
        assert fourth is not None
        assert calls["propose"] == 3
    finally:
        monkeypatch.undo()
        await engine.dispose()

@pytest.mark.asyncio
async def test_step_batches_aggregate_before_usable_evidence(db_factory):
    """Cross-unit competition must aggregate across batches: a partial batch is
    a non-usable checkpoint, and the final batch derives over all batches."""
    engine, factory = db_factory
    item_ids = await _seed_research(
        factory,
        excerpt1="Betalning erläggs inom 30 dagar efter erhållen faktura.",
        excerpt2="Leverans sker inom 60 dagar från order.",
    )
    need = make_need("n1", span_types=["PERIOD"], span_role="DEADLINE")
    propose = fake_propose(
        {
            item_ids[0]: [("30 dagar", "Tidsperiod")],
            item_ids[1]: [("60 dagar", "Tidsperiod")],
        }
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(settings.gliner_span_proposer, "max_units_per_need", 1)
    try:
        first = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=propose
        )
        assert first is not None
        items = await _gliner_items(factory)
        assert len(items) == 1
        assert items[0].status == "not_found"  # partial batch: not usable
        assert items[0].provenance["incomplete_reason"] == "partial_batch"
        assert items[0].provenance["derived_claims"] == []
        assert items[0].provenance["verified_spans"] == []
        second = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=propose
        )
        assert second is not None
        items = await _gliner_items(factory)
        final = [item for item in items if item.provenance["processed_units"] == [item_ids[1]]]
        assert len(final) == 1
        provenance = final[0].provenance
        # Prior batch's verdict participates in the aggregation.
        assert len(provenance["conflicting_spans"]) == 2
        assert provenance["derived_claims"] == []
        assert final[0].status == "not_found"
        assert "Motstridigt" in final[0].excerpt
    finally:
        monkeypatch.undo()
        await engine.dispose()

@pytest.mark.asyncio
async def test_step_prior_truncation_is_retried_before_usable_evidence(db_factory):
    """An earlier truncation is never forgotten: its unprocessed candidates are
    retried, and partial verdicts cannot become usable evidence on their own."""
    engine, factory = db_factory
    item_ids = await _seed_research(
        factory,
        excerpt1="Betalning erläggs inom 30 dagar efter erhållen faktura.",
        excerpt2="Betalning inom 30 dagar efter fakturadatum.",
    )
    need = make_need("n1", span_types=["PERIOD"], span_role="DEADLINE")
    propose = fake_propose(
        {
            item_ids[0]: [("30 dagar", "Tidsperiod"), ("60 dagar", "Tidsperiod")],
            item_ids[1]: [("30 dagar", "Tidsperiod")],
        }
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(settings.gliner_span_proposer, "max_units_per_need", 1)
    monkeypatch.setattr(settings.gliner_span_proposer, "max_spans_per_unit", 1)
    try:
        first = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=propose
        )
        assert first is not None
        items = await _gliner_items(factory)
        assert len(items) == 1
        assert items[0].status == "not_found"  # partial + truncated
        assert items[0].provenance["incomplete_reason"] == "truncated"
        # Finding 2: the checkpoint names BOTH causes and is not "empty".
        assert "ytterligare enheter återstår" in items[0].excerpt
        assert "spann-taket per enhet" in items[0].excerpt
        assert items[0].provenance["empty_proposals"] is False
        assert len(items[0].provenance["unprocessed_candidates"]) == 1

        second = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=propose
        )
        assert second is not None
        items = await _gliner_items(factory)
        # The retried "60 dagar" collides with the scanned "30 dagar" values.
        final = [item for item in items if item.provenance["processed_units"] == [item_ids[1]]]
        assert len(final) == 1
        conflicts = {row["span"] for row in final[0].provenance["conflicting_spans"]}
        assert conflicts == {"30 dagar", "60 dagar"}
        assert final[0].status == "not_found"
        assert final[0].provenance["derived_claims"] == []
        assert all(item.status == "not_found" for item in items)

        # A resolved retry is never fetched again: no JEV and no model call.
        class FailJev:
            async def ask(self, **kwargs):
                raise AssertionError("a resolved retry must not call Jev again")

        async def fail_propose(units, labels):
            raise AssertionError("a resolved retry must not call the model again")

        third = await run_step(factory, need=need, jev=FailJev(), propose=fail_propose)
        assert third is None
    finally:
        monkeypatch.undo()
        await engine.dispose()

@pytest.mark.asyncio
async def test_step_processed_units_keep_batch_order(db_factory):
    engine, factory = db_factory
    item_ids = await _seed_research(
        factory,
        excerpt1="Betalning inom 30 dagar.",
        excerpt2="Betalning inom 60 dagar.",
    )
    need = make_need("n1", span_types=["PERIOD"], span_role="DEADLINE")
    propose = fake_propose(
        {
            item_ids[0]: [("30 dagar", "Tidsperiod")],
            item_ids[1]: [("60 dagar", "Tidsperiod")],
        }
    )
    try:
        result = await run_step(
            factory, need=need, jev=CountingJev("YES"), propose=propose
        )
        assert result is not None
        items = await _gliner_items(factory)
        assert items[0].provenance["processed_units"] == item_ids
        assert items[0].provenance["input_fingerprint"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_global_jev_budget_is_shared_across_needs(db_factory):
    """The step budget is a hard cap across ALL needs, not a per-need reset."""
    engine, factory = db_factory
    item_ids = await _seed_research(factory, excerpt1=BT17_CLAUSE)
    n2_id = ""
    async with factory() as session:
        stored = await add_evidence_items(
            session,
            evidence_set_id="es-1",
            items=[
                EvidenceItemSnapshot(
                    research_need_id="n2",
                    source_type="swedish_law",
                    status="found",
                    title="t2",
                    excerpt=BT17_CLAUSE,
                    locator=None,
                    source_id="s2",
                    source_url=None,
                    provider="test",
                    score=None,
                    provenance={},
                    retrieved_at=datetime.now(timezone.utc),
                )
            ],
        )
        await session.commit()
        n2_id = stored[0].id
    need_first = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    need_second = make_need("n2", span_types=["PERIOD"], span_role="DURATION")
    plan = ResearchPlan(needs=[need_first, need_second])
    jev = CountingJev("YES")
    propose = fake_propose(
        {
            item_ids[0]: [
                ("6 månader", "Tidsperiod"),
                ("2 veckors", "Tidsperiod"),
            ],
            n2_id: [
                ("6 månader", "Tidsperiod"),
                ("2 veckors", "Tidsperiod"),
            ],
        }
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(settings.gliner_span_proposer, "max_jev_calls_per_step", 3)
    monkeypatch.setattr(service, "HttpJevSystemOne", lambda: jev)
    import app.services.research.gliner.proposal as proposal_mod

    monkeypatch.setattr(proposal_mod, "propose_spans", propose)
    assessment = make_assessment_row([need_first, need_second])
    try:
        async with factory() as session:
            result = await service.maybe_run_gliner_step(
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
                plan=plan,
                assessment=assessment,
                wave=0,
            )
        assert result is not None
        assert jev.calls == 3  # never the 4 calls a per-need reset would allow
        assert "step_jev_budget" in result.report.truncation_reasons
    finally:
        monkeypatch.undo()
        await engine.dispose()


@pytest.mark.asyncio
async def test_step_same_span_is_verified_per_declared_type(db_factory):
    """One span proposed for several declared types gets one verdict PER type."""
    engine, factory = db_factory
    item_ids = await _seed_research(factory, excerpt1="Avtalet gäller från 12 maj.")
    need = make_need("n1", span_types=["DATE", "PERIOD"], span_role="")
    jev = CountingJev("YES")
    propose = fake_propose(
        {item_ids[0]: [("12 maj", "Datum"), ("12 maj", "Tidsperiod")]}
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(service, "HttpJevSystemOne", lambda: jev)
    import app.services.research.gliner.proposal as proposal_mod

    monkeypatch.setattr(proposal_mod, "propose_spans", propose)
    try:
        async with factory() as session:
            result = await service.maybe_run_gliner_step(
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
        assert jev.calls == 2  # one Jev question per declared type
        assert set(result.report.truncation_reasons) == set()
        items = await _gliner_items(factory)
        assert {
            row["need_type"] for row in items[0].provenance["scanned_spans"]
        } == {"DATE", "PERIOD"}
    finally:
        monkeypatch.undo()
        await engine.dispose()
