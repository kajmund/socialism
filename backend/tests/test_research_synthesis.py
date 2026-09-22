from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.services.research.assessment import AssessableEvidence, programmatic_assessment
from app.services.research.followup import RuntimeResearchNeed, plan_from_runtime_needs
from app.services.research.synthesis import derive_parent_answers


def sample():
    needs = [
        RuntimeResearchNeed(
            research_need_id="parent", question="Compare both results", why_needed="objective"
        )
    ]
    evidence = []
    for child in ("a", "b"):
        needs.append(
            RuntimeResearchNeed(
                research_need_id=child,
                question=child,
                why_needed="gap",
                parent_research_need_id="parent",
            )
        )
        evidence.append(
            AssessableEvidence(
                evidence_id=f"e-{child}",
                research_need_id=child,
                source_type="web",
                status="found",
                title=child,
                excerpt=f"Verified statement {child}",
                locator=None,
                source_id=f"source-{child}",
                source_url=None,
                provider="test",
                score=None,
                provenance={},
                retrieved_at=datetime.now(UTC),
                content_hash=child,
                claims=(
                    {
                        "id": f"claim-{child}",
                        "predicate": "fact",
                        "value": {"value": child},
                        "citations": [{"quote": f"Verified statement {child}"}],
                    },
                ),
            )
        )
    return needs, evidence


def test_two_answered_children_produce_derived_parent_with_exact_provenance():
    needs, evidence = sample()
    assessment = programmatic_assessment(plan_from_runtime_needs(needs), evidence)
    (result,) = derive_parent_answers(needs, assessment, evidence)
    assert result.research_need_id == "parent"
    assert result.metadata["primary_source"] is False
    assert result.metadata["derived"] is True
    assert {row["evidence_id"] for row in result.metadata["inputs"]} == {"e-a", "e-b"}
    assert {row["source_claim_id"] for row in result.metadata["derived_claims"]} == {
        "claim-a",
        "claim-b",
    }
    assert all(
        row["derived"] and row["research_need_id"] == "parent"
        for row in result.metadata["derived_claims"]
    )
    assert result.evidence_id == derive_parent_answers(needs, assessment, evidence)[0].evidence_id


def test_unanswered_or_cross_need_or_derived_evidence_cannot_be_used():
    needs, evidence = sample()
    assessment = programmatic_assessment(plan_from_runtime_needs(needs), evidence)
    assert not derive_parent_answers(
        needs, assessment, [replace(item, research_need_id="unrelated") for item in evidence]
    )
    assert not derive_parent_answers(
        needs, assessment, [replace(item, provenance={"derived": True}) for item in evidence]
    )
    failed = [replace(item, status="error") for item in evidence]
    assert not derive_parent_answers(
        needs, programmatic_assessment(plan_from_runtime_needs(needs), failed), failed
    )


@pytest.mark.asyncio
async def test_synthesis_persists_then_reassesses_parent_in_research_engine():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.services.execution.service import (
        add_evidence_items,
        create_evidence_set,
        list_evidence_items,
        persist_runtime_needs,
    )
    from app.services.research.assessment import ProgrammaticResearchAssessor
    from app.services.research.execution import _assess_persisted_evidence, assessable_from_item
    from app.services.research.models import research_evidence
    from tests.test_research_execution import _created_attempt

    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            _, run, attempt = await _created_attempt(session)
            needs, _ = sample()
            evidence_set = await create_evidence_set(
                session, run_id=run.id, created_from_attempt_id=attempt.id
            )
            await persist_runtime_needs(session, attempt_id=attempt.id, needs=needs)
            await add_evidence_items(
                session,
                evidence_set_id=evidence_set.id,
                items=[
                    research_evidence(
                        research_need_id=child,
                        source_type="web",
                        status="found",
                        excerpt=f"Fact {child}",
                    )
                    for child in ("a", "b")
                ],
            )
            assessment = await _assess_persisted_evidence(
                session,
                attempt=attempt,
                evidence_set_id=evidence_set.id,
                plan=plan_from_runtime_needs(needs),
                assessor=ProgrammaticResearchAssessor(),
                assessment_pass=1,
            )
            parent = next(
                row for row in assessment.need_assessments if row["research_need_id"] == "parent"
            )
            assert parent["sufficient"] is True
            items = await list_evidence_items(session, evidence_set.id)
            (derived,) = [item for item in items if item.provenance.get("derived")]
            assert parent["supporting_evidence_ids"] == [derived.original_evidence_id]
            assert assessable_from_item(derived).provenance["primary_source"] is False
            await _assess_persisted_evidence(
                session,
                attempt=attempt,
                evidence_set_id=evidence_set.id,
                plan=plan_from_runtime_needs(needs),
                assessor=ProgrammaticResearchAssessor(),
                assessment_pass=1,
            )
            assert len(await list_evidence_items(session, evidence_set.id)) == 3
    finally:
        await engine.dispose()
