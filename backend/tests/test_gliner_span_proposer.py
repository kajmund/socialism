"""Unit tests for the frozen GLiNER2 span contract, gating and settings."""

from __future__ import annotations

import pytest

from app.config import settings
from app.services.research.gliner import proposal, service
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
from app.services.research.models import (
    InvalidResearchPlanError,
    ResearchPlan,
)
from app.services.research.plan import validate_research_plan
from tests.gliner_test_helpers import (
    make_assessment_row,
    make_attempt,
    make_need,
)

BT17_CLAUSE = "Syntetisk tidsklausul: Avtalet gäller i 6 månader med 2 veckors uppsägningstid"
BT13_CLAUSE = (
    "Syntetisk ansvarsklausul: Ansvar för intrång i immateriell rätt ska, utom vid grov "
    "vårdslöshet eller uppsåt, vara begränsat till arvodet för Tjänsten och vid "
    "löpande arvode, utgörs arvodet av arvodet för de senaste 12 månaderna för Tjänsten."
)


def _verdict(span: str, choice: str = "YES", unit_text: str = "") -> SpanVerdict:
    return SpanVerdict(
        span=span,
        need_type="PERIOD",
        prompt_version="span-need-contrast-v1",
        choice=choice,
        unit_id="u1",
        unit_text=unit_text,
    )


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


def test_same_span_different_units_keeps_per_unit_roles():
    """The same span text can carry different operational roles in different
    TextUnits; findings must not depend on verdict order."""
    notice_unit = "Uppsägningstid 30 dagar."
    deadline_unit = "Betalning inom 30 dagar."
    verdicts = [
        _verdict("30 dagar", unit_text=notice_unit),
        _verdict("30 dagar", unit_text=deadline_unit),
    ]
    for ordered in (verdicts, list(reversed(verdicts))):
        findings = derive_findings(
            ordered, need_type="PERIOD", need_role="DEADLINE"
        )
        assert [(f.span, f.state, f.role) for f in findings] == [
            ("30 dagar", VERIFIED, "DEADLINE")
        ]


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

    monkeypatch.setattr(proposal, "propose_spans", fail)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    result = await service.maybe_run_gliner_step(
        None, None,
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

    monkeypatch.setattr(proposal, "propose_spans", fail)
    need = make_need("n1", span_types=["PERIOD"], span_role="DURATION")
    result = await service.maybe_run_gliner_step(
        None, None,
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

    monkeypatch.setattr(proposal, "propose_spans", fail)
    need = make_need("n1", span_types=["PERIOD"])
    row = make_assessment_row([need])
    row.result = "sufficient"
    result = await service.maybe_run_gliner_step(
        None, None,
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

    monkeypatch.setattr(proposal, "propose_spans", fail)
    need = make_need("n1")
    result = await service.maybe_run_gliner_step(
        None, None,
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


# ---------------------------------------------------------------- env


def test_env_nested_delimiter_overrides_gliner_settings(monkeypatch):
    from app.config import Settings

    monkeypatch.setenv("GLINER_SPAN_PROPOSER__ENABLED", "true")
    instance = Settings(_env_file=None, database_url="sqlite+aiosqlite://")
    assert instance.gliner_span_proposer.enabled is True
    monkeypatch.delenv("GLINER_SPAN_PROPOSER__ENABLED")
    instance = Settings(_env_file=None, database_url="sqlite+aiosqlite://")
    assert instance.gliner_span_proposer.enabled is False
