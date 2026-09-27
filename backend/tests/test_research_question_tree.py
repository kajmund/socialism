from __future__ import annotations

from collections.abc import Sequence

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.base import Base
from app.database.models import (
    Kund,
    ResearchAnswerChildLink,
    ResearchNeedExecution,
    ResearchProgressEvent,
    ResearchQuestionAnswer,
    ResearchQuestionNode,
)
from app.jev.system import JevSystemOneResult, JevUsage
from app.observability.research import research_obs_scope
from app.services.execution.service import create_attempt, create_evidence_set, create_run
from app.services.prompt_catalog import PROMPT_FIELDS
from app.services.research.progress import PROGRESS_IDEMPOTENCY_KEY_MAX
from app.services.research.question_tree import (
    TRANSIENT_QUESTION_PHASES,
    AnswerInput,
    ChildRedundancyDecision,
    CompletenessDecision,
    DecompositionDecision,
    GeneratedAnswer,
    GeneratedQuestion,
    QuestionTreeLimits,
    ReadinessDecision,
    RecursiveQuestionTree,
    StructureDecision,
    append_answer_version,
    fail_transient_question_nodes,
    get_or_create_root,
    knowledge_need_counts,
    list_question_nodes,
    settle_stranded_question_nodes,
    structure_action,
    tree_event_idempotency_key,
)
from app.services.research.question_tree_controller import (
    CHILD_REDUNDANCY_QUESTIONS,
    DECOMPOSABILITY_QUESTIONS,
    DECOMPOSITION_VALIDATION_QUESTIONS,
    RESEARCHABILITY_QUESTIONS,
    JevQuestionTreeController,
    classify_child_redundancy,
    classify_decomposability,
    classify_decomposition,
    classify_researchability,
)


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        customer = Kund(name="tree", slug="tree", available_modules=["dd"])
        session.add(customer)
        await session.flush()
        run = await create_run(
            session,
            customer_id=customer.id,
            module="dd",
            title="tree",
        )
        attempt = await create_attempt(session, run_id=run.id, attempt_type="research")
        await session.commit()
        yield session, attempt
    await engine.dispose()


def _decision(
    *,
    researchable: bool,
    decomposable: bool,
    noul: dict[str, float] | None = None,
    researchability_reason: str = "",
    decomposability_reason: str = "",
) -> StructureDecision:
    return StructureDecision(
        researchability="researchable" if researchable else "not_researchable",
        decomposability="decomposable" if decomposable else "not_decomposable",
        researchability_reason=researchability_reason
        or ("bounded_evidence_retrieval" if researchable else "not_bounded_for_retrieval"),
        decomposability_reason=decomposability_reason
        or (
            "multiple_distinct_researchable_subconclusions"
            if decomposable
            else "single_conclusion_or_mapping"
        ),
        noul={} if noul is None else dict(noul),
        researchability_confidence=0.9 if researchable else 0.1,
        decomposability_confidence=0.9 if decomposable else 0.1,
        threshold=0.8,
    )


class Controller:
    async def assess_structure(self, *, question: str) -> StructureDecision:
        leaf = question.startswith("atomic")
        return _decision(researchable=leaf, decomposable=not leaf, noul={"marker": float(leaf)})

    async def assess_synthesis_readiness(
        self, *, question: str, child_answers: Sequence[AnswerInput]
    ) -> ReadinessDecision:
        return ReadinessDecision(
            sufficient=bool(child_answers),
            material_gap=False,
            additional_research_likely_to_change_answer=False,
            noul={},
        )

    async def assess_completeness(
        self,
        *,
        question: str,
        answer: str,
        child_answers: Sequence[AnswerInput],
    ) -> CompletenessDecision:
        return CompletenessDecision(
            status="answered",
            material_gap=False,
            additional_research_likely_to_change_answer=False,
            noul={},
        )

    async def validate_decomposition(
        self, *, question: str, children: Sequence[str]
    ) -> DecompositionDecision:
        accepted = len(children) >= 2
        return DecompositionDecision(
            accepted=accepted,
            noul=_validation_noul(accepted=accepted),
            rejection_reason="" if accepted else "insufficient_semantic_progress",
            threshold=0.8,
        )

    async def validate_child_redundancy(
        self,
        *,
        parent: str,
        candidate: str,
        siblings: Sequence[str],
        ancestors: Sequence[str],
    ) -> ChildRedundancyDecision:
        return ChildRedundancyDecision(
            accepted=True,
            noul=_distinct_child_noul(),
            threshold=0.8,
        )


class Generator:
    def __init__(self) -> None:
        self.decomposition_calls = 0

    async def decompose(self, *, question: str):
        self.decomposition_calls += 1
        if question == "root":
            return [GeneratedQuestion("atomic one"), GeneratedQuestion("branch")]
        return [GeneratedQuestion("atomic two"), GeneratedQuestion("atomic three")]

    async def formulate_gap_questions(self, **_kwargs):
        return []

    async def synthesize_leaf(self, **_kwargs):
        return GeneratedAnswer(text="leaf", status="answered")

    async def synthesize_parent(self, **_kwargs):
        return GeneratedAnswer(text="parent", status="answered")


class GapController(Controller):
    async def assess_completeness(
        self,
        *,
        question: str,
        answer: str,
        child_answers: Sequence[AnswerInput],
    ) -> CompletenessDecision:
        return CompletenessDecision(
            status="answered_with_gaps",
            material_gap=True,
            additional_research_likely_to_change_answer=True,
            noul={"material_gap_remains": 0.95},
        )


class GapGenerator(Generator):
    async def formulate_gap_questions(self, **_kwargs):
        return [GeneratedQuestion("atomic gap")]


class AtomicController(Controller):
    async def assess_structure(self, *, question: str) -> StructureDecision:
        return _decision(researchable=True, decomposable=False, noul={"marker": 1.0})


@pytest.mark.asyncio
async def test_recursive_decomposition_only_exposes_atomic_leaves(db):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=Controller(),
        generator=Generator(),
        limits=QuestionTreeLimits(max_depth=3, max_children=3, max_questions=10),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(
        session,
        attempt_id=attempt.id,
        root_question="root",
    )
    assert {need.question for need in plan.needs} == {
        "atomic one",
        "atomic two",
        "atomic three",
    }
    assert all(need.question not in {"root", "branch"} for need in plan.needs)

    resumed = await tree.prepare_leaf_plan(
        session,
        attempt_id=attempt.id,
        root_question="root",
    )
    assert [need.id for need in resumed.needs] == [need.id for need in plan.needs]
    assert len(await list_question_nodes(session, attempt.id)) == 5


@pytest.mark.asyncio
async def test_atomic_evidence_gap_never_invokes_decomposition(db):
    session, attempt = db
    generator = Generator()
    tree = RecursiveQuestionTree(
        controller=AtomicController(),
        generator=generator,
        limits=QuestionTreeLimits(max_depth=3, max_children=3, max_questions=10),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(
        session,
        attempt_id=attempt.id,
        root_question="one bounded question",
    )
    assert [need.question for need in plan.needs] == ["one bounded question"]
    assert generator.decomposition_calls == 0


@pytest.mark.asyncio
async def test_depth_limit_stops_without_retrieving_composite_question(db):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=Controller(),
        generator=Generator(),
        limits=QuestionTreeLimits(max_depth=0, max_children=3, max_questions=10),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(
        session,
        attempt_id=attempt.id,
        root_question="root",
    )
    assert plan.needs == []
    [root] = await list_question_nodes(session, attempt.id)
    assert root.phase == "unresolved"
    assert root.researchability == "not_researchable"
    assert root.decomposability == "decomposable"
    assert root.completeness is None


@pytest.mark.asyncio
async def test_answer_versions_require_material_text_or_provenance_change(db):
    session, attempt = db
    root = await get_or_create_root(session, attempt_id=attempt.id, question="root")
    first, created = await append_answer_version(
        session,
        node=root,
        answer_text="same",
        status="answered",
    )
    assert created is True
    same, created = await append_answer_version(
        session,
        node=root,
        answer_text="same",
        status="answered_with_gaps",
    )
    assert created is False
    assert same.id == first.id
    changed, created = await append_answer_version(
        session,
        node=root,
        answer_text="materially changed",
        status="answered_with_gaps",
    )
    assert created is True
    assert changed.supersedes_answer_id == first.id
    answers = list(
        (
            await session.execute(
                ResearchQuestionAnswer.__table__.select().where(
                    ResearchQuestionAnswer.question_node_id == root.id
                )
            )
        ).all()
    )
    assert len(answers) == 2


@pytest.mark.asyncio
async def test_parent_provenance_and_gap_question_use_normal_pipeline(db):
    session, attempt = db
    evidence_set = await create_evidence_set(
        session,
        run_id=attempt.run_id,
        created_from_attempt_id=attempt.id,
    )
    root = await get_or_create_root(session, attempt_id=attempt.id, question="root")
    root.atomicity = "composite"
    root.phase = "decomposed"
    child = ResearchQuestionNode(
        id="child",
        attempt_id=attempt.id,
        parent_question_id=root.id,
        question="atomic child",
        depth=1,
        created_from="decomposition",
        phase="completed",
        atomicity="atomic",
        research_need_id=None,
    )
    session.add(child)
    await session.flush()
    child_answer, _ = await append_answer_version(
        session,
        node=child,
        answer_text="grounded child",
        status="answered",
    )
    tree = RecursiveQuestionTree(
        controller=GapController(),
        generator=GapGenerator(),
        limits=QuestionTreeLimits(max_depth=3, max_children=3, max_questions=10),
        source_types=["web"],
    )
    gap_plan = await tree.synthesize_wave(
        session,
        attempt_id=attempt.id,
        evidence_set_id=evidence_set.id,
    )
    assert [need.question for need in gap_plan.needs] == ["atomic gap"]
    await session.refresh(root)
    parent_answer = await session.get(ResearchQuestionAnswer, root.current_answer_id)
    assert parent_answer is not None
    links = list(
        (
            await session.execute(
                select(ResearchAnswerChildLink).where(
                    ResearchAnswerChildLink.answer_id == parent_answer.id
                )
            )
        ).scalars()
    )
    assert [link.child_answer_id for link in links] == [child_answer.id]


BROAD = "Hur tillämpas 36 § avtalslagen i svensk rättspraxis?"
LEAVES = (
    "Vilka rekvisit använder domstolarna vid 36 § avtalslagen?",
    "Vilka omständigheter väger tungt vid jämkning enligt 36 §?",
    "Vilken rättsföljd följer när 36 § tillämpas?",
)


def _conclusion_noul(*, one_conclusion: bool) -> dict[str, float]:
    return {
        "atomic_enough_for_evidence_retrieval": 0.95 if one_conclusion else 0.08,
        "contains_multiple_independent_information_needs": 0.04 if one_conclusion else 0.93,
        "requires_multiple_independently_grounded_conclusions": 0.05 if one_conclusion else 0.96,
        "can_be_answered_as_one_grounded_conclusion_or_mapping": 0.97 if one_conclusion else 0.07,
        "subconclusions_may_have_independent_evidence_or_outcomes": (
            0.06 if one_conclusion else 0.91
        ),
    }


# 2026-09-27 broad root under the retired atomicity questions. High retrieval
# score, low independent-needs score, and high separate-conclusion scores.
OBSERVED_UNDER_DECOMPOSED_ROOT = {
    "atomic_enough_for_evidence_retrieval": 0.9995,
    "contains_multiple_independent_information_needs": 0.0045,
    "requires_multiple_independently_grounded_conclusions": 0.96,
    "can_be_answered_as_one_grounded_conclusion_or_mapping": 0.04,
    "subconclusions_may_have_independent_evidence_or_outcomes": 0.94,
}
MAPPING_NOUL = _conclusion_noul(one_conclusion=True)
INDEPENDENT_CONCLUSIONS_NOUL = _conclusion_noul(one_conclusion=False)
BROAD_STRUCTURE_NOUL = {
    "bounded_for_evidence_retrieval": 0.9910,
    "can_produce_grounded_answer": 0.9548,
    "robust_answer_requires_multiple_distinct_subconclusions": 0.93,
    "subconclusions_can_be_researched_separately": 0.88,
    "subconclusions_would_be_useful_as_reusable_knowledge": 0.86,
}
MAPPING_STRUCTURE_NOUL = {
    "bounded_for_evidence_retrieval": 0.9846,
    "can_produce_grounded_answer": 0.8706,
    "robust_answer_requires_multiple_distinct_subconclusions": 0.0429,
    "subconclusions_can_be_researched_separately": 0.08,
    "subconclusions_would_be_useful_as_reusable_knowledge": 0.15,
}
DEFINITION_STRUCTURE_NOUL = {
    "bounded_for_evidence_retrieval": 0.97,
    "can_produce_grounded_answer": 0.94,
    "robust_answer_requires_multiple_distinct_subconclusions": 0.04,
    "subconclusions_can_be_researched_separately": 0.06,
    "subconclusions_would_be_useful_as_reusable_knowledge": 0.11,
}
STATUTE_STRUCTURE_NOUL = {
    "bounded_for_evidence_retrieval": 0.99,
    "can_produce_grounded_answer": 0.98,
    "robust_answer_requires_multiple_distinct_subconclusions": 0.02,
    "subconclusions_can_be_researched_separately": 0.03,
    "subconclusions_would_be_useful_as_reusable_knowledge": 0.05,
}
MULTI_STRUCTURE_NOUL = {
    "bounded_for_evidence_retrieval": 0.12,
    "can_produce_grounded_answer": 0.09,
    "robust_answer_requires_multiple_distinct_subconclusions": 0.95,
    "subconclusions_can_be_researched_separately": 0.91,
    "subconclusions_would_be_useful_as_reusable_knowledge": 0.87,
}
MECHANISM_STRUCTURE_NOUL = {
    "bounded_for_evidence_retrieval": 0.91,
    "can_produce_grounded_answer": 0.86,
    "robust_answer_requires_multiple_distinct_subconclusions": 0.92,
    "subconclusions_can_be_researched_separately": 0.90,
    "subconclusions_would_be_useful_as_reusable_knowledge": 0.84,
}
MID_BAND_NOUL = {
    "atomic_enough_for_evidence_retrieval": 0.55,
    "contains_multiple_independent_information_needs": 0.40,
    "requires_multiple_independently_grounded_conclusions": 0.45,
    "can_be_answered_as_one_grounded_conclusion_or_mapping": 0.50,
    "subconclusions_may_have_independent_evidence_or_outcomes": 0.48,
}
# Logged in full for "Vilka rättsfall från Högsta domstolen behandlar 36 § avtalslagen?"
HD_CASES_NOUL = {
    "atomic_enough_for_evidence_retrieval": 0.9846,
    "contains_multiple_independent_information_needs": 0.0429,
    "requires_multiple_independently_grounded_conclusions": 0.3661,
    "can_be_answered_as_one_grounded_conclusion_or_mapping": 0.8706,
    "subconclusions_may_have_independent_evidence_or_outcomes": 0.4822,
}
# Logged atomic_enough, multiple_needs, requires_multiple, and one_mapping.
# subconclusions was absent from the excerpt and stays below the composite band.
RUNAWAY_UNCERTAIN_NOUL = {
    "atomic_enough_for_evidence_retrieval": 0.9784,
    "contains_multiple_independent_information_needs": 0.0219,
    "requires_multiple_independently_grounded_conclusions": 0.0081,
    "can_be_answered_as_one_grounded_conclusion_or_mapping": 0.7794,
    "subconclusions_may_have_independent_evidence_or_outcomes": 0.41,
}
# Logged atomic_enough 0.968, multiple_needs 0.025, one_mapping 0.753.
# The other two signals were absent from the excerpt and stay in the mid band.
DEFINITION_NOUL = {
    "atomic_enough_for_evidence_retrieval": 0.968,
    "contains_multiple_independent_information_needs": 0.025,
    "requires_multiple_independently_grounded_conclusions": 0.42,
    "can_be_answered_as_one_grounded_conclusion_or_mapping": 0.753,
    "subconclusions_may_have_independent_evidence_or_outcomes": 0.38,
}
# Logged multiple_needs 0.040. The other signals were absent from the excerpt.
OSKALIGT_NOUL = {
    "atomic_enough_for_evidence_retrieval": 0.97,
    "contains_multiple_independent_information_needs": 0.040,
    "requires_multiple_independently_grounded_conclusions": 0.62,
    "can_be_answered_as_one_grounded_conclusion_or_mapping": 0.71,
    "subconclusions_may_have_independent_evidence_or_outcomes": 0.44,
}
# Clear atomic band for the statute-text question. The run did not log this NOUL.
STATUTE_TEXT_NOUL = _conclusion_noul(one_conclusion=True)


def _validation_noul(*, accepted: bool) -> dict[str, float]:
    if accepted:
        return {
            "independent": 0.95,
            "narrower": 0.93,
            "semantic_progress": 0.94,
            "paraphrase_risk": 0.04,
            "jointly_sufficient_or_useful": 0.92,
        }
    return {
        "independent": 0.12,
        "narrower": 0.2,
        "semantic_progress": 0.08,
        "paraphrase_risk": 0.97,
        "jointly_sufficient_or_useful": 0.15,
    }


def _distinct_child_noul() -> dict[str, float]:
    return {
        "same_knowledge_need_as_parent": 0.04,
        "same_knowledge_need_as_sibling": 0.05,
        "same_knowledge_need_as_ancestor": 0.03,
        "candidate_adds_distinct_subconclusion": 0.93,
        "candidate_is_narrower_but_substantively_distinct": 0.9,
    }


def _same_need_noul(*, key: str) -> dict[str, float]:
    noul = _distinct_child_noul()
    noul[key] = 0.96
    noul["candidate_adds_distinct_subconclusion"] = 0.08
    noul["candidate_is_narrower_but_substantively_distinct"] = 0.12
    return noul


class AvtalslagenController(Controller):
    async def assess_structure(self, *, question: str) -> StructureDecision:
        if question == BROAD:
            return _decision(researchable=True, decomposable=True, noul=dict(BROAD_STRUCTURE_NOUL))
        return _decision(researchable=True, decomposable=False, noul=dict(MAPPING_STRUCTURE_NOUL))


class AvtalslagenGenerator(Generator):
    def __init__(self) -> None:
        super().__init__()
        self.leaf_calls = 0

    async def decompose(self, *, question: str):
        self.decomposition_calls += 1
        if question == BROAD:
            return [GeneratedQuestion(item) for item in LEAVES]
        return []

    async def synthesize_leaf(self, *, question: str, evidence):
        self.leaf_calls += 1
        return GeneratedAnswer(text=f"svar: {question}", status="answered")

    async def synthesize_parent(self, **_kwargs):
        return GeneratedAnswer(
            text="36 § tillämpas genom rekvisit, omständigheter och rättsföljd.", status="answered"
        )


def test_researchability_and_decomposability_are_separate_decisions():
    researchable, research_reason, _ = classify_researchability(BROAD_STRUCTURE_NOUL, threshold=0.8)
    decomposable, decompose_reason, _ = classify_decomposability(
        BROAD_STRUCTURE_NOUL, threshold=0.8
    )
    assert researchable == "researchable"
    assert research_reason == "bounded_evidence_retrieval"
    assert decomposable == "decomposable"
    assert decompose_reason == "multiple_distinct_researchable_subconclusions"
    assert structure_action(researchable, decomposable) == "decompose"
    mapping_r, _, _ = classify_researchability(MAPPING_STRUCTURE_NOUL, threshold=0.8)
    mapping_d, mapping_reason, _ = classify_decomposability(MAPPING_STRUCTURE_NOUL, threshold=0.8)
    assert mapping_r == "researchable"
    assert mapping_d == "not_decomposable"
    assert mapping_reason == "single_conclusion_or_mapping"
    assert structure_action(mapping_r, mapping_d) == "retrieve"
    reusable_mapping = dict(MAPPING_STRUCTURE_NOUL)
    reusable_mapping["subconclusions_can_be_researched_separately"] = 0.95
    reusable_mapping["subconclusions_would_be_useful_as_reusable_knowledge"] = 0.95
    still_mapping, still_reason, _ = classify_decomposability(reusable_mapping, threshold=0.8)
    assert still_mapping == "not_decomposable"
    assert still_reason == "single_conclusion_or_mapping"
    text = " ".join(
        str(value)
        for question in DECOMPOSABILITY_QUESTIONS.values()
        for value in (question["instructions"], *question["criteria"].values())
    ).lower()
    assert "separate does not mean unrelated" in text
    assert "same subject" in text
    assert "one conclusion" in text
    assert "question length does not decide" in text
    assert "positive and negative" in text
    assert "paraphrase" in text
    assert "independent knowledge" not in text
    combined = " ".join(
        str(value)
        for question in (*RESEARCHABILITY_QUESTIONS.values(), *DECOMPOSABILITY_QUESTIONS.values())
        for value in (question["instructions"], *question["criteria"].values())
    ).lower()
    for domain_term in (
        "statute",
        "case law",
        "preparatory",
        "doctrinal",
        "legal consequences",
        "36 §",
    ):
        assert domain_term not in combined
    question_keys = set(RESEARCHABILITY_QUESTIONS) | set(DECOMPOSABILITY_QUESTIONS)
    assert "can_be_supported_by_bounded_evidence" not in question_keys


OVER_DECOMPOSED = (
    "Vilka rättsfall från Högsta domstolen behandlar skälighetsbedömningen enligt 36 § avtalslagen i konsumentförhållanden?",
    "Vilket syfte anges för 36 § avtalslagen i dess förarbeten?",
)
PLURAL_ATOMIC = (
    "Vilka studier har undersökt sambandet mellan X och Y?",
    "Vilka faktorer påverkar X?",
)
TWO_PART = "Vilka faktorer påverkar X och hur skiljer sig effekten mellan population A och B?"
MAPPING_QUESTION = "Vilka studier har undersökt sambandet mellan X och Y?"
INDEPENDENT_QUESTION = (
    "Hur påverkar X utfallet Y, vilka risker medför X och "
    "hur skiljer sig effekten mellan population A och B?"
)
SINGLE_FACT = "Vad är definitionen av X enligt källa Y?"
INDEPENDENT_CHILDREN = (
    "Hur påverkar X utfallet Y?",
    "Vilka risker medför X?",
    "Hur skiljer sig effekten av X mellan population A och B?",
)


def test_decomposition_prompt_asks_for_the_smallest_sufficient_split():
    field = next(item for item in PROMPT_FIELDS if item["key"] == "research.decomposition.system")
    for prompt in (field["defaults"]["sv"], field["defaults"]["en"]):
        lowered = prompt.lower()
        assert "minsta" in lowered or "smallest" in lowered
        assert "självständigt" in lowered or "independently" in lowered
        assert "källor" in lowered or "source" in lowered
        assert "kartläggning" in lowered or "mapping" in lowered
        assert "få starka" in lowered or "few strong" in lowered
        assert "ensamt barn" in lowered or "single child" in lowered
        assert "positiva" in lowered or "positive" in lowered


class KnowledgeGoalController(Controller):
    async def assess_structure(self, *, question: str) -> StructureDecision:
        composite = question in {TWO_PART, INDEPENDENT_QUESTION, BROAD}
        noul = dict(INDEPENDENT_CONCLUSIONS_NOUL if composite else MAPPING_NOUL)
        return _decision(researchable=not composite, decomposable=composite, noul=noul)


class KnowledgeGoalGenerator(Generator):
    async def decompose(self, *, question: str):
        if question == TWO_PART:
            return [GeneratedQuestion(item) for item in PLURAL_ATOMIC]
        if question == INDEPENDENT_QUESTION:
            return [GeneratedQuestion(item) for item in INDEPENDENT_CHILDREN]
        if question == BROAD:
            return [GeneratedQuestion(item) for item in LEAVES]
        return []


@pytest.mark.asyncio
async def test_plural_questions_are_leaves_and_two_goals_are_split(db):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=KnowledgeGoalController(),
        generator=KnowledgeGoalGenerator(),
        limits=QuestionTreeLimits(max_depth=3, max_children=4, max_questions=8),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question=TWO_PART)
    assert {need.question for need in plan.needs} == set(PLURAL_ATOMIC)
    nodes = await list_question_nodes(session, attempt.id)
    parent = next(node for node in nodes if node.question == TWO_PART)
    assert parent.researchability == "not_researchable"
    assert parent.decomposability == "decomposable"
    assert parent.atomicity_noul == INDEPENDENT_CONCLUSIONS_NOUL
    assert parent.decomposition_result == "accepted"
    assert parent.execution_override == ""
    leaves = [node for node in nodes if node.question in PLURAL_ATOMIC]
    assert {node.researchability for node in leaves} == {"researchable"}
    assert {node.decomposability for node in leaves} == {"not_decomposable"}
    assert all(node.atomicity_noul == MAPPING_NOUL for node in leaves)


@pytest.mark.parametrize("question", OVER_DECOMPOSED)
@pytest.mark.asyncio
async def test_over_decomposed_mapping_question_is_one_leaf(db, question):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=KnowledgeGoalController(),
        generator=KnowledgeGoalGenerator(),
        limits=QuestionTreeLimits(max_depth=3, max_children=4, max_questions=8),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question=question)
    assert [need.question for need in plan.needs] == [question]
    node = (await list_question_nodes(session, attempt.id))[0]
    assert node.researchability == "researchable"
    assert node.decomposability == "not_decomposable"
    assert node.atomicity_noul == MAPPING_NOUL
    assert node.phase == "ready"


@pytest.mark.parametrize("question", (MAPPING_QUESTION, SINGLE_FACT))
@pytest.mark.asyncio
async def test_mapping_and_single_fact_questions_stay_atomic(db, question):
    session, attempt = db
    generator = KnowledgeGoalGenerator()
    tree = RecursiveQuestionTree(
        controller=KnowledgeGoalController(),
        generator=generator,
        limits=QuestionTreeLimits(max_depth=3, max_children=4, max_questions=8),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question=question)
    assert [need.question for need in plan.needs] == [question]
    assert generator.decomposition_calls == 0
    node = (await list_question_nodes(session, attempt.id))[0]
    assert node.researchability == "researchable"
    assert node.decomposability == "not_decomposable"
    assert node.atomicity_noul == MAPPING_NOUL
    event = (
        await session.execute(
            select(ResearchProgressEvent).where(
                ResearchProgressEvent.attempt_id == attempt.id,
                ResearchProgressEvent.event_type == "question_atomicity_completed",
            )
        )
    ).scalar_one()
    assert event.payload["question_id"] == node.id
    assert event.payload["parent_question_id"] is None
    assert event.payload["depth"] == 0
    assert event.payload["researchable"] is True
    assert event.payload["decomposable"] is False
    assert event.payload["action"] == "retrieve"
    assert event.payload["researchability"]["decision"] == "researchable"
    assert event.payload["decomposability"]["decision"] == "not_decomposable"
    assert event.payload["thresholds"] == {"structure": 0.8}
    assert event.payload["requires_multiple_independently_grounded_conclusions"] == 0.05
    assert event.payload["can_be_answered_as_one_grounded_conclusion_or_mapping"] == 0.97
    assert event.payload["subconclusions_may_have_independent_evidence_or_outcomes"] == 0.06


@pytest.mark.asyncio
async def test_independent_conclusions_are_split_into_a_small_set(db):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=KnowledgeGoalController(),
        generator=KnowledgeGoalGenerator(),
        limits=QuestionTreeLimits(max_depth=3, max_children=4, max_questions=8),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(
        session, attempt_id=attempt.id, root_question=INDEPENDENT_QUESTION
    )
    assert {need.question for need in plan.needs} == set(INDEPENDENT_CHILDREN)
    assert INDEPENDENT_QUESTION not in {need.question for need in plan.needs}
    nodes = await list_question_nodes(session, attempt.id)
    root = next(node for node in nodes if node.parent_question_id is None)
    assert root.researchability == "not_researchable"
    assert root.decomposability == "decomposable"
    assert root.atomicity_noul["requires_multiple_independently_grounded_conclusions"] == 0.96
    assert root.depth == 0
    assert all(node.depth < 3 for node in nodes)


@pytest.mark.asyncio
async def test_max_depth_composite_is_logged_and_not_retrieved(db):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=Controller(),
        generator=Generator(),
        limits=QuestionTreeLimits(max_depth=0, max_children=4, max_questions=8),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question="root")
    assert plan.needs == []
    node = (await list_question_nodes(session, attempt.id))[0]
    assert node.phase == "unresolved"
    assert node.completeness is None
    assert node.researchability == "not_researchable"
    assert node.decomposability == "decomposable"
    event = (
        await session.execute(
            select(ResearchProgressEvent).where(
                ResearchProgressEvent.attempt_id == attempt.id,
                ResearchProgressEvent.event_type == "question_tree_max_depth_reached",
            )
        )
    ).scalar_one()
    assert event.payload["question_id"] == node.id
    assert event.payload["parent_question_id"] is None
    assert event.payload["depth"] == 0
    assert event.payload["question"] == "root"
    assert event.payload["reason"] == "max_depth"
    assert event.payload["fallback"] == "unresolved"
    assert event.payload["researchability"] == "not_researchable"
    assert event.payload["decomposability"] == "decomposable"


class OpenGapController(Controller):
    async def assess_synthesis_readiness(
        self, *, question: str, child_answers: Sequence[AnswerInput]
    ):
        return ReadinessDecision(
            sufficient=False,
            material_gap=True,
            additional_research_likely_to_change_answer=True,
            noul={"sufficient_to_answer_parent": 0.2, "material_gap_remains": 0.9},
        )


async def _open_parent(session, attempt):
    evidence_set = await create_evidence_set(
        session,
        run_id=attempt.run_id,
        created_from_attempt_id=attempt.id,
    )
    root = await get_or_create_root(session, attempt_id=attempt.id, question="parent")
    root.atomicity = "composite"
    root.phase = "decomposed"
    answered = []
    for label in ("Q1", "Q2"):
        child = ResearchQuestionNode(
            id=label,
            attempt_id=attempt.id,
            parent_question_id=root.id,
            question=label,
            depth=1,
            created_from="decomposition",
            phase="completed",
            atomicity="atomic",
        )
        session.add(child)
        await session.flush()
        await append_answer_version(
            session, node=child, answer_text=f"svar {label}", status="answered"
        )
        answered.append(child)
    pending = ResearchQuestionNode(
        id="Q3",
        attempt_id=attempt.id,
        parent_question_id=root.id,
        question="Q3",
        depth=1,
        created_from="decomposition",
        phase="created",
        atomicity="composite",
    )
    session.add(pending)
    await session.commit()
    return evidence_set, root, pending


@pytest.mark.asyncio
async def test_sufficient_parent_stops_incomplete_child_without_failing(db):
    session, attempt = db
    evidence_set, root, pending = await _open_parent(session, attempt)
    tree = RecursiveQuestionTree(
        controller=Controller(),
        generator=Generator(),
        limits=QuestionTreeLimits(max_depth=10, max_children=4, max_questions=16),
        source_types=["web"],
    )
    plan = await tree.synthesize_wave(
        session, attempt_id=attempt.id, evidence_set_id=evidence_set.id
    )
    await session.refresh(root)
    await session.refresh(pending)
    assert root.phase == "completed"
    assert root.current_answer_id is not None
    assert pending.phase == "not_required"
    assert pending.phase != "failed"
    assert plan.needs == []
    answer = await session.get(ResearchQuestionAnswer, root.current_answer_id)
    answered = [
        node
        for node in await list_question_nodes(session, attempt.id)
        if node.question in {"Q1", "Q2"}
    ]
    links = list(
        (
            await session.execute(
                select(ResearchAnswerChildLink).where(
                    ResearchAnswerChildLink.answer_id == answer.id
                )
            )
        ).scalars()
    )
    assert {link.child_answer_id for link in links} == {node.current_answer_id for node in answered}


@pytest.mark.asyncio
async def test_material_gap_keeps_incomplete_child_open(db):
    session, attempt = db
    evidence_set, root, pending = await _open_parent(session, attempt)
    tree = RecursiveQuestionTree(
        controller=OpenGapController(),
        generator=Generator(),
        limits=QuestionTreeLimits(max_depth=10, max_children=4, max_questions=16),
        source_types=["web"],
    )
    await tree.synthesize_wave(session, attempt_id=attempt.id, evidence_set_id=evidence_set.id)
    await session.refresh(root)
    await session.refresh(pending)
    assert root.phase != "completed"
    assert root.current_answer_id is None
    assert pending.phase == "created"
    assert pending.phase != "failed"


class DepthGenerator(Generator):
    async def decompose(self, *, question: str):
        self.decomposition_calls += 1
        if question == "broad":
            return [GeneratedQuestion("atomic leaf"), GeneratedQuestion("narrower-1")]
        level = int(question.rsplit("-", 1)[-1])
        if level >= 3:
            return [GeneratedQuestion("atomic deep"), GeneratedQuestion("atomic side")]
        return [
            GeneratedQuestion(f"atomic side-{level}"),
            GeneratedQuestion(f"narrower-{level + 1}"),
        ]


class DepthGuardController(Controller):
    async def validate_decomposition(
        self, *, question: str, children: Sequence[str]
    ) -> DecompositionDecision:
        return DecompositionDecision(
            accepted=True,
            noul=_validation_noul(accepted=True),
            threshold=0.8,
        )


class DepthGuardGenerator(Generator):
    def __init__(self) -> None:
        super().__init__()
        self.step = 1

    async def decompose(self, *, question: str):
        self.decomposition_calls += 1
        if question == "root":
            return [GeneratedQuestion("atomic sibling"), GeneratedQuestion("keep-going-1")]
        self.step += 1
        return [GeneratedQuestion(f"keep-going-{self.step}")]


class BoomGenerator(Generator):
    async def decompose(self, *, question: str):
        raise RuntimeError("generator broke")


@pytest.mark.asyncio
async def test_research_continues_past_depth_three(db):
    session, attempt = db
    evidence_set = await create_evidence_set(
        session, run_id=attempt.run_id, created_from_attempt_id=attempt.id
    )
    tree = RecursiveQuestionTree(
        controller=Controller(),
        generator=DepthGenerator(),
        limits=QuestionTreeLimits(max_depth=10, max_children=2, max_questions=16),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question="broad")
    assert "atomic deep" in {need.question for need in plan.needs}
    nodes = await list_question_nodes(session, attempt.id)
    leaf = next(node for node in nodes if node.question == "atomic deep")
    assert leaf.depth > 3
    composites = [node for node in nodes if node.decomposability == "decomposable"]
    children_of: dict[str, list[ResearchQuestionNode]] = {}
    for node in nodes:
        if node.parent_question_id is not None:
            children_of.setdefault(node.parent_question_id, []).append(node)
    assert composites
    assert all(len(children_of.get(node.id, [])) >= 2 for node in composites)
    assert all(node.phase != "unresolved" for node in nodes)
    await tree.synthesize_wave(session, attempt_id=attempt.id, evidence_set_id=evidence_set.id)
    root = next(node for node in await list_question_nodes(session, attempt.id) if node.depth == 0)
    assert root.current_answer_id is not None
    assert root.phase == "completed"


@pytest.mark.asyncio
async def test_single_narrowing_is_retrieved_instead_of_walking_to_max_depth(db):
    """One accepted child is not a chain. The parent is researched as a whole."""
    session, attempt = db
    evidence_set = await create_evidence_set(
        session, run_id=attempt.run_id, created_from_attempt_id=attempt.id
    )
    tree = RecursiveQuestionTree(
        controller=DepthGuardController(),
        generator=DepthGuardGenerator(),
        limits=QuestionTreeLimits(max_depth=10, max_children=2, max_questions=24),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question="root")
    assert {need.question for need in plan.needs} == {"atomic sibling", "keep-going-1"}
    nodes = await list_question_nodes(session, attempt.id)
    assert max(node.depth for node in nodes) == 1
    narrowing = next(node for node in nodes if node.question == "keep-going-1")
    assert narrowing.researchability == "not_researchable"
    assert narrowing.decomposability == "decomposable"
    assert narrowing.execution_override == "best_effort_retrieval"
    assert narrowing.phase == "ready"
    await tree.synthesize_wave(session, attempt_id=attempt.id, evidence_set_id=evidence_set.id)
    nodes = await list_question_nodes(session, attempt.id)
    root = next(node for node in nodes if node.parent_question_id is None)
    narrowing = next(node for node in nodes if node.id == narrowing.id)
    assert root.phase == "completed"
    assert root.current_answer_id is not None
    assert narrowing.phase == "completed"
    assert narrowing.current_answer_id is not None
    assert narrowing.researchability == "not_researchable"


@pytest.mark.asyncio
async def test_generator_exception_stays_failed(db):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=Controller(),
        generator=BoomGenerator(),
        limits=QuestionTreeLimits(max_depth=10, max_children=2, max_questions=8),
        source_types=["web"],
    )
    with pytest.raises(RuntimeError, match="generator broke"):
        await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question="root")
    await fail_transient_question_nodes(session, attempt_id=attempt.id)
    await session.commit()
    root = (await list_question_nodes(session, attempt.id))[0]
    assert root.phase == "failed"
    assert root.phase != "unresolved"
    assert root.phase != "not_required"


class _StructureJev:
    def __init__(self, noul: dict[str, float]) -> None:
        self.noul = noul

    async def ask(self, *, state, questions, model, timeout_seconds):
        return JevSystemOneResult(
            answers={key: {"noul": self.noul[key]} for key in questions},
            model="openjev-0.1",
            latency_ms=12,
            input_chars=20,
            usage=JevUsage(),
            raw={},
        )


@pytest.mark.asyncio
async def test_uncertain_structure_does_not_decompose(monkeypatch):
    monkeypatch.setattr(settings, "research_jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "test-key")
    monkeypatch.setattr(settings, "research_question_atomicity_threshold", 0.8)
    noul = {
        "bounded_for_evidence_retrieval": 0.55,
        "can_produce_grounded_answer": 0.50,
        "robust_answer_requires_multiple_distinct_subconclusions": 0.48,
        "subconclusions_can_be_researched_separately": 0.46,
        "subconclusions_would_be_useful_as_reusable_knowledge": 0.44,
    }
    decision = await JevQuestionTreeController(_StructureJev(noul)).assess_structure(
        question="Vad är huvudregeln i 36 § avtalslagen för jämkning av avtalsvillkor?"
    )
    assert decision.researchability == "uncertain"
    assert decision.decomposability == "uncertain"
    assert structure_action(decision.researchability, decision.decomposability) == "unresolved"


class UncertainLeafController(Controller):
    async def assess_structure(self, *, question: str) -> StructureDecision:
        if question == "huvudregeln":
            return StructureDecision(
                researchability="uncertain",
                decomposability="uncertain",
                researchability_reason="unresolved_researchability",
                decomposability_reason="unresolved_decomposability",
                noul=dict(MID_BAND_NOUL),
                threshold=0.8,
            )
        return _decision(researchable=True, decomposable=False, noul=dict(MAPPING_NOUL))


class UncertainLeafGenerator(Generator):
    async def decompose(self, *, question: str):
        return [GeneratedQuestion("atomic regel")]


@pytest.mark.asyncio
async def test_uncertain_question_is_not_decomposed(db):
    session, attempt = db
    generator = UncertainLeafGenerator()
    tree = RecursiveQuestionTree(
        controller=UncertainLeafController(),
        generator=generator,
        limits=QuestionTreeLimits(max_depth=3, max_children=4, max_questions=8),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question="huvudregeln")
    assert plan.needs == []
    assert generator.decomposition_calls == 0
    nodes = await list_question_nodes(session, attempt.id)
    root = next(node for node in nodes if node.question == "huvudregeln")
    assert root.researchability == "uncertain"
    assert root.decomposability == "uncertain"
    assert root.phase == "unresolved"
    assert root.phase != "failed"
    assert root.atomicity_noul["atomic_enough_for_evidence_retrieval"] == 0.55
    assert all(node.phase != "assessing_atomicity" for node in nodes)


def test_mirrored_question_event_key_fits_the_column():
    node_id = "81ab6db731f949adabc60ea0d09cf7da"
    answer_id = "65506e8b2e8c4ded8dd918725912b94f"
    key = tree_event_idempotency_key(node_id, "answer_synthesized", f"leaf:{answer_id}")
    mirrored = f"child:{'3448cd1198c6467b94f616846992b50b'}:{key}"
    assert len(mirrored) <= PROGRESS_IDEMPOTENCY_KEY_MAX
    huge = tree_event_idempotency_key(node_id, "answer_synthesis_started", "parent:" + ("a" * 400))
    assert len(f"child:{'b' * 32}:{huge}") <= PROGRESS_IDEMPOTENCY_KEY_MAX


@pytest.mark.asyncio
async def test_section_36_question_decomposes_and_synthesizes_bottom_up(db):
    session, attempt = db
    evidence_set = await create_evidence_set(
        session,
        run_id=attempt.run_id,
        created_from_attempt_id=attempt.id,
    )
    generator = AvtalslagenGenerator()
    tree = RecursiveQuestionTree(
        controller=AvtalslagenController(),
        generator=generator,
        limits=QuestionTreeLimits(max_depth=3, max_children=4, max_questions=24),
        source_types=["swedish_law", "swedish_case_law", "swedish_preparatory_works"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question=BROAD)
    assert len(plan.needs) >= 2
    assert BROAD not in {need.question for need in plan.needs}
    assert generator.decomposition_calls == 1

    await tree.synthesize_wave(
        session,
        attempt_id=attempt.id,
        evidence_set_id=evidence_set.id,
    )
    nodes = await list_question_nodes(session, attempt.id)
    root = next(node for node in nodes if node.parent_question_id is None)
    leaves = [node for node in nodes if node.parent_question_id == root.id]
    assert root.researchability == "researchable"
    assert root.decomposability == "decomposable"
    assert root.research_need_id is None
    assert len(leaves) >= 2
    assert all(node.question != BROAD for node in leaves)
    assert all(
        node.depth < 3
        and node.researchability == "researchable"
        and node.decomposability == "not_decomposable"
        for node in leaves
    )
    assert all(node.current_answer_id for node in leaves)
    assert root.current_answer_id is not None
    assert root.phase == "completed"
    assert all(node.phase not in TRANSIENT_QUESTION_PHASES for node in nodes)
    depth_events = list(
        (
            await session.execute(
                select(ResearchProgressEvent).where(
                    ResearchProgressEvent.attempt_id == attempt.id,
                    ResearchProgressEvent.event_type == "question_tree_max_depth_reached",
                )
            )
        ).scalars()
    )
    assert depth_events == []
    executions = list(
        (
            await session.execute(
                select(ResearchNeedExecution).where(ResearchNeedExecution.attempt_id == attempt.id)
            )
        ).scalars()
    )
    assert executions == []
    answer = await session.get(ResearchQuestionAnswer, root.current_answer_id)
    assert answer is not None
    assert "rekvisit" in answer.answer_text
    links = list(
        (
            await session.execute(
                select(ResearchAnswerChildLink).where(
                    ResearchAnswerChildLink.answer_id == answer.id
                )
            )
        ).scalars()
    )
    assert {link.child_answer_id for link in links} == {node.current_answer_id for node in leaves}


@pytest.mark.asyncio
async def test_synthesizing_without_answer_retries_and_terminal_attempt_leaves_failed(db):
    session, attempt = db
    evidence_set = await create_evidence_set(
        session,
        run_id=attempt.run_id,
        created_from_attempt_id=attempt.id,
    )
    root = await get_or_create_root(session, attempt_id=attempt.id, question="atomic leaf")
    root.atomicity = "atomic"
    root.phase = "synthesizing"
    root.research_need_id = "question-leaf"
    await session.commit()
    generator = AvtalslagenGenerator()
    tree = RecursiveQuestionTree(
        controller=AtomicController(),
        generator=generator,
        limits=QuestionTreeLimits(max_depth=3, max_children=4, max_questions=24),
        source_types=["web"],
    )
    await tree.synthesize_wave(
        session,
        attempt_id=attempt.id,
        evidence_set_id=evidence_set.id,
    )
    await session.refresh(root)
    assert generator.leaf_calls == 1
    assert root.current_answer_id is not None
    assert root.phase == "completed"

    stuck = await get_or_create_root(session, attempt_id=attempt.id, question="atomic leaf")
    stuck.phase = "synthesizing"
    await session.commit()
    await fail_transient_question_nodes(session, attempt_id=attempt.id)
    await session.commit()
    await session.refresh(stuck)
    assert stuck.phase == "failed"
    assert stuck.current_answer_id is not None


HD_CASES = "Vilka rättsfall från Högsta domstolen behandlar 36 § avtalslagen?"
DEFINITION = "Vad innebär begreppet avtalets karaktär i svensk avtalsrätt?"
MULTI_DIMENSION = "Hur påverkar X effekt, risk och kostnad i populationerna A och B?"
STATUTE_TEXT = "Vad är ordalydelsen av 36 § avtalslagen?"
MECHANISM = "How does mechanism X affect system Y?"
STUDIES = "Which studies have investigated the relationship between X and Y?"
CONCEPT = "What does concept X mean?"
EFFECTIVENESS = "How does X affect effectiveness, risk and cost?"
_DISTINCT = "robust_answer_requires_multiple_distinct_subconclusions"
_SEPARATE = "subconclusions_can_be_researched_separately"


@pytest.mark.parametrize(
    ("question", "noul", "researchable", "decomposable"),
    [
        (BROAD, BROAD_STRUCTURE_NOUL, "researchable", "decomposable"),
        (HD_CASES, MAPPING_STRUCTURE_NOUL, "researchable", "not_decomposable"),
        (DEFINITION, DEFINITION_STRUCTURE_NOUL, "researchable", "not_decomposable"),
        (STATUTE_TEXT, STATUTE_STRUCTURE_NOUL, "researchable", "not_decomposable"),
        (MECHANISM, MECHANISM_STRUCTURE_NOUL, "researchable", "decomposable"),
        (STUDIES, MAPPING_STRUCTURE_NOUL, "researchable", "not_decomposable"),
        (CONCEPT, DEFINITION_STRUCTURE_NOUL, "researchable", "not_decomposable"),
        (EFFECTIVENESS, MECHANISM_STRUCTURE_NOUL, "researchable", "decomposable"),
        (MULTI_DIMENSION, MULTI_STRUCTURE_NOUL, "not_researchable", "decomposable"),
    ],
)
def test_structure_regressions(question, noul, researchable, decomposable):
    threshold = 0.8
    got_research, _, _ = classify_researchability(noul, threshold=threshold)
    got_decompose, _, _ = classify_decomposability(noul, threshold=threshold)
    assert got_research == researchable, question
    assert got_decompose == decomposable, question
    if decomposable == "decomposable":
        assert noul[_DISTINCT] >= threshold, question
        assert noul[_SEPARATE] >= threshold, question
    else:
        assert noul[_DISTINCT] <= 1 - threshold, question


def test_set_validation_accepts_progress_without_secondary_vetoes():
    accepted, reason = classify_decomposition(_validation_noul(accepted=True), threshold=0.8)
    assert accepted is True
    assert reason == ""
    rejected, reason = classify_decomposition(_validation_noul(accepted=False), threshold=0.8)
    assert rejected is False
    assert reason == "insufficient_semantic_progress"
    mid = _validation_noul(accepted=True)
    mid["semantic_progress"] = 0.5
    rejected, reason = classify_decomposition(mid, threshold=0.8)
    assert rejected is False
    # The logged run: two valid children, clear progress, secondary signals
    # just under the general 0.8 band.
    regression = {
        "independent": 0.718,
        "narrower": 0.780,
        "semantic_progress": 0.862,
        "paraphrase_risk": 0.052,
        "jointly_sufficient_or_useful": 0.980,
    }
    accepted, reason = classify_decomposition(regression, threshold=0.8)
    assert accepted is True
    assert reason == ""
    supporting_only = dict(regression)
    supporting_only["independent"] = 0.1
    supporting_only["narrower"] = 0.1
    accepted, _reason = classify_decomposition(supporting_only, threshold=0.8)
    assert accepted is True
    paraphrase = dict(regression)
    paraphrase["paraphrase_risk"] = 0.9
    rejected, reason = classify_decomposition(paraphrase, threshold=0.8)
    assert rejected is False
    assert reason == "insufficient_semantic_progress"
    useless = dict(regression)
    useless["jointly_sufficient_or_useful"] = 0.5
    rejected, _reason = classify_decomposition(useless, threshold=0.8)
    assert rejected is False
    text = " ".join(
        str(value)
        for question in DECOMPOSITION_VALIDATION_QUESTIONS.values()
        for value in (question["instructions"], *question["criteria"].values())
    ).lower()
    assert "single child" in text
    assert "restates the parent" in text
    for domain_term in ("statute", "case law", "36 §"):
        assert domain_term not in text


class _ScoreJev:
    def __init__(self, noul: dict[str, float]) -> None:
        self.noul = noul

    async def ask(self, *, state, questions, model, timeout_seconds):
        return JevSystemOneResult(
            answers={key: {"noul": self.noul[key]} for key in questions},
            model="openjev-0.1",
            latency_ms=9,
            input_chars=20,
            usage=JevUsage(),
            raw={},
        )


@pytest.mark.asyncio
async def test_jev_rejects_a_paraphrase_split(monkeypatch):
    monkeypatch.setattr(settings, "research_jev_enabled", True)
    monkeypatch.setattr(settings, "typesafe_api_key", "test-key")
    monkeypatch.setattr(settings, "research_question_decomposition_threshold", 0.8)
    decision = await JevQuestionTreeController(
        _ScoreJev(_validation_noul(accepted=False))
    ).validate_decomposition(
        question=BROAD,
        children=["Hur tillämpas 36 § avtalslagen i rättspraxis?"],
    )
    assert decision.accepted is False
    assert decision.rejection_reason == "insufficient_semantic_progress"
    assert decision.noul["paraphrase_risk"] == 0.97


class LoggedScoreController(Controller):
    def __init__(
        self,
        noul: dict[str, float],
        *,
        researchable: bool,
        decomposable: bool,
    ) -> None:
        self.noul = noul
        self.researchable = researchable
        self.decomposable = decomposable

    async def assess_structure(self, *, question: str) -> StructureDecision:
        if question in {HD_CASES, DEFINITION, STATUTE_TEXT, BROAD, MULTI_DIMENSION}:
            return _decision(
                researchable=self.researchable,
                decomposable=self.decomposable,
                noul=dict(self.noul),
            )
        return _decision(researchable=True, decomposable=False, noul=dict(MAPPING_STRUCTURE_NOUL))


class ParaphraseGenerator(Generator):
    async def decompose(self, *, question: str):
        self.decomposition_calls += 1
        return [GeneratedQuestion(f"{question} i praxis")]


@pytest.mark.asyncio
async def test_researchable_paraphrase_chain_becomes_one_leaf(db):
    session, attempt = db
    generator = ParaphraseGenerator()
    tree = RecursiveQuestionTree(
        controller=LoggedScoreController(
            MAPPING_STRUCTURE_NOUL,
            researchable=True,
            decomposable=True,
        ),
        generator=generator,
        limits=QuestionTreeLimits(max_depth=10, max_children=4, max_questions=24),
        source_types=["swedish_case_law"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question=HD_CASES)
    assert [need.question for need in plan.needs] == [HD_CASES]
    assert generator.decomposition_calls == 1
    assert len(await list_question_nodes(session, attempt.id)) == 1
    root = (await list_question_nodes(session, attempt.id))[0]
    assert root.researchability == "researchable"
    assert root.decomposability == "decomposable"
    assert root.phase == "ready"
    event = (
        await session.execute(
            select(ResearchProgressEvent).where(
                ResearchProgressEvent.attempt_id == attempt.id,
                ResearchProgressEvent.event_type == "question_decomposed",
            )
        )
    ).scalar_one()
    assert event.payload["parent_question_id"] is None
    assert event.payload["child_count"] == 1
    assert event.payload["decision"] == "rejected"
    assert event.payload["rejection_reason"] == "insufficient_distinct_children"
    assert event.payload["decomposition_decision"] == "insufficient_distinct_children"
    assert event.payload["fallback"] == "best_effort_retrieval"
    assert event.payload["decomposition_result"] == "exhausted"
    assert root.execution_override == "best_effort_retrieval"
    assert root.researchability == "researchable"
    assert event.payload["accepted_count"] == 1
    assert event.payload["rejected_count"] == 0


@pytest.mark.asyncio
async def test_invalid_split_without_researchability_retrieves_the_question(db):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=LoggedScoreController(
            MULTI_STRUCTURE_NOUL,
            researchable=False,
            decomposable=True,
        ),
        generator=ParaphraseGenerator(),
        limits=QuestionTreeLimits(max_depth=10, max_children=4, max_questions=8),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question=BROAD)
    assert [need.question for need in plan.needs] == [BROAD]
    assert plan.needs[0].generated_from == "decomposition_fallback"
    root = (await list_question_nodes(session, attempt.id))[0]
    assert root.researchability == "not_researchable"
    assert root.decomposability == "decomposable"
    assert root.decomposition_result == "exhausted"
    assert root.execution_override == "best_effort_retrieval"
    assert root.phase == "ready"
    assert root.phase != "failed"
    event = (
        await session.execute(
            select(ResearchProgressEvent).where(
                ResearchProgressEvent.attempt_id == attempt.id,
                ResearchProgressEvent.event_type == "question_decomposed",
            )
        )
    ).scalar_one()
    assert event.payload["decision"] == "rejected"
    assert event.payload["fallback"] == "best_effort_retrieval"


class NarrowingController(Controller):
    async def assess_structure(self, *, question: str) -> StructureDecision:
        leaf = question != "parent"
        return _decision(
            researchable=leaf,
            decomposable=not leaf,
            noul=dict(MAPPING_NOUL if leaf else INDEPENDENT_CONCLUSIONS_NOUL),
        )

    async def validate_decomposition(
        self, *, question: str, children: Sequence[str]
    ) -> DecompositionDecision:
        return DecompositionDecision(
            accepted=True,
            noul=_validation_noul(accepted=True),
            threshold=0.8,
        )


class NarrowingGenerator(Generator):
    async def decompose(self, *, question: str):
        self.decomposition_calls += 1
        return [GeneratedQuestion("atomic narrower criterion")]


@pytest.mark.asyncio
async def test_single_valid_child_exhausts_and_retrieves_the_parent(db):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=NarrowingController(),
        generator=NarrowingGenerator(),
        limits=QuestionTreeLimits(max_depth=4, max_children=4, max_questions=8),
        source_types=["web"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question="parent")
    assert [need.question for need in plan.needs] == ["parent"]
    nodes = await list_question_nodes(session, attempt.id)
    assert [node.question for node in nodes] == ["parent"]
    root = nodes[0]
    assert root.researchability == "not_researchable"
    assert root.execution_override == "best_effort_retrieval"
    assert root.execution_override_reason == "insufficient_distinct_children"
    assert root.phase == "ready"
    event = (
        await session.execute(
            select(ResearchProgressEvent).where(
                ResearchProgressEvent.attempt_id == attempt.id,
                ResearchProgressEvent.event_type == "question_decomposed",
            )
        )
    ).scalar_one()
    assert event.payload["child_count"] == 1
    assert event.payload["decision"] == "rejected"
    assert event.payload["decomposition_decision"] == "insufficient_distinct_children"
    assert event.payload["fallback"] == "best_effort_retrieval"


HOW_LATER = "Hur beaktar HD senare inträffade förhållanden vid tillämpningen av 36 §?"
WHICH_LATER = "Vilka senare inträffade förhållanden har HD beaktat vid tillämpningen av 36 §?"
CONTENT_CIRCUMSTANCES = "Vilka omständigheter har HD beaktat avseende avtalets innehåll?"
POSITION_CIRCUMSTANCES = "Vilka omständigheter har HD beaktat avseende parternas ställning?"


@pytest.mark.parametrize(
    ("parent", "candidate", "noul", "has_siblings", "has_ancestors", "accepted", "reason"),
    [
        (
            HOW_LATER,
            WHICH_LATER,
            _same_need_noul(key="same_knowledge_need_as_parent"),
            False,
            False,
            False,
            "redundant_with_parent",
        ),
        (
            HOW_LATER,
            WHICH_LATER,
            _same_need_noul(key="same_knowledge_need_as_sibling"),
            True,
            False,
            False,
            "redundant_with_sibling",
        ),
        (
            HOW_LATER,
            WHICH_LATER,
            _same_need_noul(key="same_knowledge_need_as_ancestor"),
            False,
            True,
            False,
            "redundant_with_ancestor",
        ),
        (
            CONTENT_CIRCUMSTANCES,
            POSITION_CIRCUMSTANCES,
            _distinct_child_noul(),
            True,
            False,
            True,
            "",
        ),
    ],
)
def test_child_redundancy_regressions(
    parent, candidate, noul, has_siblings, has_ancestors, accepted, reason
):
    got, got_reason = classify_child_redundancy(
        noul, threshold=0.8, has_siblings=has_siblings, has_ancestors=has_ancestors
    )
    assert got is accepted, (parent, candidate)
    assert got_reason == reason, (parent, candidate)


def test_parent_containment_does_not_reject_a_proper_subset():
    """Live scores for the parties' relative-strength child under the 36 § root."""
    noul = {
        "same_knowledge_need_as_parent": 0.9105148026447609,
        "same_knowledge_need_as_sibling": 0.001358894333762215,
        "same_knowledge_need_as_ancestor": 0.00043489304716149855,
        "candidate_adds_distinct_subconclusion": 0.9753834034058311,
        "candidate_is_narrower_but_substantively_distinct": 0.9932633333291248,
    }
    accepted, reason = classify_child_redundancy(
        noul, threshold=0.8, has_siblings=False, has_ancestors=False
    )
    assert accepted is True
    assert reason == ""


def test_sibling_same_need_rejects_even_when_the_parent_subset_is_clear():
    noul = _distinct_child_noul()
    noul["same_knowledge_need_as_sibling"] = 0.96
    accepted, reason = classify_child_redundancy(
        noul, threshold=0.8, has_siblings=True, has_ancestors=False
    )
    assert accepted is False
    assert reason == "redundant_with_sibling"


def test_whole_parent_paraphrase_stays_redundant_when_subset_signals_are_low():
    noul = _distinct_child_noul()
    noul["same_knowledge_need_as_parent"] = 0.95
    noul["candidate_adds_distinct_subconclusion"] = 0.08
    noul["candidate_is_narrower_but_substantively_distinct"] = 0.12
    accepted, reason = classify_child_redundancy(
        noul, threshold=0.8, has_siblings=False, has_ancestors=False
    )
    assert accepted is False
    assert reason == "redundant_with_parent"


def test_narrower_wording_without_a_new_conclusion_is_rejected():
    noul = _distinct_child_noul()
    noul["candidate_adds_distinct_subconclusion"] = 0.1
    noul["candidate_is_narrower_but_substantively_distinct"] = 0.1
    accepted, reason = classify_child_redundancy(
        noul, threshold=0.8, has_siblings=False, has_ancestors=False
    )
    assert accepted is False
    assert reason == "not_distinct_knowledge_need"


def test_empty_sibling_and_ancestor_lists_do_not_reject():
    noul = _same_need_noul(key="same_knowledge_need_as_sibling")
    noul["same_knowledge_need_as_ancestor"] = 0.97
    noul["candidate_adds_distinct_subconclusion"] = 0.91
    accepted, reason = classify_child_redundancy(
        noul, threshold=0.8, has_siblings=False, has_ancestors=False
    )
    assert accepted is True
    assert reason == ""


def test_child_redundancy_questions_judge_knowledge_intent():
    text = " ".join(
        str(value)
        for question in CHILD_REDUNDANCY_QUESTIONS.values()
        for value in (question["instructions"], *question["criteria"].values())
    ).lower()
    parent = CHILD_REDUNDANCY_QUESTIONS["same_knowledge_need_as_parent"]
    parent_text = " ".join((parent["instructions"], *parent["criteria"].values())).lower()
    ancestor = CHILD_REDUNDANCY_QUESTIONS["same_knowledge_need_as_ancestor"]
    ancestor_text = " ".join((ancestor["instructions"], *ancestor["criteria"].values())).lower()
    assert "same knowledge need" in text
    assert "proper substantive subset" in parent_text
    assert "entire parent" in parent_text
    assert "paraphrase" in parent_text
    assert "subset of an ancestor" in ancestor_text
    assert "how versus which" in text
    assert "sharing the parent's subject is not the same need" in parent_text
    assert "when something applies" in text
    assert "mapping of many results" in text
    for domain_term in ("statute", "case law", "36 §"):
        assert domain_term not in text


def test_proper_subset_is_accepted_and_whole_parent_paraphrase_is_rejected():
    subset = _distinct_child_noul()
    accepted, reason = classify_child_redundancy(
        subset, threshold=0.8, has_siblings=False, has_ancestors=False
    )
    assert accepted is True
    assert reason == ""
    paraphrase = _same_need_noul(key="same_knowledge_need_as_parent")
    accepted, reason = classify_child_redundancy(
        paraphrase, threshold=0.8, has_siblings=False, has_ancestors=False
    )
    assert accepted is False
    assert reason == "redundant_with_parent"
    subset_of_ancestor = _distinct_child_noul()
    subset_of_ancestor["same_knowledge_need_as_ancestor"] = 0.1
    accepted, reason = classify_child_redundancy(
        subset_of_ancestor, threshold=0.8, has_siblings=False, has_ancestors=True
    )
    assert accepted is True
    assert reason == ""


class AccountingGenerator(Generator):
    async def decompose(self, *, question: str):
        self.decomposition_calls += 1
        if question != "budget-root":
            return []
        return [
            GeneratedQuestion("keep-a"),
            GeneratedQuestion("keep-a"),
            GeneratedQuestion("reject-1"),
            GeneratedQuestion("keep-b"),
            GeneratedQuestion("extra"),
            GeneratedQuestion("also"),
        ]


class AccountingController(Controller):
    async def assess_structure(self, *, question: str) -> StructureDecision:
        return _decision(
            researchable=True,
            decomposable=question == "budget-root",
        )

    async def validate_child_redundancy(
        self,
        *,
        parent: str,
        candidate: str,
        siblings: Sequence[str],
        ancestors: Sequence[str],
    ) -> ChildRedundancyDecision:
        del parent, siblings, ancestors
        if candidate.startswith("reject"):
            return ChildRedundancyDecision(
                accepted=False,
                rejection_reason="redundant_with_parent",
                noul=_same_need_noul(key="same_knowledge_need_as_parent"),
                threshold=0.8,
            )
        return ChildRedundancyDecision(accepted=True, noul=_distinct_child_noul(), threshold=0.8)


@pytest.mark.asyncio
async def test_generated_candidates_sum_to_accepted_rejected_and_pre_filtered(db):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=AccountingController(),
        generator=AccountingGenerator(),
        limits=QuestionTreeLimits(max_depth=2, max_children=3, max_questions=8),
        source_types=["web"],
    )
    await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question="budget-root")
    event = (
        await session.execute(
            select(ResearchProgressEvent).where(
                ResearchProgressEvent.attempt_id == attempt.id,
                ResearchProgressEvent.event_type == "question_decomposed",
            )
        )
    ).scalar_one()
    payload = event.payload
    assert payload["candidate_count"] == 6
    assert payload["accepted_count"] == 3
    assert payload["rejected_count"] == 1
    assert payload["pre_filtered_count"] == 2
    assert payload["pre_filtered_reasons"] == ["duplicate", "child_budget"]
    assert payload["pre_filtered_questions"] == ["keep-a", "also"]
    assert (
        payload["accepted_count"] + payload["rejected_count"] + payload["pre_filtered_count"]
        == payload["candidate_count"]
    )


class SelectiveRedundancyController(Controller):
    async def assess_structure(self, *, question: str) -> StructureDecision:
        split = question in {BROAD, "bridge"}
        return _decision(
            researchable=True,
            decomposable=split,
            noul=dict(BROAD_STRUCTURE_NOUL if split else MAPPING_STRUCTURE_NOUL),
        )

    async def validate_decomposition(
        self, *, question: str, children: Sequence[str]
    ) -> DecompositionDecision:
        return DecompositionDecision(
            accepted=len(children) >= 2,
            noul=_validation_noul(accepted=len(children) >= 2),
            rejection_reason="" if len(children) >= 2 else "insufficient_semantic_progress",
            threshold=0.8,
        )

    async def validate_child_redundancy(
        self,
        *,
        parent: str,
        candidate: str,
        siblings: Sequence[str],
        ancestors: Sequence[str],
    ) -> ChildRedundancyDecision:
        if candidate == WHICH_LATER and HOW_LATER in siblings:
            return ChildRedundancyDecision(
                accepted=False,
                rejection_reason="redundant_with_sibling",
                noul=_same_need_noul(key="same_knowledge_need_as_sibling"),
                threshold=0.8,
            )
        if candidate == "root-need reformulated" and ancestors:
            return ChildRedundancyDecision(
                accepted=False,
                rejection_reason="redundant_with_ancestor",
                noul=_same_need_noul(key="same_knowledge_need_as_ancestor"),
                threshold=0.8,
            )
        if candidate == "only wording":
            return ChildRedundancyDecision(
                accepted=False,
                rejection_reason="redundant_with_parent",
                noul=_same_need_noul(key="same_knowledge_need_as_parent"),
                threshold=0.8,
            )
        return ChildRedundancyDecision(accepted=True, noul=_distinct_child_noul(), threshold=0.8)


class MixedGenerator(Generator):
    async def decompose(self, *, question: str):
        self.decomposition_calls += 1
        if question == "bridge":
            return [GeneratedQuestion("root-need reformulated")]
        return [
            GeneratedQuestion(HOW_LATER),
            GeneratedQuestion(WHICH_LATER),
            GeneratedQuestion(CONTENT_CIRCUMSTANCES),
            GeneratedQuestion(POSITION_CIRCUMSTANCES),
            GeneratedQuestion("bridge"),
        ]


@pytest.mark.asyncio
async def test_redundant_sibling_is_dropped_and_distinct_dimensions_stay(db):
    session, attempt = db
    generator = MixedGenerator()
    tree = RecursiveQuestionTree(
        controller=SelectiveRedundancyController(),
        generator=generator,
        limits=QuestionTreeLimits(max_depth=4, max_children=6, max_questions=16),
        source_types=["swedish_case_law"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question=BROAD)
    questions = {need.question for need in plan.needs}
    assert HOW_LATER in questions
    assert CONTENT_CIRCUMSTANCES in questions
    assert POSITION_CIRCUMSTANCES in questions
    assert WHICH_LATER not in questions
    assert "root-need reformulated" not in questions
    nodes = await list_question_nodes(session, attempt.id)
    assert all(node.question != WHICH_LATER for node in nodes)
    event = list(
        (
            await session.execute(
                select(ResearchProgressEvent).where(
                    ResearchProgressEvent.attempt_id == attempt.id,
                    ResearchProgressEvent.event_type == "question_decomposed",
                )
            )
        ).scalars()
    )
    root_event = next(row for row in event if row.payload.get("depth") == 0)
    assert root_event.payload["decomposition_decision"] == "accepted"
    assert root_event.payload["accepted_count"] == 4
    assert root_event.payload["rejected_count"] == 1
    assert root_event.payload["rejection_questions"] == [WHICH_LATER]
    assert root_event.payload["rejection_reasons"] == ["redundant_with_sibling"]
    bridge_event = next(row for row in event if row.payload.get("depth") == 1)
    assert bridge_event.payload["decomposition_decision"] == "no_valid_children"
    assert bridge_event.payload["fallback"] == "best_effort_retrieval"
    assert bridge_event.payload["rejection_questions"] == ["root-need reformulated"]
    assert bridge_event.payload["rejection_reasons"] == ["redundant_with_ancestor"]


class AllRedundantGenerator(Generator):
    async def decompose(self, *, question: str):
        self.decomposition_calls += 1
        return [
            GeneratedQuestion("only wording"),
            GeneratedQuestion("only wording two"),
        ]


class ParentWordingController(SelectiveRedundancyController):
    async def validate_child_redundancy(
        self,
        *,
        parent: str,
        candidate: str,
        siblings: Sequence[str],
        ancestors: Sequence[str],
    ) -> ChildRedundancyDecision:
        return ChildRedundancyDecision(
            accepted=False,
            rejection_reason="redundant_with_parent",
            noul=_same_need_noul(key="same_knowledge_need_as_parent"),
            threshold=0.8,
        )


@pytest.mark.asyncio
async def test_all_redundant_children_research_the_parent(db):
    session, attempt = db
    generator = AllRedundantGenerator()
    tree = RecursiveQuestionTree(
        controller=ParentWordingController(),
        generator=generator,
        limits=QuestionTreeLimits(max_depth=4, max_children=4, max_questions=8),
        source_types=["swedish_case_law"],
    )
    plan = await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question=BROAD)
    assert [need.question for need in plan.needs] == [BROAD]
    assert generator.decomposition_calls == 1
    assert len(await list_question_nodes(session, attempt.id)) == 1
    event = (
        await session.execute(
            select(ResearchProgressEvent).where(
                ResearchProgressEvent.attempt_id == attempt.id,
                ResearchProgressEvent.event_type == "question_decomposed",
            )
        )
    ).scalar_one()
    assert event.payload["decision"] == "rejected"
    assert event.payload["decomposition_decision"] == "no_valid_children"
    assert event.payload["fallback"] == "best_effort_retrieval"
    assert event.payload["accepted_count"] == 0
    assert event.payload["rejected_count"] == 2
    assert event.payload["pre_filtered_count"] == 0
    assert (
        event.payload["accepted_count"]
        + event.payload["rejected_count"]
        + event.payload["pre_filtered_count"]
        == event.payload["candidate_count"]
    )
    assert event.payload["rejection_reasons"] == [
        "redundant_with_parent",
        "redundant_with_parent",
    ]


ROOT_EXHAUSTED = "Hur ska den breda frågan besvaras?"
CHILD_A = "Vilka rekvisit använder HD när 36 § avtalslagen tillämpas?"
CHILD_B = "Vilken rättsföljd anger HD när 36 § avtalslagen tillämpas?"
PARENT_REDUNDANT_A = "Hur beskriver HD rekvisiten för 36 § avtalslagen?"
PARENT_REDUNDANT_B = "Hur beskriver HD rättsföljden för 36 § avtalslagen?"


class NestedExhaustionController(Controller):
    async def assess_structure(self, *, question: str) -> StructureDecision:
        return _decision(
            researchable=False,
            decomposable=True,
            noul=dict(INDEPENDENT_CONCLUSIONS_NOUL),
        )

    async def validate_child_redundancy(
        self,
        *,
        parent: str,
        candidate: str,
        siblings: Sequence[str],
        ancestors: Sequence[str],
    ) -> ChildRedundancyDecision:
        if candidate in {PARENT_REDUNDANT_A, PARENT_REDUNDANT_B} or candidate.endswith(
            "omformulering"
        ):
            return ChildRedundancyDecision(
                accepted=False,
                rejection_reason="redundant_with_parent",
                noul=_same_need_noul(key="same_knowledge_need_as_parent"),
                threshold=0.8,
            )
        return ChildRedundancyDecision(accepted=True, noul=_distinct_child_noul(), threshold=0.8)


class NestedExhaustionGenerator(Generator):
    async def decompose(self, *, question: str):
        self.decomposition_calls += 1
        if question == ROOT_EXHAUSTED:
            return [
                GeneratedQuestion(PARENT_REDUNDANT_A),
                GeneratedQuestion(PARENT_REDUNDANT_B),
                GeneratedQuestion(CHILD_A),
                GeneratedQuestion(CHILD_B),
            ]
        return [GeneratedQuestion(f"{question} omformulering")]


@pytest.mark.asyncio
async def test_exhausted_children_are_retrieved_instead_of_waiting(db):
    session, attempt = db
    generator = NestedExhaustionGenerator()
    tree = RecursiveQuestionTree(
        controller=NestedExhaustionController(),
        generator=generator,
        limits=QuestionTreeLimits(max_depth=4, max_children=4, max_questions=8),
        source_types=["swedish_case_law"],
    )
    with research_obs_scope() as stats:
        plan = await tree.prepare_leaf_plan(
            session, attempt_id=attempt.id, root_question=ROOT_EXHAUSTED
        )
    assert {need.question for need in plan.needs} == {CHILD_A, CHILD_B}
    assert {need.generated_from for need in plan.needs} == {"decomposition_fallback"}
    nodes = await list_question_nodes(session, attempt.id)
    children = [node for node in nodes if node.parent_question_id is not None]
    assert {node.question for node in children} == {CHILD_A, CHILD_B}
    assert {node.phase for node in children} == {"ready"}
    assert {node.researchability for node in children} == {"not_researchable"}
    assert {node.decomposition_result for node in children} == {"exhausted"}
    assert {node.execution_override for node in children} == {"best_effort_retrieval"}
    assert stats.decomposition_exhausted_total == 2
    assert stats.decomposition_exhausted_redundancy_total == 2
    assert stats.research_fallback_started_total == 2
    assert generator.decomposition_calls == 3


class TimeoutGenerator(Generator):
    async def decompose(self, *, question: str):
        raise TimeoutError("provider timeout")


@pytest.mark.asyncio
async def test_decomposition_timeout_does_not_start_best_effort_retrieval(db):
    session, attempt = db
    tree = RecursiveQuestionTree(
        controller=LoggedScoreController(
            MULTI_STRUCTURE_NOUL,
            researchable=False,
            decomposable=True,
        ),
        generator=TimeoutGenerator(),
        limits=QuestionTreeLimits(max_depth=4, max_children=4, max_questions=8),
        source_types=["web"],
    )
    with pytest.raises(TimeoutError):
        await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question=BROAD)
    node = (await list_question_nodes(session, attempt.id))[0]
    assert node.execution_override == ""
    assert node.decomposition_result == ""
    assert node.research_need_id is None
    assert node.phase == "decomposing"
    assert node.researchability == "not_researchable"


class FallbackAnswerGenerator(Generator):
    def __init__(self, status: str) -> None:
        super().__init__()
        self.status = status

    async def synthesize_leaf(self, **_kwargs):
        return GeneratedAnswer(text="grundat svar", status=self.status)


async def _exhausted_leaf(session, attempt, *, status: str):
    evidence_set = await create_evidence_set(
        session,
        run_id=attempt.run_id,
        created_from_attempt_id=attempt.id,
    )
    root = await get_or_create_root(session, attempt_id=attempt.id, question="hel fråga")
    root.researchability = "not_researchable"
    root.decomposability = "decomposable"
    root.decomposition_result = "exhausted"
    root.execution_override = "best_effort_retrieval"
    root.execution_override_reason = "no_semantic_progress"
    root.phase = "ready"
    root.research_need_id = f"question-{root.id}"
    await session.commit()
    tree = RecursiveQuestionTree(
        controller=Controller(),
        generator=FallbackAnswerGenerator(status),
        limits=QuestionTreeLimits(max_depth=4, max_children=4, max_questions=8),
        source_types=["web"],
    )
    return evidence_set, root, tree


@pytest.mark.asyncio
async def test_best_effort_retrieval_can_answer_without_rewriting_researchability(db):
    session, attempt = db
    evidence_set, root, tree = await _exhausted_leaf(session, attempt, status="answered")
    with research_obs_scope() as stats:
        await tree.synthesize_wave(session, attempt_id=attempt.id, evidence_set_id=evidence_set.id)
    await session.refresh(root)
    assert root.researchability == "not_researchable"
    assert root.execution_override == "best_effort_retrieval"
    assert root.phase == "completed"
    answer = await session.get(ResearchQuestionAnswer, root.current_answer_id)
    assert answer is not None
    assert answer.status == "answered"
    assert stats.research_fallback_sufficient_total == 1


@pytest.mark.asyncio
async def test_best_effort_insufficient_evidence_is_not_waiting_or_failed(db):
    session, attempt = db
    evidence_set, root, tree = await _exhausted_leaf(
        session, attempt, status="insufficient_evidence"
    )
    with research_obs_scope() as stats:
        await tree.synthesize_wave(session, attempt_id=attempt.id, evidence_set_id=evidence_set.id)
    await session.refresh(root)
    answer = await session.get(ResearchQuestionAnswer, root.current_answer_id)
    assert answer is not None
    assert answer.status == "insufficient_evidence"
    assert root.phase == "evidence_incomplete"
    assert root.phase != "failed"
    assert root.researchability == "not_researchable"
    assert stats.research_fallback_insufficient_total == 1
    calls_before = tree.generator.decomposition_calls
    await tree.prepare_leaf_plan(session, attempt_id=attempt.id, root_question="hel fråga")
    assert tree.generator.decomposition_calls == calls_before


@pytest.mark.asyncio
async def test_not_required_does_not_increase_unresolved_required(db):
    session, attempt = db
    evidence_set = await create_evidence_set(
        session,
        run_id=attempt.run_id,
        created_from_attempt_id=attempt.id,
    )
    root = await get_or_create_root(session, attempt_id=attempt.id, question="parent")
    root.phase = "decomposed"
    root.researchability = "not_researchable"
    root.decomposability = "decomposable"
    root.decomposition_result = "accepted"

    class RecordingController(Controller):
        def __init__(self) -> None:
            self.statuses: list[str] = []

        async def assess_completeness(self, *, question: str, answer: str, child_answers):
            self.statuses = [item.status for item in child_answers]
            return CompletenessDecision(
                status="answered",
                material_gap=False,
                additional_research_likely_to_change_answer=False,
                noul={},
            )

    controller = RecordingController()
    answered = ResearchQuestionNode(
        id="answered-child",
        attempt_id=attempt.id,
        parent_question_id=root.id,
        question="besvarad",
        depth=1,
        created_from="decomposition",
        phase="completed",
        researchability="researchable",
        decomposability="not_decomposable",
    )
    pending = ResearchQuestionNode(
        id="pending-child",
        attempt_id=attempt.id,
        parent_question_id=root.id,
        question="väntar",
        depth=1,
        created_from="decomposition",
        phase="created",
        researchability="researchable",
        decomposability="not_decomposable",
    )
    unresolved = ResearchQuestionNode(
        id="unresolved-child",
        attempt_id=attempt.id,
        parent_question_id=root.id,
        question="saknar svar",
        depth=1,
        created_from="decomposition",
        phase="unresolved",
        researchability="not_researchable",
        decomposability="not_decomposable",
    )
    skipped = ResearchQuestionNode(
        id="skipped-child",
        attempt_id=attempt.id,
        parent_question_id=root.id,
        question="behövdes inte",
        depth=1,
        created_from="decomposition",
        phase="not_required",
        researchability="researchable",
        decomposability="not_decomposable",
    )
    session.add_all([answered, pending, unresolved, skipped])
    await session.flush()
    await append_answer_version(session, node=answered, answer_text="svar", status="answered")
    before = knowledge_need_counts(await list_question_nodes(session, attempt.id))
    tree = RecursiveQuestionTree(
        controller=controller,
        generator=Generator(),
        limits=QuestionTreeLimits(max_depth=4, max_children=4, max_questions=8),
        source_types=["web"],
    )
    await tree.synthesize_wave(session, attempt_id=attempt.id, evidence_set_id=evidence_set.id)
    await session.refresh(root)
    await session.refresh(pending)
    await session.refresh(unresolved)
    await session.refresh(skipped)
    after = knowledge_need_counts(await list_question_nodes(session, attempt.id))
    assert root.phase == "completed"
    assert pending.phase == "not_required"
    assert unresolved.phase == "unresolved"
    assert skipped.phase == "not_required"
    assert before["unresolved_required_question_count"] == 1
    assert after["unresolved_required_question_count"] == 1
    assert "unresolved" in controller.statuses
    assert "not_required" in controller.statuses


@pytest.mark.asyncio
async def test_finished_attempt_does_not_leave_required_nodes_waiting(db):
    session, attempt = db
    root = await get_or_create_root(session, attempt_id=attempt.id, question="root")
    root.phase = "decomposed"
    root.researchability = "not_researchable"
    root.decomposability = "decomposable"
    child = ResearchQuestionNode(
        id="still-created",
        attempt_id=attempt.id,
        parent_question_id=root.id,
        question="barn",
        depth=1,
        created_from="decomposition",
        phase="created",
        researchability="researchable",
        decomposability="not_decomposable",
    )
    session.add(child)
    await session.commit()
    await settle_stranded_question_nodes(session, attempt_id=attempt.id)
    await session.refresh(root)
    await session.refresh(child)
    assert root.phase == "unresolved"
    assert child.phase == "unresolved"
    counts = knowledge_need_counts(await list_question_nodes(session, attempt.id))
    assert counts["unresolved_required_question_count"] == 2
    assert counts["not_required_question_count"] == 0
