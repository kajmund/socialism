"""Question write-back must reference the passage actually persisted by research."""

from dataclasses import replace

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import EvidencePassage, KnowledgeQuestionEvidenceLink, KnowledgeQuestionRow, Kund
from app.database.sqlite import async_engine_kwargs, register_sqlite_pragmas
from app.services.execution import add_evidence_items, create_evidence_set, create_run
from app.services.knowledge.models import KnowledgeScope
from app.services.legal_research_result import (
    CaseLawAnalysis,
    LegalCitation,
    LegalQuestionRelation,
    LegalResearchResult,
    LegalSourceIdentity,
    PreparatoryWorkAnalysis,
    StatuteAnalysis,
)
from app.services.research.models import ResearchContext, ResearchNeed, research_evidence
from app.services.research.question_graph_sql import SqlQuestionEvidenceGraph
from app.services.research.question_reuse import commit_persisted_evidence


@pytest.fixture
async def db():
    url = "sqlite+aiosqlite:///:memory:"
    engine = create_async_engine(url, **async_engine_kwargs(url))
    register_sqlite_pragmas(engine, url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            assert await session.scalar(text("PRAGMA foreign_keys")) == 1
            yield session
    finally:
        await engine.dispose()


def _legal_result(kind: str) -> LegalResearchResult | None:
    if kind == "plain":
        return None
    uri = "https://lagen.nu/1915:218#P36"
    citations = [LegalCitation(source_uri=uri, quote="Avtalsvillkor får jämkas")]
    analyses = {
        "statute": StatuteAnalysis(operative_rule="Jämkning", citations=citations),
        "case_law": CaseLawAnalysis(
            legal_issue="Jämkning", court_reasoning="Oskälighet", citations=citations
        ),
        "preparatory_work": PreparatoryWorkAnalysis(
            legislative_intent="Skälighet", proposal_or_commentary="Jämkning", citations=citations
        ),
    }
    return LegalResearchResult(
        source=LegalSourceIdentity(kind=kind, title="36 §", canonical_uri=uri),
        relation=LegalQuestionRelation(
            relation="supports", explanation="Jämkning tillåts", confidence="high"
        ),
        raw_text="Avtalsvillkor får jämkas om villkoret är oskäligt.",
        **{kind: analyses[kind]},
    )


@pytest.mark.parametrize("kind", ["plain", "statute", "case_law", "preparatory_work"])
@pytest.mark.parametrize("explicit_hash", [None, "provider-content-hash"])
async def test_writeback_references_persisted_passage(db, kind, explicit_hash):
    customer = Kund(name="Write-back", slug="writeback", available_modules=["dd"])
    db.add(customer)
    await db.flush()
    run = await create_run(db, customer_id=customer.id, module="dd", title="36 §")
    evidence_set = await create_evidence_set(db, run_id=run.id)
    need = ResearchNeed(
        id="n1",
        question="När får avtalsvillkor jämkas?",
        why_needed="Skälighet",
        source_types=["swedish_law"],
    )
    context = ResearchContext(scope=KnowledgeScope(customer_id=customer.id, module="dd"))
    evidence = research_evidence(
        research_need_id=need.id,
        source_type="swedish_law",
        status="found",
        title="36 §",
        excerpt="Avtalsvillkor får jämkas",
        locator="P36",
        source_id="https://lagen.nu/1915:218",
        source_url="https://lagen.nu/1915:218#P36",
        provider="lagen_nu",
        metadata={"public": True, **({"content_hash": explicit_hash} if explicit_hash else {})},
        legal_result=_legal_result(kind),
    )
    stored = await add_evidence_items(db, evidence_set_id=evidence_set.id, items=[evidence])
    await db.commit()
    graph = SqlQuestionEvidenceGraph()
    for _ in range(2):
        await commit_persisted_evidence(
            db, graph=graph, need=need, context=context, evidence=[evidence]
        )
    links = (await db.scalars(select(KnowledgeQuestionEvidenceLink))).all()
    assert len(links) == 1
    assert {link.visibility for link in links} == {"public"}
    questions = list(await db.scalars(select(KnowledgeQuestionRow)))
    assert all(question.visibility == "tenant" for question in questions)
    assert {link.passage_id for link in links} == {stored[0].passage_id}
    assert await db.scalar(select(func.count()).select_from(EvidencePassage)) == 1

    if kind != "plain":
        second_need = replace(need, id="n2", question="När kan hela avtalet jämkas?")
        second_evidence = replace(
            evidence, research_need_id=second_need.id, evidence_id="second-need-evidence"
        )
        second_stored = await add_evidence_items(
            db, evidence_set_id=evidence_set.id, items=[second_evidence]
        )
        await db.commit()
        await commit_persisted_evidence(
            db, graph=graph, need=second_need, context=context, evidence=[second_evidence]
        )
        assert second_stored[0].passage_id != stored[0].passage_id
        links = (await db.scalars(select(KnowledgeQuestionEvidenceLink))).all()
        assert len(links) == 2
        assert {link.passage_id for link in links} == {
            stored[0].passage_id,
            second_stored[0].passage_id,
        }
