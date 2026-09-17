"""Run one general question through the existing Attempt research engine."""

from __future__ import annotations

from copy import deepcopy

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ResearchQuestion
from app.services.execution.service import (
    create_attempt,
    get_attempt,
    list_runtime_needs,
    runtime_need_from_row,
)
from app.services.research.assessment import ResearchAssessor
from app.services.research.completeness import ResearchCompletenessReviewer
from app.services.research.execution import (
    ResearchRouterFactory,
    execute_attempt_research,
)
from app.services.research.followup import FollowUpResearchPlanner
from app.services.research.planner import ResearchObjective, ResearchPlanner
from app.services.research.quality import EvidenceRelevanceAssessor
from app.services.research.question_execution import (
    ExecutableResearchQuestion,
    QuestionFollowUpDraft,
    QuestionResearchOutcome,
)
from app.services.research.question_graph import QuestionEvidenceGraph
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph


class AttemptResearchQuestionWorker:
    """Adapter from a DAG node to a child Attempt with frozen evidence."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        router_factory: ResearchRouterFactory,
        research_planner: ResearchPlanner,
        assessor: ResearchAssessor | None = None,
        follow_up_planner: FollowUpResearchPlanner | None = None,
        completeness_reviewer: ResearchCompletenessReviewer | None = None,
        relevance_assessor: EvidenceRelevanceAssessor | None = None,
        question_graph: QuestionEvidenceGraph | None = None,
        research_concurrency: int | None = None,
    ) -> None:
        self._factory = session_factory
        self._router_factory = router_factory
        self._research_planner = research_planner
        self._assessor = assessor
        self._follow_up_planner = follow_up_planner
        self._completeness_reviewer = completeness_reviewer
        self._relevance_assessor = relevance_assessor
        self._question_graph = question_graph or SqlQuestionEvidenceGraph()
        self._research_concurrency = research_concurrency

    async def research_question(
        self, question: ExecutableResearchQuestion
    ) -> QuestionResearchOutcome:
        child_attempt_id = await self._ensure_child_attempt(question)
        async with self._factory() as session:
            result = await execute_attempt_research(
                session,
                attempt_id=child_attempt_id,
                research_objective=ResearchObjective(
                    objective=question.question,
                    context={
                        "research_question_id": question.id,
                        "specific_question_id": question.specific_question_id,
                        "knowledge_question_id": question.knowledge_question_id,
                        "assigned_expert_id": question.assigned_expert_id,
                        "why_needed": question.why_needed,
                    },
                ),
                research_planner=self._research_planner,
                router_factory=self._router_factory,
                assessor=self._assessor,
                planner=self._follow_up_planner,
                completeness_reviewer=self._completeness_reviewer,
                relevance_assessor=self._relevance_assessor,
                question_graph=self._question_graph,
                session_factory=self._factory,
                concurrency=self._research_concurrency,
            )
        if result.status != "ready":
            raise RuntimeError(
                f"research child Attempt {child_attempt_id} finished as {result.status}"
            )
        follow_ups = await self._completed_follow_ups(
            child_attempt_id=child_attempt_id,
            assigned_expert_id=question.assigned_expert_id,
        )
        return QuestionResearchOutcome(
            execution_attempt_id=child_attempt_id,
            follow_ups=follow_ups,
        )

    async def _ensure_child_attempt(self, question: ExecutableResearchQuestion) -> str:
        async with self._factory() as session:
            row = await session.get(ResearchQuestion, question.id)
            if row is None or row.attempt_id != question.attempt_id:
                raise RuntimeError(
                    f"research question is outside its parent Attempt: {question.id}"
                )
            if row.execution_attempt_id is not None:
                child = await get_attempt(session, row.execution_attempt_id)
                if child.parent_attempt_id != question.attempt_id:
                    raise RuntimeError(
                        f"research question child Attempt has invalid parent: {question.id}"
                    )
                return child.id
            parent = await get_attempt(session, question.attempt_id)
            child = await create_attempt(
                session,
                run_id=parent.run_id,
                parent_attempt_id=parent.id,
                attempt_type="research_question",
                configuration_snapshot=deepcopy(parent.configuration_snapshot),
                input_snapshot={
                    "research_question_id": question.id,
                    "specific_question_id": question.specific_question_id,
                    "knowledge_question_id": question.knowledge_question_id,
                    "assigned_expert_id": question.assigned_expert_id,
                },
            )
            row.execution_attempt_id = child.id
            await session.commit()
            return child.id

    async def _completed_follow_ups(
        self,
        *,
        child_attempt_id: str,
        assigned_expert_id: str,
    ) -> tuple[QuestionFollowUpDraft, ...]:
        async with self._factory() as session:
            runtime_needs = [
                runtime_need_from_row(row)
                for row in await list_runtime_needs(session, child_attempt_id)
            ]
        return tuple(
            QuestionFollowUpDraft(
                question=need.question,
                why_needed=need.why_needed,
                assigned_expert_id=assigned_expert_id,
                raised_by_expert_ids=(assigned_expert_id,),
                runtime_need_id=need.research_need_id,
                already_researched=True,
            )
            for need in runtime_needs
            if need.origin != "initial"
        )
