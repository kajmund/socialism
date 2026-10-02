import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from app.llm.research_assessment import (
    EvidenceSufficiencyModel,
    LlmResearchAssessor,
    NeedSufficiencyModel,
)
from app.services.execution import create_attempt, create_run
from app.services.knowledge.models import KnowledgeScope
from app.services.research.models import ResearchContext, ResearchNeed, research_evidence
from app.services.research.planner import ResearchObjective

MAIN = "Hur tillämpas 36 § avtalslagen i svensk rättspraxis?"
CHILD = "Vilken betydelse har senare lagändringar för 36 § avtalslagen?"


def need(*, question=CHILD, need_id="child", question_id="") -> ResearchNeed:
    return ResearchNeed(
        id=need_id,
        question=question,
        why_needed="Identifierad lucka",
        source_types=["swedish_preparatory_works"],
        knowledge_question_id=question_id,
    )


def context(*, customer_id=1, case_id=None) -> ResearchContext:
    return ResearchContext(
        scope=KnowledgeScope(customer_id=customer_id, module="dd", case_id=case_id)
    )


async def attempt(session, *, objective=MAIN):
    run = await create_run(session, customer_id=1, module="dd", title="Reuse contract", context={})
    row = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={},
        input_snapshot={"question": objective},
    )
    row.research_objective_snapshot = {"objective": objective, "context": {}}
    await session.flush()
    return row


def evidence(*, need_id="child", source_id="law", freshness="fresh"):
    return research_evidence(
        research_need_id=need_id,
        source_type="swedish_preparatory_works",
        status="found",
        provider="graph_v2",
        source_id=source_id,
        excerpt="36 § har en allmän jämkningsregel.",
        locator="a2.4",
        retrieved_at=datetime.now(UTC),
        metadata={"reuse": {"origin": "persistent_knowledge", "freshness": freshness}},
    )


def assessor(*, sufficient=True):
    async def complete(_messages, _model):
        payload = json.loads(_messages[1]["content"].split("\n", 1)[1])
        refs = [row["evidence_id"] for row in payload["evidence"]]
        return EvidenceSufficiencyModel(
            result="sufficient" if sufficient else "insufficient",
            rationale="Bedömd mot frågan",
            need_assessments=[
                NeedSufficiencyModel(
                    research_need_id="child",
                    sufficient=sufficient,
                    supporting_evidence_ids=refs if sufficient else [],
                    missing_or_weak="" if sufficient else "Senare lagändringar saknas",
                )
            ],
            considered_evidence_ids=refs,
        )

    completer = AsyncMock(side_effect=complete)
    adapter = LlmResearchAssessor(
        completer=completer,
        system_prompt="Test boundary",
        user_prompt="{plan_json}\n{evidence_json}",
    )
    return adapter, completer


def objective() -> ResearchObjective:
    return ResearchObjective(objective=MAIN)


class FreshSource:
    source_type = "swedish_preparatory_works"
    provider_id = "mock-public-source"

    def __init__(self):
        self.questions = []

    async def research(self, research_need, _context):
        self.questions.append(research_need.question)
        return [
            research_evidence(
                research_need_id=research_need.id,
                source_type=self.source_type,
                status="found",
                source_id="source:" + research_need.id,
                excerpt="Belagt svar om " + research_need.question,
                provider=self.provider_id,
                retrieved_at=datetime.now(UTC),
            )
        ]


async def reviewed_answer(plan, items):
    # Mock the judgment only; production still validates question and citation IDs.
    from app.services.research.assessment import ResearchNeedAssessment

    rows = []
    for research_need in plan.needs:
        supporting = [
            item.evidence_id
            for item in items
            if item.status == "found"
            and research_need.id in (item.research_need_ids or (item.research_need_id,))
        ]
        rows.append(
            ResearchNeedAssessment(
                research_need_id=research_need.id,
                sufficient=bool(supporting),
                supporting_evidence_ids=supporting,
            )
        )
    from app.services.research.assessment import ResearchAssessmentDraft

    return ResearchAssessmentDraft(
        result="sufficient" if all(row.sufficient for row in rows) else "insufficient",
        rationale="Mocked question-specific judgment",
        need_assessments=rows,
    )
