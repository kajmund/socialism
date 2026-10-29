"""Unit + integration tests for the optional GLiNER2 span proposer.

Covers the frozen E1–E3 contract rules, the proposer lifecycle and typed
errors, the opt-in gating, the split-phase database discipline, and the
frozen experiment outcomes (PR #443–#446) as regression tests.
"""

from __future__ import annotations

import asyncio
import builtins
import sys
import time
import types
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.models import Base, EvidenceSet, ExecutionRun, Kund
from app.services.research.assessment import (
    ResearchAssessmentDraft,
    ResearchNeedAssessment,
)
from app.services.research.gliner import proposer, service
from app.services.research.gliner.contract import (
    AMBIGUOUS,
    REJECTED,
    VERIFIED,
    SpanVerdict,
    canon,
    canon_value,
    derive_findings,
    operational_role,
    verification_question,
)
from app.services.research.gliner.proposer import (
    GlinerProposerError,
    ProposalUnit,
    SpanProposal,
    UnitProposals,
)
from app.services.research.models import (
    InvalidResearchPlanError,
    ResearchNeed,
    ResearchPlan,
)
from app.services.research.plan import validate_research_plan

BT17_CLAUSE = "Syntetisk tidsklausul: Avtalet gäller i 6 månader med 2 veckors uppsägningstid"
BT13_CLAUSE = (
    "Syntetisk ansvarsklausul: Ansvar för intrång i immateriell rätt ska, utom vid grov "
    "vårdslöshet eller uppsåt, vara begränsat till arvodet för Tjänsten och vid "
    "löpande arvode, utgörs arvodet av arvodet för de senaste 12 månaderna för Tjänsten."
)


def make_attempt(*, opted_in: bool = False) -> SimpleNamespace:
    snapshot = {"gliner_span_proposer": True} if opted_in else {}
    return SimpleNamespace(configuration_snapshot=snapshot)


def make_need(
    need_id: str,
    *,
    span_types: list[str] | None = None,
    span_role: str = "",
) -> ResearchNeed:
    return ResearchNeed(
        id=need_id,
        question=f"Fråga {need_id}?",
        why_needed="test",
        source_types=["swedish_law"],
        span_types=span_types or [],
        span_role=span_role,
    )


def make_assessment(needs: list[ResearchNeed]) -> ResearchAssessmentDraft:
    return ResearchAssessmentDraft(
        result="insufficient",
        rationale="test",
        need_assessments=[
            ResearchNeedAssessment(research_need_id=need.id, sufficient=False)
            for need in needs
        ],
    )


# ---------------------------------------------------------------- contract


def test_canon_and_canon_value_frozen_rules():
    assert canon("[nio (9)] månader") == "nio (9) månader"
    assert canon_value("inom 30 dagar") == "30 dagar"
    assert canon_value("2 veckors") == "2 veckor"
    assert canon_value("i 6 månader") == "6 månader"
    # Quantifiers carry semantic load and are never stripped.
    assert canon_value("minst 500 kr") == "minst 500 kr"


def test_operational_role_bt17():
    assert operational_role("6 månader", BT17_CLAUSE) == "DURATION"
    assert operational_role("2 veckors", BT17_CLAUSE) == "NOTICE"


def test_operational_role_word_boundary_guard():
    # "senast" must not match inside "senaste"; arvodet is the nearest cue.
    assert operational_role("12 m å naderna", BT13_CLAUSE) == "MONEY"


def test_operational_role_unknown():
    assert operational_role("finns inte", BT17_CLAUSE) is None


def test_derive_findings_single_yes():
    findings = derive_findings(
        [SpanVerdict(span="6 månader", need_type="PERIOD",
                     prompt_version="x", choice="YES")],
        need_type="PERIOD",
        need_role="DURATION",
        unit_text=BT17_CLAUSE,
    )
    assert [f.state for f in findings] == [VERIFIED]
    assert findings[0].value == "6 månader"


def test_derive_findings_rejected():
    findings = derive_findings(
        [SpanVerdict(span="Enligt LAS", need_type="NOTICE_PERIOD",
                     prompt_version="x", choice="NO")],
        need_type="NOTICE_PERIOD",
        need_role="NOTICE",
        unit_text="Uppsägningstid Enligt LAS",
    )
    assert [f.state for f in findings] == [REJECTED]


def test_derive_findings_bt17_role_split():
    """E3: a different operational role neither competes nor persists."""
    findings = derive_findings(
        [
            SpanVerdict(span="6 månader", need_type="PERIOD",
                        prompt_version="x", choice="YES"),
            SpanVerdict(span="2 veckors", need_type="PERIOD",
                        prompt_version="x", choice="YES"),
        ],
        need_type="PERIOD",
        need_role="DURATION",
        unit_text=BT17_CLAUSE,
    )
    by_span = {f.span: f.state for f in findings}
    assert by_span["6 månader"] == VERIFIED
    assert "2 veckors" not in by_span  # role NOTICE != need role DURATION


def test_derive_findings_ambiguous_same_role():
    findings = derive_findings(
        [
            SpanVerdict(span="30 dagar", need_type="PERIOD",
                        prompt_version="x", choice="YES"),
            SpanVerdict(span="60 dagar", need_type="PERIOD",
                        prompt_version="x", choice="YES"),
        ],
        need_type="PERIOD",
        need_role="DEADLINE",
        unit_text="Betalning inom 30 dagar, leverans inom 60 dagar.",
    )
    assert {f.state for f in findings} == {AMBIGUOUS}


def test_derive_findings_unknown_role_fails_safe():
    """A span with an undeterminable role always competes."""
    findings = derive_findings(
        [
            SpanVerdict(span="6 månader", need_type="PERIOD",
                        prompt_version="x", choice="YES"),
            SpanVerdict(span="finns inte i texten", need_type="PERIOD",
                        prompt_version="x", choice="YES"),
        ],
        need_type="PERIOD",
        need_role="DURATION",
        unit_text=BT17_CLAUSE,
    )
    assert {f.state for f in findings} == {AMBIGUOUS}


def test_derive_findings_no_role_fails_safe():
    findings = derive_findings(
        [
            SpanVerdict(span="6 månader", need_type="PERIOD",
                        prompt_version="x", choice="YES"),
            SpanVerdict(span="2 veckors", need_type="PERIOD",
                        prompt_version="x", choice="YES"),
        ],
        need_type="PERIOD",
        need_role="",
        unit_text=BT17_CLAUSE,
    )
    assert {f.state for f in findings} == {AMBIGUOUS}


def test_verification_question_versions():
    assert verification_question("DATE", "12 maj")["prompt_version"] == "span-date-v1"
    assert (
        verification_question("PERIOD", "30 dagar")["prompt_version"]
        == "span-need-contrast-v1"
    )


# ---------------------------------------------------------------- proposer


def test_proposer_loads_model_once(monkeypatch):
    loads = {"count": 0}
    fake = types.ModuleType("gliner2")

    class FakeExtractor:
        def extract_entities(self, text, *, entity_types, threshold, format_results):
            return {"entities": []}

    def from_pretrained(model):
        loads["count"] += 1
        return FakeExtractor()

    fake.AutoExtractor = SimpleNamespace(from_pretrained=from_pretrained)
    monkeypatch.setitem(sys.modules, "gliner2", fake)
    proposer.reset_model_cache()
    try:
        first = proposer._load_model()
        second = proposer._load_model()
        assert first is second
        assert loads["count"] == 1
    finally:
        proposer.reset_model_cache()


def test_proposer_missing_dependencies(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "gliner2":
            raise ImportError("no gliner2")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    proposer.reset_model_cache()

    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer.propose_spans(
                (ProposalUnit(unit_id="u1", text="text"),), ("Datum",)
            )
        assert excinfo.value.reason == "missing_dependencies"

    asyncio.run(run())


def test_proposer_load_failed(monkeypatch):
    fake = types.ModuleType("gliner2")
    fake.AutoExtractor = SimpleNamespace(
        from_pretrained=lambda model: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    monkeypatch.setitem(sys.modules, "gliner2", fake)
    proposer.reset_model_cache()

    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer.propose_spans(
                (ProposalUnit(unit_id="u1", text="text"),), ("Datum",)
            )
        assert excinfo.value.reason == "load_failed"

    asyncio.run(run())


def test_proposer_timeout(monkeypatch):
    def slow(units, labels):
        time.sleep(0.2)
        return []

    monkeypatch.setattr(proposer, "_propose_sync", slow)
    monkeypatch.setattr(proposer, "_model", object())  # skip loading

    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer.propose_spans(
                (ProposalUnit(unit_id="u1", text="text"),),
                ("Datum",),
                timeout_seconds=0.01,
            )
        assert excinfo.value.reason == "timeout"

    asyncio.run(run())


def test_proposer_invalid_labels():
    async def run():
        with pytest.raises(GlinerProposerError) as excinfo:
            await proposer.propose_spans(
                (ProposalUnit(unit_id="u1", text="text"),), ()
            )
        assert excinfo.value.reason == "invalid_labels"
        assert await proposer.propose_spans((), ("Datum",)) == []

    asyncio.run(run())


# ---------------------------------------------------------------- gating


@pytest.mark.asyncio
async def test_step_disabled_is_no_op(monkeypatch):
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", False)

    async def fail(*args, **kwargs):
        raise AssertionError("proposer must not run when disabled")

    monkeypatch.setattr(service, "propose_spans", fail)
    report = await service.maybe_run_gliner_step(
        SimpleNamespace(), None, attempt=make_attempt(opted_in=True),
        plan=ResearchPlan(), assessment=ResearchAssessmentDraft(
            result="insufficient", rationale="", need_assessments=[]
        ),
    )
    assert report is None


@pytest.mark.asyncio
async def test_step_opted_out_is_no_op(monkeypatch):
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)

    async def fail(*args, **kwargs):
        raise AssertionError("proposer must not run when the run did not opt in")

    monkeypatch.setattr(service, "propose_spans", fail)
    report = await service.maybe_run_gliner_step(
        SimpleNamespace(), None, attempt=make_attempt(opted_in=False),
        plan=ResearchPlan(), assessment=ResearchAssessmentDraft(
            result="insufficient", rationale="", need_assessments=[]
        ),
    )
    assert report is None


@pytest.mark.asyncio
async def test_step_sufficient_assessment_is_no_op(monkeypatch):
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)

    async def fail(*args, **kwargs):
        raise AssertionError("proposer must not run when nothing is missing")

    monkeypatch.setattr(service, "propose_spans", fail)
    report = await service.maybe_run_gliner_step(
        SimpleNamespace(), None, attempt=make_attempt(opted_in=True),
        plan=ResearchPlan(), assessment=ResearchAssessmentDraft(
            result="sufficient", rationale="", need_assessments=[]
        ),
    )
    assert report is None


@pytest.mark.asyncio
async def test_step_no_span_types_is_no_op(monkeypatch):
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)

    async def fail(*args, **kwargs):
        raise AssertionError("proposer must not run without declared span types")

    monkeypatch.setattr(service, "propose_spans", fail)
    need = make_need("n1", span_types=None)
    report = await service.maybe_run_gliner_step(
        SimpleNamespace(), None, attempt=make_attempt(opted_in=True),
        plan=ResearchPlan(needs=[need]), assessment=make_assessment([need]),
    )
    assert report is None


# ---------------------------------------------------------------- plan


def test_plan_validation_span_vocabulary():
    valid = validate_research_plan(
        ResearchPlan(needs=[make_need("n1", span_types=["PERIOD"], span_role="DURATION")])
    )
    assert valid.needs[0].span_types == ["PERIOD"]
    assert valid.needs[0].span_role == "DURATION"
    with pytest.raises(InvalidResearchPlanError, match="unknown span_types"):
        validate_research_plan(
            ResearchPlan(needs=[make_need("n1", span_types=["NOT_A_TYPE"])])
        )
    with pytest.raises(InvalidResearchPlanError, match="unknown span_role"):
        validate_research_plan(
            ResearchPlan(needs=[make_need("n1", span_types=["PERIOD"], span_role="NOPE")])
        )


# ---------------------------------------------------------------- service


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


async def seed_database(factory, *, need_id: str, excerpt: str | None):
    async with factory() as session:
        session.add(Kund(id=1, name="Test", slug="test", available_modules=[]))
        session.add(
            ExecutionRun(
                id="run-1", customer_id=1, module="dd", title="t", context={}
            )
        )
        session.add(EvidenceSet(id="es-1", run_id="run-1", status="building"))
        await session.commit()
    if excerpt is None:
        return None
    from app.services.execution.service import add_evidence_items
    from app.services.execution.snapshots import EvidenceItemSnapshot

    async with factory() as session:
        stored = await add_evidence_items(
            session,
            evidence_set_id="es-1",
            items=[
                EvidenceItemSnapshot(
                    research_need_id=need_id,
                    source_type="swedish_law",
                    status="found",
                    title="t",
                    excerpt=excerpt,
                    locator=None,
                    source_id="s1",
                    source_url=None,
                    provider="test",
                    score=None,
                    provenance={},
                    retrieved_at=datetime.now(timezone.utc),
                )
            ],
        )
        await session.commit()
    return stored[0].id


class FakeJev:
    def __init__(self, choice: str = "YES") -> None:
        self.choice = choice
        self.calls: list[str] = []

    async def ask(self, *, state, questions, model, timeout_seconds):
        self.calls.append(questions["evidence"]["instructions"])
        return SimpleNamespace(answers={"evidence": {"choice": self.choice}})


def fake_propose(proposals_by_unit: dict[str, list[tuple[str, str]]]):
    async def propose(units, labels):
        return [
            UnitProposals(
                unit_id=unit.unit_id,
                proposals=tuple(
                    SpanProposal(span=span, label=label)
                    for span, label in proposals_by_unit.get(unit.unit_id, [])
                ),
            )
            for unit in units
        ]

    return propose


async def run_step(factory, *, need, jev, propose):
    import app.services.research.gliner.service as svc

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(svc, "HttpJevSystemOne", lambda: jev)
    monkeypatch.setattr(svc, "propose_spans", propose)
    try:
        async with factory() as session:
            return await svc.maybe_run_gliner_step(
                SimpleNamespace(factory=factory, evidence_set_id="es-1"),
                session,
                attempt=make_attempt(opted_in=True),
                plan=ResearchPlan(needs=[need]),
                assessment=make_assessment([need]),
            )
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_full_run_persists_verified_findings(db_factory):
    engine, factory = db_factory
    item_id = await seed_database(factory, need_id="n1", excerpt=BT17_CLAUSE)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    jev = FakeJev(choice="YES")
    propose = fake_propose({item_id: [("6 månader", "Tidsperiod")]})
    try:
        report = await run_step(factory, need=need, jev=jev, propose=propose)
        assert report is not None
        assert report.inferences == 1
        assert report.jev_calls == 1
        assert report.findings_persisted == 1
        async with factory() as session:
            from sqlalchemy import select

            from app.database.models import EvidenceSetItem

            rows = (
                await session.execute(
                    select(EvidenceSetItem).where(
                        EvidenceSetItem.evidence_set_id == "es-1"
                    )
                )
            ).scalars().all()
        gliner_items = [
            row for row in rows if row.provenance.get("derivation") == "gliner_span_proposal"
        ]
        assert len(gliner_items) == 1
        assert "6 månader" in gliner_items[0].excerpt
        assert gliner_items[0].provenance["need_role"] == "DURATION"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_jev_no_persists_nothing(db_factory):
    engine, factory = db_factory
    item_id = await seed_database(factory, need_id="n1", excerpt=BT17_CLAUSE)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    jev = FakeJev(choice="NO")
    propose = fake_propose({item_id: [("6 månader", "Tidsperiod")]})
    try:
        report = await run_step(factory, need=need, jev=jev, propose=propose)
        assert report is not None
        assert report.findings_persisted == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_existing_gliner_item_skips_reproposal(db_factory):
    engine, factory = db_factory
    await seed_database(factory, need_id="n1", excerpt=None)
    from app.services.execution.service import add_evidence_items
    from app.services.execution.snapshots import EvidenceItemSnapshot

    async with factory() as session:
        await add_evidence_items(
            session,
            evidence_set_id="es-1",
            items=[
                EvidenceItemSnapshot(
                    research_need_id="n1",
                    source_type="derived",
                    status="found",
                    title="old",
                    excerpt="old finding",
                    locator=None,
                    source_id="s2",
                    source_url=None,
                    provider="gliner_span_proposer",
                    score=None,
                    provenance={"derivation": "gliner_span_proposal"},
                    retrieved_at=datetime.now(timezone.utc),
                )
            ],
        )
        await session.commit()
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    jev = FakeJev(choice="YES")

    async def fail_propose(units, labels):
        raise AssertionError("need already proposed — must not run again")

    try:
        report = await run_step(factory, need=need, jev=jev, propose=fail_propose)
        assert report is not None
        assert report.units_scanned == 0
        assert report.inferences == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_connection_held_during_external_phase(tmp_path):
    """Root rule: another client must acquire a connection while the
    GLiNER2/Jev phase is pending. A one-connection pool makes retention fail."""
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'release.db'}", pool_size=1
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await seed_database(factory, need_id="n1", excerpt=BT17_CLAUSE)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    jev = FakeJev(choice="YES")
    released = asyncio.Event()

    async def propose_impl(units, labels):
        await asyncio.wait_for(released.wait(), timeout=5)
        return [
            UnitProposals(
                unit_id=unit.unit_id,
                proposals=(SpanProposal(span="6 månader", label="Tidsperiod"),),
            )
            for unit in units
        ]

    import app.services.research.gliner.service as svc

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(svc, "HttpJevSystemOne", lambda: jev)
    monkeypatch.setattr(svc, "propose_spans", propose_impl)
    step_task: asyncio.Task | None = None
    try:
        async def run_step_here():
            async with factory() as session:
                return await svc.maybe_run_gliner_step(
                    SimpleNamespace(factory=factory, evidence_set_id="es-1"),
                    session,
                    attempt=make_attempt(opted_in=True),
                    plan=ResearchPlan(needs=[need]),
                    assessment=make_assessment([need]),
                )

        step_task = asyncio.create_task(run_step_here())
        await asyncio.sleep(0.2)  # let the step enter the external phase

        from sqlalchemy import select

        async def second_client():
            async with factory() as session:
                await session.execute(select(EvidenceSet.id).limit(1))
            return True

        second = asyncio.create_task(second_client())
        done, _pending = await asyncio.wait({second}, timeout=3)
        assert done, "second client could not acquire a connection"
        released.set()
        report = await step_task
        assert report is not None
    finally:
        released.set()
        if step_task is not None:
            await asyncio.gather(step_task, return_exceptions=True)
        monkeypatch.undo()
        await engine.dispose()
