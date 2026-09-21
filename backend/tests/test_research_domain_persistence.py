"""Raw documents are shared, while interpretations and claims retain need lineage."""

import json
from dataclasses import replace
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
    ResearchRuntimeNeed,
)
from app.llm.research_assessment import _evidence_payload as assessment_payload
from app.llm.research_completeness import _evidence_payload as completeness_payload
from app.services.execution import (
    add_evidence_items,
    create_attempt,
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
async def test_three_followups_reuse_one_raw_document_and_keep_distinct_analyses(monkeypatch):
    from app.config import settings
    from app.services.lagen_nu.models import ResolvedCitations
    from app.services.lagen_nu.research_source import LagenNuResearchSource
    from app.services.research.knowledge_question import research_question_key
    from tests.test_lagen_nu_provider import (
        FakeLagenNuClient,
        FakeLegalInterpreter,
        PassthroughLagenNuSelector,
        _document,
        _hit,
    )
    from tests.test_research import _context, _need

    engine = create_async_engine(
        "sqlite+aiosqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    uri = "https://lagen.nu/dom/nja/2005s142"
    hit = _hit(
        uri=uri,
        title="NJA 2005 s. 142",
        source="dv",
        pinpoint=None,
        highlight="ansvarsbegränsningen jämkades",
    )
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(hit,)),
        documents={
            uri: _document(
                uri=uri,
                pinpoint=None,
                source="dv",
                text="HD jämkade ansvarsbegränsningen i avtalet.",
            )
        },
    )

    class CountingInterpreter(FakeLegalInterpreter):
        calls = 0

        async def interpret(self, **kwargs):
            self.calls += 1
            return await super().interpret(**kwargs)

    interpreter = CountingInterpreter()
    try:
        async with factory() as session:
            customer = Kund(name="Test", slug="source-reuse", available_modules=["dd"])
            session.add(customer)
            await session.flush()
            run = await create_run(session, customer_id=customer.id, module="dd", title="Research")
            attempt = await create_attempt(session, run_id=run.id, attempt_type="generic_panel")
            evidence_set = await create_evidence_set(
                session, run_id=run.id, created_from_attempt_id=attempt.id
            )
            context = replace(_context(), attempt_id=attempt.id)
            source = LagenNuResearchSource(
                source_type="swedish_case_law",
                client=client,
                selector=PassthroughLagenNuSelector(),
                interpreter=interpreter,
                reuse_session=session,
            )
            for index, question in enumerate(
                (
                    "Vilka villkor jämkades i NJA 2005 s. 142?",
                    "Vilka omständigheter var avgörande i NJA 2005 s. 142?",
                    "Vilken betydelse har NJA 2005 s. 142 för 36 §?",
                )
            ):
                need = _need("swedish_case_law", question=question)
                need = replace(need, id=f"followup-{index}")
                evidence = await source.research(need, context)
                assert len(evidence) == 1 and evidence[0].status == "found"
                await add_evidence_items(session, evidence_set_id=evidence_set.id, items=evidence)
                await session.flush()
            assert sum(name == "get_document" for name, _ in client.calls) == 1
            assert len((await session.scalars(select(RawSource))).all()) == 1
            assert len((await session.scalars(select(DomainResearchResultRecord))).all()) == 3
            assert interpreter.calls == 3
            session.add(
                ResearchRuntimeNeed(
                    id="runtime-first",
                    attempt_id=attempt.id,
                    research_need_id="followup-0",
                    question="Vilka villkor jämkades i NJA 2005 s. 142?",
                    why_needed="test",
                    question_key=research_question_key("Vilka villkor jämkades i NJA 2005 s. 142?"),
                )
            )
            await session.flush()
            same_need = replace(
                _need("swedish_case_law", question="Vilka villkor jämkades i NJA 2005 s. 142?"),
                id="same-question-again",
            )
            same_evidence = await source.research(same_need, context)
            assert same_evidence[0].metadata["reused_domain_result_id"]
            await add_evidence_items(session, evidence_set_id=evidence_set.id, items=same_evidence)
            await session.flush()
            assert len((await session.scalars(select(DomainResearchResultRecord))).all()) == 3
            assert interpreter.calls == 3
            from app.api.execution import _evidence_set_out

            first_error = research_evidence(
                research_need_id="followup-2",
                source_type="swedish_case_law",
                status="error",
                title="NJA 2005 s. 142",
                source_id=uri,
                source_url=uri,
                provider="lagen_nu",
                metadata={
                    "reason": "legal_domain_extraction_failed",
                    "error_type": "LegalDomainExtractionError",
                },
            )
            await add_evidence_items(
                session, evidence_set_id=evidence_set.id, items=[first_error, first_error]
            )
            items = await list_evidence_items(session, evidence_set.id)
            assert len([item for item in items if item.status == "error"]) == 1
            response = _evidence_set_out(evidence_set, items)
            assert len(response.sources) == 1
            assert len(response.sources[0].research_need_ids) == 4
            assert len(response.sources[0].domain_result_ids) == 3
            assert response.sources[0].error_count == 1

            other_question = "Varför jämkades villkoret i NJA 2005 s. 142?"
            second_attempt = await create_attempt(
                session, run_id=run.id, attempt_type="generic_panel"
            )
            session.add(
                ResearchRuntimeNeed(
                    id="runtime-second",
                    attempt_id=second_attempt.id,
                    research_need_id="followup-0",
                    question=other_question,
                    why_needed="test",
                    question_key=research_question_key(other_question),
                )
            )
            await session.flush()
            other_need = replace(
                _need("swedish_case_law", question=other_question), id="followup-0"
            )
            raw_text = client.documents[uri].text
            assert (
                await source._cached_domain_result(
                    need=other_need, source_uri=uri, raw_text=raw_text
                )
                is None
            )

            old = datetime(2020, 1, 1, tzinfo=UTC)
            for item in items:
                item.retrieved_at = old
            raw_row = (await session.scalars(select(RawSource))).one()
            raw_row.created_at = old
            await session.flush()
            monkeypatch.setattr(settings, "research_knowledge_freshness_max_age_seconds", 60)
            second_set = await create_evidence_set(
                session, run_id=run.id, created_from_attempt_id=second_attempt.id
            )
            second_context = replace(_context(), attempt_id=second_attempt.id)
            second_evidence = await source.research(other_need, second_context)
            await add_evidence_items(session, evidence_set_id=second_set.id, items=second_evidence)
            await session.flush()
            assert sum(name == "get_document" for name, _ in client.calls) == 2
            assert interpreter.calls == 4

            third_attempt = await create_attempt(
                session, run_id=run.id, attempt_type="generic_panel"
            )
            third_context = replace(_context(), attempt_id=third_attempt.id)
            await source.research(other_need, third_context)
            assert sum(name == "get_document" for name, _ in client.calls) == 2
            assert interpreter.calls == 4

            for source_type in ("swedish_case_law", "swedish_law"):
                await add_evidence_items(
                    session,
                    evidence_set_id=evidence_set.id,
                    items=[
                        research_evidence(
                            research_need_id="followup-2",
                            source_type=source_type,
                            status="error",
                            provider="lagen_nu",
                            metadata={"reason": "provider_error", "error_type": "McpError"},
                        )
                    ],
                )
            items = await list_evidence_items(session, evidence_set.id)
            assert len([item for item in items if item.status == "error"]) == 3
    finally:
        await engine.dispose()


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
