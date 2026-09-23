"""Legal ResearchNeed validation before retrieval. No live model or MCP."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.llm.legal_question_validator import (
    LegalQuestionValidationModel,
    LlmLegalQuestionValidator,
)
from app.services.execution import list_runtime_needs
from app.services.lagen_nu.question_validation import (
    CIVIL_AVTL_SPLIT_QUESTION,
    CIVIL_COURT_AVTL_QUESTION,
    COMMERCIAL_AVTL_QUESTION,
    LEGAL_RESEARCH_SOURCE_TYPES,
    MARKET_AVLK_SPLIT_QUESTION,
    MARKET_COURT_AVLK_QUESTION,
    MIXED_MD_AVTL_QUESTION,
    LegalFollowUpPlannerAdapter,
    LegalNeedNormalizer,
    LegalQuestionVerdict,
    LegalResearchPlannerAdapter,
    ScriptedLegalQuestionValidator,
    apply_legal_verdict_to_draft,
    canonical_legal_question_verdicts,
    coherent_commercial_avtl_verdict,
    is_legal_research_need,
    mixed_md_avtl_verdict,
)
from app.services.lagen_nu.research_source import LagenNuResearchSource
from app.services.research.execution import execute_attempt_research
from app.services.research.followup import FollowUpNeedDraft, NoOpFollowUpPlanner
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.planner import FakeResearchPlanner, ResearchNeedDraft, ResearchObjective
from tests.test_research_execution import (
    RecordingSource,
    _created_attempt,
    _router,
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
        yield session, factory
    await engine.dispose()


def _scripted() -> ScriptedLegalQuestionValidator:
    return ScriptedLegalQuestionValidator(canonical_legal_question_verdicts())


def _legal_draft(question: str) -> ResearchNeedDraft:
    return ResearchNeedDraft(
        question=question,
        why_needed="Kartlägg praxis för oskäliga villkor.",
        source_types=["swedish_case_law"],
        proposed_id="research_1",
    )


class QuestionRecordingSource(RecordingSource):
    def __init__(self, source_type: str) -> None:
        super().__init__(source_type, excerpt="praxis")
        self.questions: list[str] = []

    async def research(self, need, context):
        self.questions.append(need.question)
        return await super().research(need, context)


class BoomLagenNuClient:
    async def resolve_citation(self, citation: str, source: str | None = None):
        raise AssertionError(f"must not retrieve: resolve_citation {citation}")

    async def search(self, query: str, source: str | None = None, limit: int = 10):
        raise AssertionError(f"must not retrieve: search {query}")

    async def get_document(self, uri: str, max_chars: int | None = None):
        raise AssertionError(f"must not retrieve: get_document {uri}")


@pytest.mark.asyncio
async def test_mixed_md_avtl_question_is_split():
    normalizer = LegalNeedNormalizer(_scripted())
    expanded = await normalizer.normalize_drafts([_legal_draft(MIXED_MD_AVTL_QUESTION)])
    questions = [draft.question for draft in expanded]
    assert MIXED_MD_AVTL_QUESTION not in questions
    assert questions == [MARKET_AVLK_SPLIT_QUESTION, CIVIL_AVTL_SPLIT_QUESTION]
    assert all(draft.already_normalized for draft in expanded)
    assert all(draft.original_question == MIXED_MD_AVTL_QUESTION for draft in expanded)
    assert all(draft.generated_from == "research_1" for draft in expanded)
    assert all(draft.original_need_id == "research_1" for draft in expanded)
    assert all("blandar" in draft.normalization_reason for draft in expanded)


@pytest.mark.asyncio
async def test_coherent_civil_avtl_question_is_kept():
    normalizer = LegalNeedNormalizer(_scripted())
    expanded = await normalizer.normalize_drafts([_legal_draft(CIVIL_COURT_AVTL_QUESTION)])
    assert [draft.question for draft in expanded] == [CIVIL_COURT_AVTL_QUESTION]
    assert expanded[0].already_normalized is True
    assert expanded[0].original_question == ""


@pytest.mark.asyncio
async def test_coherent_market_avlk_question_is_kept():
    normalizer = LegalNeedNormalizer(_scripted())
    expanded = await normalizer.normalize_drafts([_legal_draft(MARKET_COURT_AVLK_QUESTION)])
    assert [draft.question for draft in expanded] == [MARKET_COURT_AVLK_QUESTION]


@pytest.mark.asyncio
async def test_commercial_avtl_question_is_not_pulled_into_avlk():
    normalizer = LegalNeedNormalizer(_scripted())
    expanded = await normalizer.normalize_drafts([_legal_draft(COMMERCIAL_AVTL_QUESTION)])
    assert [draft.question for draft in expanded] == [COMMERCIAL_AVTL_QUESTION]
    verdict = coherent_commercial_avtl_verdict()
    assert "AVLK" not in verdict.provisions
    assert all("AVLK" not in draft.question for draft in expanded)


@pytest.mark.asyncio
async def test_already_normalized_need_is_not_validated_again():
    validator = _scripted()
    normalizer = LegalNeedNormalizer(validator)
    first = await normalizer.normalize_drafts([_legal_draft(MIXED_MD_AVTL_QUESTION)])
    second = await normalizer.normalize_drafts(first)
    assert validator.calls == [MIXED_MD_AVTL_QUESTION]
    assert [draft.question for draft in second] == [draft.question for draft in first]


def test_schema_rejects_keeping_a_mixed_track():
    with pytest.raises(ValidationError, match="mixed legal tracks are not coherent"):
        LegalQuestionValidationModel.model_validate(
            {
                "is_coherent": True,
                "legal_track": "mixed",
                "action": "keep",
                "rationale": "no",
            }
        )


def test_schema_requires_split_questions():
    with pytest.raises(ValidationError, match="at least two"):
        LegalQuestionValidationModel.model_validate(
            {
                "is_coherent": False,
                "legal_track": "mixed",
                "action": "split",
                "split_questions": ["only one"],
            }
        )


@pytest.mark.asyncio
async def test_llm_validator_uses_structured_output_for_mixed_question():
    async def complete(messages, model):
        assert MIXED_MD_AVTL_QUESTION in messages[-1]["content"]
        assert "Hämta inte" in messages[0]["content"] or "Do not fetch" in messages[0]["content"]
        verdict = mixed_md_avtl_verdict()
        return model.model_validate(
            {
                "is_coherent": verdict.is_coherent,
                "issue_type": verdict.issue_type,
                "legal_track": verdict.legal_track,
                "institutions": list(verdict.institutions),
                "provisions": list(verdict.provisions),
                "remedy": verdict.remedy,
                "problems": list(verdict.problems),
                "action": verdict.action,
                "split_questions": list(verdict.split_questions),
                "rationale": verdict.rationale,
            }
        )

    validator = LlmLegalQuestionValidator(
        completer=complete,
        system_prompt="Validera juridiska ResearchNeeds. Hämta inte evidens.",
        user_prompt="Fråga:\n{question}\nwhy_needed:\n{why_needed}\nsource_types:\n{source_types}",
    )
    verdict = await validator.validate(
        question=MIXED_MD_AVTL_QUESTION,
        why_needed="praxis",
        source_types=["swedish_case_law"],
    )
    assert verdict.action == "split"
    assert verdict.split_questions == (
        MARKET_AVLK_SPLIT_QUESTION,
        CIVIL_AVTL_SPLIT_QUESTION,
    )


@pytest.mark.asyncio
async def test_planner_adapter_splits_before_ids_are_assigned():
    planner = LegalResearchPlannerAdapter(
        FakeResearchPlanner([_legal_draft(MIXED_MD_AVTL_QUESTION)]),
        LegalNeedNormalizer(_scripted()),
    )
    drafts = await planner.plan_research(
        objective=ResearchObjective(objective="Oskäliga villkor"),
    )
    assert [draft.question for draft in drafts] == [
        MARKET_AVLK_SPLIT_QUESTION,
        CIVIL_AVTL_SPLIT_QUESTION,
    ]


@pytest.mark.asyncio
async def test_follow_up_adapter_splits_mixed_follow_up():
    class MixedFollowUp:
        async def plan_follow_ups(self, **kwargs):
            return [
                FollowUpNeedDraft(
                    question=MIXED_MD_AVTL_QUESTION,
                    why_needed="Lucka i praxis",
                    source_types=["swedish_case_law"],
                    parent_research_need_id="research_1",
                )
            ]

    adapter = LegalFollowUpPlannerAdapter(MixedFollowUp(), LegalNeedNormalizer(_scripted()))
    drafts = await adapter.plan_follow_ups(
        plan=ResearchPlan(),
        assessment=None,
        evidence=[],
        previous_needs=[],
    )
    assert [draft.question for draft in drafts] == [
        MARKET_AVLK_SPLIT_QUESTION,
        CIVIL_AVTL_SPLIT_QUESTION,
    ]
    assert all(draft.parent_research_need_id == "research_1" for draft in drafts)


@pytest.mark.asyncio
async def test_provider_refuses_mixed_question_without_retrieval():
    provider = LagenNuResearchSource(
        source_type="swedish_case_law",
        client=BoomLagenNuClient(),
        question_validator=_scripted(),
    )
    from tests.test_research import _context, _need

    evidence = await provider.research(
        _need("swedish_case_law", question=MIXED_MD_AVTL_QUESTION),
        _context(),
    )
    assert evidence[0].status == "not_found"
    assert evidence[0].metadata["failure_category"] == "question_incoherent"
    assert evidence[0].metadata["reason"] == "question_incoherent"


@pytest.mark.asyncio
async def test_already_normalized_need_skips_provider_validator():
    validator = _scripted()
    provider = LagenNuResearchSource(
        source_type="swedish_case_law",
        client=BoomLagenNuClient(),
        question_validator=validator,
    )
    from tests.test_research import _context

    need = ResearchNeed(
        id="research_1",
        question=CIVIL_COURT_AVTL_QUESTION,
        why_needed="praxis",
        source_types=["swedish_case_law"],
        already_normalized=True,
    )
    with pytest.raises(AssertionError, match="must not retrieve"):
        await provider.research(need, _context())
    assert validator.calls == []


@pytest.mark.asyncio
async def test_execution_does_not_retrieve_mixed_md_avtl_question(db):
    session, factory = db
    _customer, _run, attempt = await _created_attempt(session)
    source = QuestionRecordingSource("swedish_case_law")
    router, _ = _router(source)
    plan = ResearchPlan(
        needs=[
            ResearchNeed(
                id="mixed",
                question=MIXED_MD_AVTL_QUESTION,
                why_needed="Kartlägg praxis för oskäliga villkor.",
                source_types=["swedish_case_law"],
            )
        ]
    )
    result = await execute_attempt_research(
        session,
        attempt_id=attempt.id,
        research_plan=plan,
        router=router,
        session_factory=factory,
        planner=NoOpFollowUpPlanner(),
        need_normalizer=LegalNeedNormalizer(_scripted()),
    )
    assert result.status == "ready"
    assert MIXED_MD_AVTL_QUESTION not in source.questions
    assert MARKET_AVLK_SPLIT_QUESTION in source.questions
    assert CIVIL_AVTL_SPLIT_QUESTION in source.questions
    rows = await list_runtime_needs(session, attempt.id)
    questions = {row.question for row in rows}
    assert MIXED_MD_AVTL_QUESTION not in questions
    assert MARKET_AVLK_SPLIT_QUESTION in questions
    assert CIVIL_AVTL_SPLIT_QUESTION in questions
    assert all(row.already_normalized for row in rows)
    assert all(row.original_question == MIXED_MD_AVTL_QUESTION for row in rows)


def test_non_legal_needs_are_not_legal_research():
    assert is_legal_research_need(["swedish_case_law"])
    assert is_legal_research_need(["web", "swedish_law"])
    assert not is_legal_research_need(["case_knowledge", "web"])
    assert LEGAL_RESEARCH_SOURCE_TYPES == {
        "swedish_law",
        "swedish_case_law",
        "swedish_preparatory_works",
    }


def test_apply_keep_marks_normalized_without_changing_question():
    draft = _legal_draft(CIVIL_COURT_AVTL_QUESTION)
    kept = apply_legal_verdict_to_draft(
        draft,
        LegalQuestionVerdict(
            is_coherent=True,
            issue_type="unfair_contract_terms",
            legal_track="civil_law",
            institutions=(),
            provisions=(),
            remedy="",
            problems=(),
            action="keep",
            rationale="ok",
        ),
    )
    assert kept[0].question == CIVIL_COURT_AVTL_QUESTION
    assert kept[0].already_normalized is True
