"""Fill path reuses OverGraph TextUnits and releases the SQL connection."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Kund, SsrAnchorSet, UserAccount
from app.database.tabular_review import TabularReviewCell
from app.services.knowledge.units import hash_text
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.text_units import load_domain_text_units
from app.services.overgraph.write import upsert_text_unit
from app.services.ssr import set_embedder
from app.services.ssr.similarity import cosine_similarity
from app.services.tabular_review.run import fill_review
from app.services.tabular_review.store import add_column, create_review, set_documents
from app.services.tabular_review.types import ColumnSpec
from tests.conftest import RESEARCH_TEST_DIM
from tests.text_unit_fakes import text_unit_view, text_unit_write


def _vec(*head: float) -> tuple[float, ...]:
    values = list(head) + [0.0] * RESEARCH_TEST_DIM
    return tuple(values[:RESEARCH_TEST_DIM])

CUSTOMER_ID = 11


async def _probe(factory) -> None:
    async with factory() as session:
        assert await session.scalar(select(Kund.id).where(Kund.id == CUSTOMER_ID)) == CUSTOMER_ID


class _ProbingEmbedder:
    def __init__(self, factory):
        self.factory = factory
        self.calls = 0

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        await _probe(self.factory)
        await asyncio.sleep(0.05)
        return [list(_vec(1.0)) for _ in texts]


@pytest.fixture
async def review_db(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'tabular.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.3,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=CUSTOMER_ID, name="Acme", slug="acme", available_modules=["tabular_review"]))
        session.add(UserAccount(id="user-1", email="u@test.local", role="user", kund_id=CUSTOMER_ID))
        session.add(
            CanonicalDocumentRecord(
                id="doc-1",
                scope_type="customer",
                scope_key=f"customer:{CUSTOMER_ID}",
                customer_id=CUSTOMER_ID,
                source_type="upload",
                canonical_uri="doc://doc-1",
                title="Avtal",
                extra={},
            )
        )
        session.add(
            DocumentVersionRecord(
                id="ver-1",
                scope_type="customer",
                scope_key=f"customer:{CUSTOMER_ID}",
                customer_id=CUSTOMER_ID,
                document_id="doc-1",
                content_hash=hash_text("body"),
                mime_type="text/plain",
                extra={},
            )
        )
        session.add(
            SsrAnchorSet(
                id=9,
                name="clause",
                kind="clause",
                locale="sv",
                version="v1",
                labels=["uppsagning"],
                statements=["tre månaders uppsägningstid"],
                status="published",
            )
        )
        await session.commit()
    view = text_unit_view(
        text="Avtalet kan sägas upp med tre månaders uppsägningstid.",
        id="unit-1",
        document_id="doc-1",
        document_version_id="ver-1",
        customer_id=CUSTOMER_ID,
        locator="§12",
        page_start=2,
    )
    upsert_text_unit(require_knowledge(), replace(text_unit_write(view), embedding=_vec(1.0)))
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_fill_reuses_overgraph_units_and_releases_connection(review_db):
    factory = review_db
    units = load_domain_text_units(require_knowledge(), document_version_id="ver-1")
    assert [unit.id for unit in units] == ["unit-1"]
    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0

    embedder = _ProbingEmbedder(factory)
    set_embedder(embedder)
    try:
        async with factory() as session:
            review = await create_review(
                session,
                customer_id=CUSTOMER_ID,
                created_by_user_id="user-1",
                name="Review",
            )
            await set_documents(session, review, ["doc-1"])
            await add_column(
                session,
                review,
                ColumnSpec(
                    column_id=None,
                    title="Uppsägning",
                    anchor_set_id=9,
                    label="uppsagning",
                ),
            )
            await session.commit()
            review_id = review.id

        await fill_review(
            factory,
            review_id,
            catalog=require_knowledge(),
            embeddings_by_document={"doc-1": {"unit-1": list(_vec(1.0))}},
            customer_id=CUSTOMER_ID,
        )
    finally:
        set_embedder(None)

    assert embedder.calls >= 1
    async with factory() as session:
        cells = list((await session.execute(select(TabularReviewCell))).scalars().all())
        assert len(cells) == 1
        assert cells[0].status == "hit"
        assert cells[0].text_unit_id == "unit-1"
