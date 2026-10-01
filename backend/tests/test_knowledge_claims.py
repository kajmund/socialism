"""Knowledge claims are assertions SUPPORTED_BY TextUnits."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import KnowledgeClaimRecord, KnowledgeClaimTextUnit, Kund
from app.services.knowledge.claims import (
    SUPPORTED_BY,
    KnowledgeClaim,
    KnowledgeClaimError,
    knowledge_claim_id,
    persist_knowledge_claim,
    supporting_text_unit_ids_for_claim,
    supporting_text_unit_ids_for_quote,
)
from app.services.knowledge.units import TextUnit
from tests.text_unit_fakes import persisted_text_unit


def _passage(unit_id: str, text: str) -> TextUnit:
    return TextUnit(
        id=unit_id,
        document_version_id="ver-a",
        document_id="doc-a",
        section_id="sec-1",
        ordinal=0,
        text=text,
        content_hash=unit_id,
    )


def test_quote_grounds_to_the_unit_that_contains_it():
    units = [
        _passage("tu-bg", "The lease was signed in 1998."),
        _passage("tu-hold", "The court held that the clause was not adjusted."),
    ]
    assert supporting_text_unit_ids_for_quote(
        "the clause was not adjusted",
        units,
    ) == ["tu-hold"]


def test_quote_spanning_two_units_grounds_to_both():
    units = [
        _passage("tu-42", "The court held that"),
        _passage("tu-43", "the clause was not adjusted."),
    ]
    assert supporting_text_unit_ids_for_quote(
        "The court held that\n\nthe clause was not adjusted.",
        units,
    ) == ["tu-42", "tu-43"]


def test_missing_quote_fails_loud():
    with pytest.raises(KnowledgeClaimError, match="absent from TextUnits"):
        supporting_text_unit_ids_for_quote("invented holding", [_passage("tu-1", "No holding here.")])


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(Kund(id=1, name="acme", slug="acme", available_modules=["dd"]))
        await db.flush()
        yield db
    await engine.dispose()


async def _persist_supported_claim(session: AsyncSession):
    from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord

    session.add(
        CanonicalDocumentRecord(
            id="doc-a",
            customer_id=1,
            source_type="upload",
            canonical_uri="doc://a",
            title="A",
            extra={},
        )
    )
    session.add(
        DocumentVersionRecord(
            id="ver-a",
            document_id="doc-a",
            customer_id=1,
            content_hash="hash",
            mime_type="text/plain",
            extra={},
        )
    )
    session.add(
        await persisted_text_unit(session,
            id="tu-hold",
            document_version_id="ver-a",
            document_id="doc-a",
            customer_id=1,
            section_id=None,
            ordinal=0,
            text="The court held that the clause was not adjusted.",
        )
    )
    await session.flush()
    value = {"value": False}
    claim = KnowledgeClaim(
        id=knowledge_claim_id(
            scope_key="customer:1",
            predicate="outcome.granted",
            value=value,
        ),
        customer_id=1,
        predicate="outcome.granted",
        value=value,
        supporting_text_unit_ids=("tu-hold",),
    )
    await persist_knowledge_claim(session, claim)
    await session.flush()
    stored = await session.get(KnowledgeClaimRecord, claim.id)
    assert stored is not None
    assert stored.predicate == "outcome.granted"
    assert await supporting_text_unit_ids_for_claim(session, claim.id) == ["tu-hold"]
    link = (
        await session.execute(
            KnowledgeClaimTextUnit.__table__.select().where(
                KnowledgeClaimTextUnit.claim_id == claim.id
            )
        )
    ).one()
    assert link.relation == SUPPORTED_BY


async def test_persist_claim_writes_supported_by_links(session: AsyncSession):
    await _persist_supported_claim(session)


async def test_support_attach_is_idempotent_even_when_existing_read_is_stale(
    session: AsyncSession, monkeypatch
):
    from unittest.mock import AsyncMock
    from app.services.knowledge.claim_store import attach_supporting_text_units

    await _persist_supported_claim(session)
    claim = (await session.execute(select(KnowledgeClaimRecord))).scalars().one()
    # Both writers can observe no link before the first commits it.
    monkeypatch.setattr(
        "app.services.knowledge.claim_store.supporting_text_unit_ids_for_claim",
        AsyncMock(return_value=[]),
    )
    await attach_supporting_text_units(session, claim.id, ["tu-hold", "tu-hold"])
    links = list((await session.execute(select(KnowledgeClaimTextUnit))).scalars())
    assert len(links) == 1
    assert links[0].relation == SUPPORTED_BY
