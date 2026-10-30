"""Shared fixtures, fakes and seeding for the GLiNER2 span-proposer tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.database.models import (
    EvidenceSet,
    EvidenceSetItem,
    ExecutionAttempt,
    ExecutionRun,
    Kund,
    ResearchNeedExecution,
    ResearchRuntimeNeed,
)
from app.services.execution.service import add_evidence_items
from app.services.execution.snapshots import EvidenceItemSnapshot
from app.services.research.assessment import (
    ResearchAssessmentDraft,
    ResearchNeedAssessment,
)
from app.services.research.gliner.proposer import SpanProposal, UnitProposals
from app.services.research.models import ResearchNeed, ResearchPlan


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


class StepAssessor:
    async def assess(self, plan, evidence):
        return ResearchAssessmentDraft(
            result="insufficient",
            rationale="test",
            need_assessments=[
                ResearchNeedAssessment(research_need_id=need.id, sufficient=False)
                for need in plan.needs
            ],
        )


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





async def run_step(factory, *, need, jev, propose, attempt=None):
    import app.services.research.gliner.proposal as proposal_mod
    import app.services.research.gliner.service as svc

    from app.config import settings

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(settings.gliner_span_proposer, "enabled", True)
    monkeypatch.setattr(svc, "HttpJevSystemOne", lambda: jev)
    monkeypatch.setattr(proposal_mod, "propose_spans", propose)
    try:
        async with factory() as session:
            return await svc.maybe_run_gliner_step(
                SimpleNamespace(
                    factory=factory,
                    evidence_set_id="es-1",
                    assessor=StepAssessor(),
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
