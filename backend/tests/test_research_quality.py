"""Evidence quality: programmatic signals, lagen.nu provenance, persist, read model."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Kund
from app.services.execution import (
    add_evidence_items,
    create_attempt,
    create_evidence_set,
    create_run,
    get_attempt,
    get_evidence_set,
    list_evidence_items,
    list_evidence_quality,
    persist_evidence_quality,
)
from app.services.lagen_nu.models import SearchResults
from app.services.lagen_nu.registration import (
    LAGEN_NU_PROVIDER_ID,
    LAGEN_NU_PUBLICATION_NOTE,
    lagen_nu_descriptor,
)
from app.services.research import (
    KnowledgeProviderDescriptor,
    ProviderAccess,
    ResearchExecutionError,
    ResearchNeed,
    ResearchPlan,
    ResearchRouter,
    ResearchSourceRegistry,
    execute_attempt_research,
    research_evidence,
)
from app.services.research.assessment import (
    AssessableEvidence,
    programmatic_assessment,
)
from app.services.research.execution import quality_input_from_item
from app.services.research.quality import (
    EVIDENCE_QUALITY_POLICY_VERSION,
    FLAG_AUTHORITY_WARNING,
    FLAG_NOT_OFFICIAL_PUBLICATION,
    EvidenceQualityError,
    EvidenceRelevanceJudgment,
    QualityEvidenceInput,
    assess_evidence_quality,
    independence_key,
    quality_model_identity_key,
)
from app.services.research.registry import standard_capability_descriptors
from tests.test_lagen_nu_provider import FakeLagenNuClient, _document, _hit, _source
from tests.test_research import _context
from tests.test_research_execution import RecordingSource, _created_attempt, _need, _router


def _input(**overrides: object) -> QualityEvidenceInput:
    values: dict[str, object] = {
        "item_id": "item-1",
        "original_evidence_id": "ev-1",
        "research_need_id": "need-1",
        "source_type": "swedish_law",
        "status": "found",
        "title": "Titel",
        "excerpt": "Utdrag",
        "locator": None,
        "source_id": None,
        "source_url": None,
        "provider": LAGEN_NU_PROVIDER_ID,
        "provenance": {},
        "retrieved_at": datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        "content_hash": "hash-1",
    }
    values.update(overrides)
    return QualityEvidenceInput(**values)  # type: ignore[arg-type]


def _need_row(need_id: str = "need-1") -> ResearchNeed:
    return ResearchNeed(
        id=need_id,
        question="Vad gäller avtalslagen 36 §?",
        why_needed="behövs",
        source_types=["swedish_law"],
    )


def test_quality_module_has_no_provider_special_case():
    text = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "research"
        / "quality.py"
    ).read_text(encoding="utf-8")
    assert "lagen_nu" not in text
    assert "lagen.nu" not in text


def _official_descriptor() -> KnowledgeProviderDescriptor:
    return KnowledgeProviderDescriptor(
        provider_id="gazette.swedish_law",
        domains=frozenset({"public"}),
        modalities=frozenset({"text"}),
        capabilities=frozenset({"search"}),
        evidence_natures=frozenset({"swedish_law"}),
        authority={
            "retrieval_provider": "gazette",
            "official_publication": True,
            "primary_source": True,
        },
        access=ProviderAccess(mechanism="api"),
        rank=1,
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
        yield session
    await engine.dispose()


async def test_duplicate_canonical_source_is_not_corroboration():
    first = _input(
        item_id="a",
        source_id="https://lagen.nu/1915:218#P36",
        source_url="https://lagen.nu/1915:218#P36",
        content_hash="hash-a",
    )
    second = _input(
        item_id="b",
        source_id="https://lagen.nu/1915:218#P1",
        source_url="https://lagen.nu/1915:218#P1",
        content_hash="hash-b",
    )
    assert independence_key(first) == independence_key(second)
    drafts = await assess_evidence_quality([first, second], needs=[_need_row()])
    assert {draft.independent_source_count for draft in drafts} == {1}


async def test_two_independent_sources_count_as_corroboration():
    first = _input(
        item_id="a",
        source_id="https://lagen.nu/1915:218",
        content_hash="hash-a",
    )
    second = _input(
        item_id="b",
        source_id="https://lagen.nu/1962:700",
        content_hash="hash-b",
    )
    drafts = await assess_evidence_quality([first, second], needs=[_need_row()])
    assert independence_key(first) != independence_key(second)
    assert {draft.independent_source_count for draft in drafts} == {2}


async def test_unknown_recency_and_authority_are_not_guessed():
    drafts = await assess_evidence_quality(
        [_input(provider="supabase", source_type="case_knowledge", provenance={})],
        descriptors=standard_capability_descriptors(),
    )
    assert drafts[0].authority == "unknown"
    assert drafts[0].currentness == "unknown"
    assert drafts[0].source_nature == "unknown"
    assert drafts[0].source_timestamp is None
    assert drafts[0].relevance == "unknown"


async def test_explicit_trusted_descriptor_overrides_transport_warnings():
    official = _input(
        item_id="official",
        provider="gazette",
        source_id="https://example.test/sfs/1915:218",
        provenance={},
    )
    automated = _input(
        item_id="auto",
        provider=LAGEN_NU_PROVIDER_ID,
        source_id="https://lagen.nu/1915:218",
        provenance={
            "not_official_publication": True,
            "automated_corpus": True,
            "authority_warning": "Automated corpus is not an official publication.",
        },
    )
    drafts = await assess_evidence_quality(
        [official, automated],
        descriptors=(_official_descriptor(), lagen_nu_descriptor("swedish_law")),
    )
    by_id = {draft.evidence_set_item_id: draft for draft in drafts}
    assert by_id["official"].authority == "official"
    assert by_id["official"].source_nature == "primary"
    assert by_id["auto"].authority == "trusted"
    assert by_id["auto"].source_nature == "primary"
    assert {flag.code for flag in by_id["auto"].flags} >= {
        FLAG_NOT_OFFICIAL_PUBLICATION,
        FLAG_AUTHORITY_WARNING,
    }


async def test_lagen_nu_is_a_trusted_primary_source_aggregator():
    client = FakeLagenNuClient(
        search=SearchResults(query="jämkning", total=1, results=(_hit(),)),
        documents={"https://lagen.nu/1915:218#P36": _document()},
    )
    need = _need_row()
    evidence = await _source(client).research(need, _context())
    assert [item.status for item in evidence] == ["found"]
    item = evidence[0]
    drafts = await assess_evidence_quality(
        [
            QualityEvidenceInput(
                item_id="persisted-1",
                original_evidence_id=item.evidence_id,
                research_need_id=item.research_need_id,
                source_type=item.source_type,
                status=item.status,
                title=item.title,
                excerpt=item.excerpt,
                locator=item.locator,
                source_id=item.source_id,
                source_url=item.source_url,
                provider=item.provider,
                provenance=dict(item.metadata),
                retrieved_at=item.retrieved_at,
                content_hash="seen-1",
            )
        ],
        needs=[need],
        descriptors=(lagen_nu_descriptor("swedish_law"),),
    )
    draft = drafts[0]
    assert item.metadata["official_source_aggregator"] is True
    assert item.metadata["publication_note"] == LAGEN_NU_PUBLICATION_NOTE
    assert draft.authority == "trusted"
    assert draft.source_nature == "primary"
    assert draft.currentness == "unknown"
    assert draft.relevance == "unknown"
    assert draft.flags == []
    assert independence_key(
        QualityEvidenceInput(
            item_id="x",
            original_evidence_id=None,
            research_need_id=need.id,
            source_type="swedish_law",
            status="found",
            title=None,
            excerpt=None,
            locator=None,
            source_id=item.source_id,
            source_url=item.source_url,
            provider=item.provider,
            provenance={},
            retrieved_at=item.retrieved_at,
            content_hash="z",
        )
    ) == "https://lagen.nu/1915:218"


async def test_relevance_failure_cannot_produce_high_quality():
    class Boom:
        async def judge(self, need: ResearchNeed, item: QualityEvidenceInput):
            raise RuntimeError("model down")

    with pytest.raises(EvidenceQualityError, match="Relevance assessor failed"):
        await assess_evidence_quality(
            [
                _input(
                    provenance={
                        "not_official_publication": True,
                        "automated_corpus": True,
                    }
                )
            ],
            needs=[_need_row()],
            descriptors=(lagen_nu_descriptor("swedish_law"),),
            relevance_assessor=Boom(),
        )


def test_model_identity_key_includes_provider_name_and_version():
    programmatic = quality_model_identity_key(
        model_provider=None, model_name=None, model_version=None
    )
    same_version_a = quality_model_identity_key(
        model_provider="cerebras", model_name="gpt-oss-120b", model_version="1"
    )
    same_version_b = quality_model_identity_key(
        model_provider="deepseek", model_name="deepseek-chat", model_version="1"
    )
    unnamed = quality_model_identity_key(
        model_provider="cerebras", model_name="gpt-oss-120b", model_version=None
    )
    assert programmatic != same_version_a
    assert same_version_a != same_version_b
    assert same_version_a != unnamed
    assert quality_model_identity_key(
        model_provider="cerebras", model_name="gpt-oss-120b", model_version="1"
    ) == same_version_a


async def test_quality_does_not_flip_programmatic_sufficient():
    quality = (
        await assess_evidence_quality(
            [
                _input(
                    provenance={
                        "not_official_publication": True,
                        "authority_warning": "Secondary source warning.",
                    }
                )
            ],
            descriptors=(lagen_nu_descriptor("swedish_law"),),
        )
    )[0]
    evidence = AssessableEvidence(
        evidence_id="ev-1",
        research_need_id="need-1",
        source_type="swedish_law",
        status="found",
        title="Avtal",
        excerpt="jämkas",
        locator="P36",
        source_id="https://lagen.nu/1915:218#P36",
        source_url="https://lagen.nu/1915:218#P36",
        provider=LAGEN_NU_PROVIDER_ID,
        score=1.0,
        provenance={"not_official_publication": True},
        retrieved_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        content_hash="hash-1",
        quality=quality,
    )
    assessment = programmatic_assessment(ResearchPlan(needs=[_need_row()]), [evidence])
    assert assessment.result == "sufficient"
    assert assessment.need_assessments[0].sufficient is True


@pytest.mark.asyncio
async def test_same_evidence_and_policy_is_idempotent(db: AsyncSession):
    kund = Kund(name="acme", slug="acme-quality", available_modules=["dd"])
    db.add(kund)
    await db.flush()
    run = await create_run(
        db, customer_id=kund.id, module="dd", title="Kvalitet", context={}
    )
    attempt = await create_attempt(
        db,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={},
        input_snapshot={},
    )
    evidence_set = await create_evidence_set(
        db, run_id=run.id, created_from_attempt_id=attempt.id
    )
    items = await add_evidence_items(
        db,
        evidence_set_id=evidence_set.id,
        items=[
            research_evidence(
                research_need_id="need-1",
                source_type="swedish_law",
                status="found",
                excerpt="jämkas",
                source_id="https://lagen.nu/1915:218#P36",
                source_url="https://lagen.nu/1915:218#P36",
                provider=LAGEN_NU_PROVIDER_ID,
                metadata={
                    "authority_level": "trusted",
                    "primary_source": True,
                    "source_nature": "primary",
                    "official_source_aggregator": True,
                    "publication_note": LAGEN_NU_PUBLICATION_NOTE,
                },
            )
        ],
    )
    drafts = await assess_evidence_quality(
        [quality_input_from_item(item) for item in items],
        descriptors=(lagen_nu_descriptor("swedish_law"),),
    )
    first = await persist_evidence_quality(
        db, evidence_set_id=evidence_set.id, drafts=drafts
    )
    second = await persist_evidence_quality(
        db, evidence_set_id=evidence_set.id, drafts=drafts
    )
    await db.commit()
    rows = await list_evidence_quality(db, evidence_set.id)
    assert len(first) == 1
    assert len(second) == 1
    assert first[0].id == second[0].id
    assert len(rows) == 1
    assert rows[0].scoring_policy_version == EVIDENCE_QUALITY_POLICY_VERSION
    assert rows[0].authority == "trusted"
    assert items[0].excerpt == "jämkas"


@pytest.mark.asyncio
async def test_loop_persists_lagen_nu_quality_and_keeps_evidence(db: AsyncSession):
    _customer, _run, attempt = await _created_attempt(db, slug="lagen-quality")
    client = FakeLagenNuClient(
        search=SearchResults(query="jämkning", total=1, results=(_hit(),)),
        documents={"https://lagen.nu/1915:218#P36": _document()},
    )
    registry = ResearchSourceRegistry()
    registry.register(
        _source(client),
        descriptor=lagen_nu_descriptor("swedish_law"),
    )
    result = await execute_attempt_research(
        db,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("need-1", "swedish_law")]),
        router=ResearchRouter(registry),
        max_follow_up_waves=0,
    )
    assert result.status == "ready"
    assert result.found_count == 1
    items = await list_evidence_items(db, result.evidence_set_id)
    quality = await list_evidence_quality(db, result.evidence_set_id)
    assert len(items) == 1
    assert items[0].status == "found"
    assert items[0].provider == LAGEN_NU_PROVIDER_ID
    assert items[0].provenance["official_source_aggregator"] is True
    assert len(quality) == 1
    row = quality[0]
    assert row.evidence_set_item_id == items[0].id
    assert row.original_evidence_id == items[0].original_evidence_id
    assert row.scoring_policy_version == EVIDENCE_QUALITY_POLICY_VERSION
    assert row.authority == "trusted"
    assert row.source_nature == "primary"
    assert row.currentness == "unknown"
    assert row.relevance == "unknown"
    assert row.independence_key == "https://lagen.nu/1915:218"
    assert row.flags == []


@pytest.mark.asyncio
async def test_loop_tenant_evidence_stays_unknown_authority(db: AsyncSession):
    _customer, _run, attempt = await _created_attempt(db, slug="tenant-quality")
    found = RecordingSource("case_knowledge")
    router, _ = _router(found)
    result = await execute_attempt_research(
        db,
        attempt_id=attempt.id,
        research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
        router=router,
        max_follow_up_waves=0,
    )
    quality = await list_evidence_quality(db, result.evidence_set_id)
    assert result.status == "ready"
    assert len(quality) == 1
    assert quality[0].authority == "unknown"
    assert quality[0].currentness == "unknown"
    assert quality[0].source_nature == "unknown"


@pytest.mark.asyncio
async def test_distinct_relevance_models_persist_separate_rows(db: AsyncSession):
    kund = Kund(name="acme", slug="acme-quality-models", available_modules=["dd"])
    db.add(kund)
    await db.flush()
    run = await create_run(
        db, customer_id=kund.id, module="dd", title="Kvalitet", context={}
    )
    attempt = await create_attempt(
        db,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot={},
        input_snapshot={},
    )
    evidence_set = await create_evidence_set(
        db, run_id=run.id, created_from_attempt_id=attempt.id
    )
    items = await add_evidence_items(
        db,
        evidence_set_id=evidence_set.id,
        items=[
            research_evidence(
                research_need_id="need-1",
                source_type="swedish_law",
                status="found",
                excerpt="jämkas",
                source_id="https://lagen.nu/1915:218",
                provider=LAGEN_NU_PROVIDER_ID,
            )
        ],
    )

    class Fixed:
        def __init__(self, provider: str, name: str, version: str) -> None:
            self.provider = provider
            self.name = name
            self.version = version

        async def judge(self, need: ResearchNeed, item: QualityEvidenceInput):
            return EvidenceRelevanceJudgment(
                relevance="medium",
                model_provider=self.provider,
                model_name=self.name,
                model_version=self.version,
            )

    first = await assess_evidence_quality(
        [quality_input_from_item(item) for item in items],
        needs=[_need_row()],
        relevance_assessor=Fixed("cerebras", "gpt-oss-120b", "1"),
    )
    second = await assess_evidence_quality(
        [quality_input_from_item(item) for item in items],
        needs=[_need_row()],
        relevance_assessor=Fixed("deepseek", "deepseek-chat", "1"),
    )
    stored = await persist_evidence_quality(
        db, evidence_set_id=evidence_set.id, drafts=[*first, *second]
    )
    await db.commit()
    rows = await list_evidence_quality(db, evidence_set.id)
    assert len(stored) == 2
    assert len(rows) == 2
    assert {row.model_provider for row in rows} == {"cerebras", "deepseek"}
    assert {row.model_identity_key for row in rows} == {
        quality_model_identity_key(
            model_provider="cerebras", model_name="gpt-oss-120b", model_version="1"
        ),
        quality_model_identity_key(
            model_provider="deepseek", model_name="deepseek-chat", model_version="1"
        ),
    }


@pytest.mark.asyncio
async def test_relevance_failure_fail_closes_attempt(db: AsyncSession):
    class Boom:
        async def judge(self, need: ResearchNeed, item: QualityEvidenceInput):
            raise RuntimeError("model down")

    _customer, _run, attempt = await _created_attempt(db, slug="quality-fail")
    found = RecordingSource("case_knowledge")
    router, _ = _router(found)
    with pytest.raises(ResearchExecutionError):
        await execute_attempt_research(
            db,
            attempt_id=attempt.id,
            research_plan=ResearchPlan(needs=[_need("research_1", "case_knowledge")]),
            router=router,
            relevance_assessor=Boom(),
            max_follow_up_waves=0,
        )
    reloaded = await get_attempt(db, attempt.id)
    evidence_set = await get_evidence_set(db, reloaded.evidence_set_id)
    assert reloaded.status == "failed"
    assert evidence_set.status == "failed"
