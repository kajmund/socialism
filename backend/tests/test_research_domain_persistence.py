"""Raw documents are shared, while interpretations and claims retain need lineage."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import (
    DomainResearchResultRecord,
    Kund,
    RawSource,
    ResearchClaim,
)
from app.llm.research_assessment import _evidence_payload as assessment_payload
from app.llm.research_completeness import _evidence_payload as completeness_payload
from app.services.execution import (
    add_evidence_items,
    create_evidence_set,
    create_run,
    list_evidence_items,
)
from app.services.legal_research_result import (
    CaseLawAnalysis,
    LegalCitation,
    LegalQuestionRelation,
    LegalResearchResult,
    LegalSourceIdentity,
)
from app.services.research.assessment import EvidenceReviewGroup
from app.services.research.execution import assessable_from_item
from app.services.research.models import research_evidence


@pytest.mark.asyncio
async def test_raw_dedupe_question_specific_results_and_grounded_claims():
    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            customer = Kund(name="Test", slug="research-domain", available_modules=["dd"])
            session.add(customer)
            await session.flush()
            run = await create_run(session, customer_id=customer.id, module="dd", title="Research")
            evidence_set = await create_evidence_set(session, run_id=run.id)
            uri = "https://lagen.nu/dom/nja/2000s1"
            raw = "Domstolen jämkade ansvarsbegränsningen i avtalet."
            source = LegalSourceIdentity(kind="case_law", title="Exempelfall", canonical_uri=uri)

            def evidence(need: str, relation: str):
                legal = LegalResearchResult(
                    source=source,
                    relation=LegalQuestionRelation(
                        relation=relation, explanation="Relevant", confidence="high"
                    ),
                    case_law=CaseLawAnalysis(
                        legal_issue="Jämkning",
                        court_reasoning="Villkoret var oskäligt",
                        outcome="Villkoret jämkades",
                        adjustment_requested=True,
                        adjustment_granted=True,
                        adjusted_term_type="ansvarsbegränsning",
                        decisive_factors=["obalans", "förhandlingsstyrka"],
                        party_context="commercial",
                        citations=[
                            LegalCitation(source_uri=uri, quote="jämkade ansvarsbegränsningen")
                        ],
                    ),
                    raw_text=raw,
                )
                return research_evidence(
                    research_need_id=need,
                    source_type="swedish_case_law",
                    status="found",
                    title=source.title,
                    excerpt="jämkade ansvarsbegränsningen",
                    locator="p1",
                    source_id=uri,
                    source_url=uri,
                    provider="lagen_nu",
                    retrieved_at=datetime.now(UTC),
                    legal_result=legal,
                )

            await add_evidence_items(
                session,
                evidence_set_id=evidence_set.id,
                items=[
                    evidence("need-positive", "supports"),
                    evidence("need-limits", "limits"),
                ],
            )
            await session.commit()
        async with factory() as session:
            items = await list_evidence_items(session, evidence_set.id)
            assert len(items) == 2
            assert len({item.domain_result_id for item in items}) == 2
            assert all("legal_result" not in item.provenance for item in items)
            assert len((await session.scalars(select(RawSource))).all()) == 1
            results = (await session.scalars(select(DomainResearchResultRecord))).all()
            assert {row.research_need_id for row in results} == {"need-positive", "need-limits"}
            claims = (await session.scalars(select(ResearchClaim))).all()
            assert (
                len([claim for claim in claims if claim.predicate == "legal.adjustment_granted"])
                == 2
            )
            assert all(claim.citations[0]["quote"] in raw for claim in claims)
            assessable = [assessable_from_item(item) for item in items]
            assert all(row.legal_result.raw_text == raw for row in assessable)
            assert all(
                any(claim["predicate"] == "legal.adjusted_term_type" for claim in row.claims)
                for row in assessable
            )
            # Prompt payloads must be identical after a different physical insert order.
            record_id = items[0].domain_result_id
            claim_rows = [
                {
                    "id": claim.id,
                    "domain_result_id": claim.domain_result_id,
                    "research_need_id": claim.research_need_id,
                    "predicate": claim.predicate,
                    "value": claim.value,
                    "relation": claim.relation,
                    "citations": claim.citations,
                }
                for claim in items[0].domain_result.claims
            ]

            def prompt_payload(item):
                evidence = assessable_from_item(item)
                group = EvidenceReviewGroup(
                    evidence=evidence,
                    research_need_ids=(evidence.research_need_id,),
                    duplicate_evidence_ids=(),
                )
                return (
                    json.dumps(assessment_payload(group), sort_keys=True),
                    json.dumps(completeness_payload(group), sort_keys=True),
                )

            before = prompt_payload(items[0])
            item_id = items[0].id
        async with factory() as session:
            await session.execute(
                delete(ResearchClaim).where(ResearchClaim.domain_result_id == record_id)
            )
            await session.flush()
            for values in reversed(claim_rows):
                session.add(ResearchClaim(**values))
            await session.commit()
        async with factory() as session:
            reloaded = next(
                item
                for item in await list_evidence_items(session, evidence_set.id)
                if item.id == item_id
            )
            assert prompt_payload(reloaded) == before
            assert [
                (claim.predicate, claim.id) for claim in reloaded.domain_result.claims
            ] == sorted((claim.predicate, claim.id) for claim in reloaded.domain_result.claims)
    finally:
        await engine.dispose()
