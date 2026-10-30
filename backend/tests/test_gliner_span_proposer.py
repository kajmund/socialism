"""Unit + integration tests for the optional GLiNER2 span proposer.

Covers the frozen E1–E3 contract rules (including cross-unit ambiguity), the
subprocess proposer lifecycle and typed errors, the opt-in gating, persisted
runtime needs and assessment rows, retry idempotency, explicit Jev budgets,
invalid Jev schema errors, the refreshed assessment, and the wave-body path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.knowledge_scope import customer_scope
from app.database.models import (
    Base,
    EvidenceSet,
    EvidenceSetItem,
    ExecutionAttempt,
    ExecutionRun,
    Kund,
    ResearchAssessment,
    ResearchNeedExecution,
    ResearchRuntimeNeed,
)
from app.services.execution.service import (
    add_evidence_items,
    list_evidence_quality,
    persist_runtime_needs,
    runtime_need_from_row,
)
from app.services.execution.snapshots import EvidenceItemSnapshot
from app.services.research.assessment import (
    ResearchAssessmentDraft,
    ResearchNeedAssessment,
)
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.gliner import service
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
    SpanProposal,
    UnitProposals,
)
from app.services.research.models import (
    InvalidResearchPlanError,
    ResearchContext,
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
    return SimpleNamespace(id="at-1", configuration_snapshot=snapshot)


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


def make_assessment_row(needs: list[ResearchNeed]) -> SimpleNamespace:
    """A persisted-research-assessment-like row (need_assessments are JSON)."""
    return SimpleNamespace(
        result="insufficient",
        rationale="test",
        need_assessments=[
            {
                "research_need_id": need.id,
                "sufficient": False,
                "supporting_evidence_ids": [],
                "missing_or_weak": "",
                "contradictions": [],
                "further_information": None,
            }
            for need in needs
        ],
        gaps=[],
        contradictions=[],
        considered_evidence_ids=[],
        model_provider=None,
        model_name=None,
        model_version=None,
    )


# ---------------------------------------------------------------- contract


def test_canon_and_canon_value_frozen_rules():
    assert canon("[nio (9)] månader") == "nio (9) månader"
    assert canon_value("inom 30 dagar") == "30 dagar"
    assert canon_value("2 veckors") == "2 veckor"
    assert canon_value("i 6 månader") == "6 månader"
    assert canon_value("minst 500 kr") == "minst 500 kr"


def test_operational_role_bt17():
    assert operational_role("6 månader", BT17_CLAUSE) == "DURATION"
    assert operational_role("2 veckors", BT17_CLAUSE) == "NOTICE"


def test_operational_role_word_boundary_guard():
    assert operational_role("12 m å naderna", BT13_CLAUSE) == "MONEY"


def test_operational_role_unknown():
    assert operational_role("finns inte", BT17_CLAUSE) is None


def _verdict(span: str, choice: str = "YES", unit_text: str = "") -> SpanVerdict:
    return SpanVerdict(
        span=span,
        need_type="PERIOD",
        prompt_version="span-need-contrast-v1",
        choice=choice,
        unit_id="u1",
        unit_text=unit_text,
    )


def test_derive_findings_single_yes():
    findings = derive_findings(
        [_verdict("6 månader", unit_text=BT17_CLAUSE)],
        need_type="PERIOD",
        need_role="DURATION",
    )
    assert [f.state for f in findings] == [VERIFIED]
    assert findings[0].value == "6 månader"
    assert findings[0].prompt_version == "span-need-contrast-v1"
    assert findings[0].unit_id == "u1"


def test_derive_findings_rejected():
    findings = derive_findings(
        [_verdict("Enligt LAS", choice="NO", unit_text="Uppsägningstid Enligt LAS")],
        need_type="NOTICE_PERIOD",
        need_role="NOTICE",
    )
    assert [f.state for f in findings] == [REJECTED]


def test_derive_findings_bt17_role_split():
    findings = derive_findings(
        [
            _verdict("6 månader", unit_text=BT17_CLAUSE),
            _verdict("2 veckors", unit_text=BT17_CLAUSE),
        ],
        need_type="PERIOD",
        need_role="DURATION",
    )
    by_span = {f.span: f.state for f in findings}
    assert by_span["6 månader"] == VERIFIED
    assert "2 veckors" not in by_span


def test_derive_findings_ambiguous_across_units():
    """Two competing values in DIFFERENT TextUnits must collide into AMBIGUOUS."""
    findings = derive_findings(
        [
            _verdict("30 dagar", unit_text="Betalning inom 30 dagar."),
            _verdict("60 dagar", unit_text="Leverans inom 60 dagar."),
        ],
        need_type="PERIOD",
        need_role="DEADLINE",
    )
    assert {f.state for f in findings} == {AMBIGUOUS}


def test_derive_findings_unknown_role_fails_safe():
    findings = derive_findings(
        [
            _verdict("6 månader", unit_text=BT17_CLAUSE),
            _verdict("finns inte i texten", unit_text=BT17_CLAUSE),
        ],
        need_type="PERIOD",
        need_role="DURATION",
    )
    assert {f.state for f in findings} == {AMBIGUOUS}


def test_derive_findings_no_role_fails_safe():
    findings = derive_findings(
        [
            _verdict("6 månader", unit_text=BT17_CLAUSE),
            _verdict("2 veckors", unit_text=BT17_CLAUSE),
        ],
        need_type="PERIOD",
        need_role="",
    )
    assert {f.state for f in findings} == {AMBIGUOUS}


def test_verification_question_versions():
    assert verification_question("DATE", "12 maj")["prompt_version"] == "span-date-v1"
    assert (
        verification_question("PERIOD", "30 dagar")["prompt_version"]
        == "span-need-contrast-v1"
    )


# ---------------------------------------------------------------- gating


@pytest.mark.asyncio
async def test_step_disabled_is_no_op(monkeypatch):
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", False)

    async def fail(*args, **kwargs):
        raise AssertionError("proposer must not run when disabled")

    monkeypatch.setattr(service, "propose_spans", fail)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    result = await service.maybe_run_gliner_step(
        SimpleNamespace(), None,
        attempt=make_attempt(opted_in=True),
        plan=ResearchPlan(needs=[need]),
        assessment=make_assessment_row([need]),
        wave=0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_step_opted_out_is_no_op(monkeypatch):
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)

    async def fail(*args, **kwargs):
        raise AssertionError("proposer must not run when the run did not opt in")

    monkeypatch.setattr(service, "propose_spans", fail)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    result = await service.maybe_run_gliner_step(
        SimpleNamespace(), None,
        attempt=make_attempt(opted_in=False),
        plan=ResearchPlan(needs=[need]),
        assessment=make_assessment_row([need]),
        wave=0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_step_sufficient_assessment_is_no_op(monkeypatch):
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)

    async def fail(*args, **kwargs):
        raise AssertionError("proposer must not run when nothing is missing")

    monkeypatch.setattr(service, "propose_spans", fail)
    need = make_need("n1", span_types=["PERIOD"])
    row = make_assessment_row([need])
    row.result = "sufficient"
    result = await service.maybe_run_gliner_step(
        SimpleNamespace(), None,
        attempt=make_attempt(opted_in=True),
        plan=ResearchPlan(needs=[need]),
        assessment=row,
        wave=0,
    )
    assert result is None


@pytest.mark.asyncio
async def test_step_no_span_types_is_no_op(monkeypatch):
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)

    async def fail(*args, **kwargs):
        raise AssertionError("proposer must not run without declared span types")

    monkeypatch.setattr(service, "propose_spans", fail)
    need = make_need("n1")
    result = await service.maybe_run_gliner_step(
        SimpleNamespace(), None,
        attempt=make_attempt(opted_in=True),
        plan=ResearchPlan(needs=[need]),
        assessment=make_assessment_row([need]),
        wave=0,
    )
    assert result is None


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


# ---------------------------------------------------------------- db helpers


async def _seed_research(factory, *, excerpt1: str, excerpt2: str | None = None):
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
                status="researching",
                configuration_snapshot={"gliner_span_proposer": True},
                input_snapshot={},
                research_wave=0,
            )
        )
        session.add(EvidenceSet(id="es-1", run_id="run-1", status="building"))
        session.add(
            ResearchNeedExecution(
                id="ne-1", attempt_id="at-1", research_need_id="n1", status="completed"
            )
        )
        session.add(
            ResearchRuntimeNeed(
                id="rn-1",
                attempt_id="at-1",
                research_need_id="n1",
                question="Vilken betalningsfrist gäller?",
                why_needed="test",
                question_key="qk1",
                span_types=["PERIOD"],
                span_role="DEADLINE",
                origin="initial",
                wave_number=0,
            )
        )
        await session.commit()
    excerpts = [excerpt1] + ([excerpt2] if excerpt2 else [])
    async with factory() as session:
        stored = await add_evidence_items(
            session,
            evidence_set_id="es-1",
            items=[
                EvidenceItemSnapshot(
                    research_need_id="n1",
                    source_type="swedish_law",
                    status="found",
                    title="t",
                    excerpt=excerpt,
                    locator=None,
                    source_id=f"s{index}",
                    source_url=None,
                    provider="test",
                    score=None,
                    provenance={},
                    retrieved_at=datetime.now(timezone.utc),
                )
                for index, excerpt in enumerate(excerpts)
            ],
        )
        await session.commit()
    return [item.id for item in stored]


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


class CountingJev:
    def __init__(self, choice: str = "YES") -> None:
        self.choice = choice
        self.calls = 0

    async def ask(self, *, state, questions, model, timeout_seconds):
        self.calls += 1
        return SimpleNamespace(answers={"evidence": {"choice": self.choice}})


def fake_propose(proposals: dict[str, list[tuple[str, str]]]):
    async def propose(units, labels):
        out = []
        for unit in units:
            entries = proposals.get(unit.unit_id, [])
            out.append(
                UnitProposals(
                    unit_id=unit.unit_id,
                    proposals=tuple(
                        SpanProposal(span=span, label=label) for span, label in entries
                    ),
                )
            )
        return out

    return propose


class _StepAssessor:
    async def assess(self, plan, evidence):
        return ResearchAssessmentDraft(
            result="insufficient",
            rationale="test",
            need_assessments=[
                ResearchNeedAssessment(research_need_id=need.id, sufficient=False)
                for need in plan.needs
            ],
        )


async def run_step(factory, *, need, jev, propose, attempt=None):
    import app.services.research.gliner.service as svc

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(svc, "HttpJevSystemOne", lambda: jev)
    monkeypatch.setattr(svc, "propose_spans", propose)
    try:
        async with factory() as session:
            return await svc.maybe_run_gliner_step(
                SimpleNamespace(
                    factory=factory,
                    evidence_set_id="es-1",
                    assessor=_StepAssessor(),
                    router=None,
                    provider_descriptors=None,
                    relevance_assessor=None,
                ),
                session,
                attempt=attempt or make_attempt(opted_in=True),
                plan=ResearchPlan(needs=[need]),
                assessment=make_assessment_row([need]),
                wave=0,
            )
    finally:
        monkeypatch.undo()


async def _gliner_items(factory):
    async with factory() as session:
        rows = (
            await session.execute(
                select(EvidenceSetItem).where(EvidenceSetItem.evidence_set_id == "es-1")
            )
        ).scalars().all()
    return [
        row for row in rows
        if (row.provenance or {}).get("derivation") == "gliner_span_proposal"
    ]


# ---------------------------------------------------------------- service


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
    import app.services.research.gliner.service as svc

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(settings.gliner_span_proposer, "max_jev_calls_per_need", 1)
    monkeypatch.setattr(svc, "HttpJevSystemOne", lambda: jev)
    monkeypatch.setattr(svc, "propose_spans", propose)
    try:
        async with factory() as session:
            result = await svc.maybe_run_gliner_step(
                SimpleNamespace(
                    factory=factory,
                    evidence_set_id="es-1",
                    assessor=_StepAssessor(),
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
        assert items[0].provenance["jev_budget_truncated"] is True
    finally:
        monkeypatch.undo()
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


# ---------------------------------------------------------------- env


def test_env_nested_delimiter_overrides_gliner_settings(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("GLINER_SPAN_PROPOSER__ENABLED", "true")
    instance = Settings(_env_file=None, database_url="sqlite+aiosqlite://")
    assert instance.gliner_span_proposer.enabled is True
    monkeypatch.delenv("GLINER_SPAN_PROPOSER__ENABLED")
    instance = Settings(_env_file=None, database_url="sqlite+aiosqlite://")
    assert instance.gliner_span_proposer.enabled is False


# ---------------------------------------------------------------- wave body


class FakeAssessor:
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
    assessor = FakeAssessor()
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

    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(service, "HttpJevSystemOne", lambda: jev)
    monkeypatch.setattr(service, "propose_spans", propose)

    async def no_decision(*args, **kwargs):
        return None

    monkeypatch.setattr(loop_control, "_decide_research_wave", no_decision)

    config = ResearchWaveConfig(
        factory=factory,
        attempt_id="at-1",
        evidence_set_id="es-1",
        context=ResearchContext(scope=customer_scope(1), limit=10, attempt_id="at-1"),
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
