from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Kund, Persona, ResearchQuestionExpert
from app.llm import set_structured_completer
from app.llm.expert_gen import ExpertCandidate, ExpertCandidatesOut
from app.serializers import blank_profile
from app.services.execution import create_attempt, create_run
from app.services.panel.question_expert_adapters import (
    PanelCompetencyQuestionMatcher,
    UnderlagExpertCreator,
)
from app.services.research.question_domain import (
    GeneralQuestionDraft,
    create_general_question,
    create_specific_question,
)
from app.services.research.question_expert_assignment import (
    ExpertAssignmentQuestion,
    ExpertCandidateIdentity,
    ResearchQuestionExpertAssignmentError,
    assign_unowned_research_questions,
)


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as db:
        yield db
    await engine.dispose()


async def _setup(session, questions=("Vilka skatteregler gäller?",)):
    customer = Kund(name="Acme", slug="acme", available_modules=["expertgranskning"])
    session.add(customer)
    await session.flush()
    run = await create_run(
        session,
        customer_id=customer.id,
        module="expertgranskning",
        title="Avtalsgranskning",
        context={},
    )
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="research_question_dag",
        configuration_snapshot={},
        input_snapshot={},
    )
    specific = await create_specific_question(
        session,
        run_id=run.id,
        text="Vad innebär klausul 2?",
        context={},
        origin_kind="expertgranskning",
    )
    rows = []
    for text in questions:
        rows.append(
            await create_general_question(
                session,
                attempt_id=attempt.id,
                specific_question_id=specific.id,
                draft=GeneralQuestionDraft(
                    question=text,
                    raised_by_expert_ids=["requesting-expert"],
                ),
            )
        )
    await session.flush()
    return customer, attempt, rows


def _expert(customer_id: int, *, expert_id: str, name: str, competence: str) -> Persona:
    profile = blank_profile(name)
    profile.kompetensomrade = competence
    profile.yrkesbakgrund = name
    return Persona(
        id=expert_id,
        customer_id=customer_id,
        kind="expert",
        name=name,
        age=None,
        occ=name,
        district="—",
        quote="",
        profile=profile.model_dump(),
        tools=[],
    )


class SelectMatcher:
    def __init__(self, selected: str | None):
        self.selected = selected
        self.calls = []

    async def match_expert(self, *, question, candidates):
        self.calls.append((question, candidates))
        if self.selected == "first" and candidates:
            return candidates[0].expert_id
        return self.selected


class PersistingCreator:
    def __init__(self):
        self.calls = 0

    async def create_expert(self, session, *, question):
        self.calls += 1
        persona = _expert(
            question.customer_id,
            expert_id=f"created-{self.calls}",
            name="Skattejurist",
            competence="Svensk skatterätt",
        )
        session.add(persona)
        await session.flush()
        return ExpertCandidateIdentity(
            expert_id=persona.id,
            name=persona.name,
            profile="Kompetensområde: Svensk skatterätt",
        )


async def test_existing_customer_expert_is_assigned_without_creation(session):
    customer, attempt, questions = await _setup(session)
    session.add(
        _expert(
            customer.id,
            expert_id="tax-expert",
            name="Skattejurist",
            competence="Svensk skatterätt",
        )
    )
    await session.flush()
    matcher = SelectMatcher("first")
    creator = PersistingCreator()
    result = await assign_unowned_research_questions(
        session,
        attempt_id=attempt.id,
        matcher=matcher,
        creator=creator,
    )
    assert result.matched_count == 1
    assert result.created_count == 0
    assert creator.calls == 0
    await session.refresh(questions[0])
    assert questions[0].status == "pending"
    link = (
        await session.execute(
            select(ResearchQuestionExpert).where(
                ResearchQuestionExpert.question_id == questions[0].id,
                ResearchQuestionExpert.role == "assigned_to",
            )
        )
    ).scalar_one()
    assert link.expert_id == "tax-expert"


async def test_missing_expertise_creates_customer_expert_and_assigns_it(session):
    customer, attempt, questions = await _setup(session)
    matcher = SelectMatcher(None)
    creator = PersistingCreator()
    result = await assign_unowned_research_questions(
        session,
        attempt_id=attempt.id,
        matcher=matcher,
        creator=creator,
    )
    assert result.created_count == 1
    created = await session.get(Persona, "created-1")
    assert created is not None
    assert created.customer_id == customer.id
    assert created.kind == "expert"
    await session.refresh(questions[0])
    assert questions[0].status == "pending"


async def test_new_expert_is_available_to_later_questions_in_same_batch(session):
    _customer, attempt, _questions = await _setup(
        session,
        questions=("Vilka skatteregler gäller?", "Hur beräknas skatten?"),
    )

    class MatchAfterCreate(SelectMatcher):
        async def match_expert(self, *, question, candidates):
            self.calls.append((question, candidates))
            created = next(
                (row for row in candidates if row.expert_id.startswith("created-")), None
            )
            return created.expert_id if created else None

    matcher = MatchAfterCreate(None)
    creator = PersistingCreator()
    result = await assign_unowned_research_questions(
        session,
        attempt_id=attempt.id,
        matcher=matcher,
        creator=creator,
    )
    assert result.question_count == 2
    assert result.created_count == 1
    assert result.matched_count == 1


async def test_matcher_cannot_assign_expert_from_outside_customer_catalog(session):
    _customer, attempt, _questions = await _setup(session)
    with pytest.raises(ResearchQuestionExpertAssignmentError, match="outside"):
        await assign_unowned_research_questions(
            session,
            attempt_id=attempt.id,
            matcher=SelectMatcher("other-customer-expert"),
            creator=PersistingCreator(),
        )


async def test_assignment_requires_expert_who_raised_question(session):
    _customer, attempt, questions = await _setup(session)
    await session.execute(
        ResearchQuestionExpert.__table__.delete().where(
            ResearchQuestionExpert.question_id == questions[0].id,
            ResearchQuestionExpert.role == "raised_by",
        )
    )
    with pytest.raises(ResearchQuestionExpertAssignmentError, match="no raised_by"):
        await assign_unowned_research_questions(
            session,
            attempt_id=attempt.id,
            matcher=SelectMatcher(None),
            creator=PersistingCreator(),
        )


async def test_panel_competency_matcher_uses_profile_and_question_only():
    captured = []

    async def complete(messages, response_model):
        captured.append(messages)
        return response_model(
            has_domain_competence="Skattejurist" in str(messages),
            competence_reason="Svensk skatterätt är kärnkompetensen.",
        )

    set_structured_completer(complete)
    matcher = PanelCompetencyQuestionMatcher(
        prompts={
            "panel.expert.system": "Expert {label}: {profile}",
            "panel.expert.competency": "{topic}\n{brief}\n{profile}",
        }
    )
    matched = await matcher.match_expert(
        question=ExpertAssignmentQuestion(
            question_id="q1",
            question="Vilka skatteregler gäller?",
            why_needed="Avgör skatteeffekten.",
            customer_id=1,
            module="expertgranskning",
        ),
        candidates=(
            ExpertCandidateIdentity("ma", "M&A-rådgivare", "Företagsförvärv"),
            ExpertCandidateIdentity("tax", "Skattejurist", "Svensk skatterätt"),
        ),
    )
    assert matched == "tax"
    assert len(captured) == 2
    assert all("evidence" not in str(messages).lower() for messages in captured)


async def test_underlag_creator_reuses_existing_generator_and_persists_persona(session):
    async def complete(_messages, _response_model):
        return ExpertCandidatesOut(
            candidates=[
                ExpertCandidate(
                    name="Skattejurist",
                    description="Bedömer svensk beskattning.",
                    kompetensomrade="Svensk skatterätt",
                    radgivningsstil="Saklig",
                    yrkesbakgrund="Skattejurist",
                    professionell_anekdot="Har hanterat komplexa skatteavtal.",
                )
            ]
        )

    set_structured_completer(complete)
    creator = UnderlagExpertCreator(
        prompts={
            "expert.from_underlag.system": "{count} {module}",
            "expert.from_underlag.user": "{count} {module} {underlag_text}",
        }
    )
    created = await creator.create_expert(
        session,
        question=ExpertAssignmentQuestion(
            question_id="q1",
            question="Vilka skatteregler gäller?",
            why_needed="Avgör skatteeffekten.",
            customer_id=1,
            module="expertgranskning",
        ),
    )
    persona = await session.get(Persona, created.expert_id)
    assert persona is not None
    assert persona.origin == "research_auto"
    assert persona.profile["kompetensomrade"] == "Svensk skatterätt"
