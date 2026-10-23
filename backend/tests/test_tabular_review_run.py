"""Fill path reuses OverGraph TextUnits and releases the SQL connection."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, DocumentVersionRecord, Kund, UserAccount
from app.database.tabular_review import TabularReviewCell
from app.services.knowledge.units import hash_text
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.text_units import load_domain_text_units
from app.services.overgraph.write import upsert_text_unit
from app.services.ssr.similarity import cosine_similarity
from app.services.clause_ssr.anchors import promote_anchor
from app.services.clause_ssr.classifications import upsert_classification
from app.services.clause_ssr.select import build_anchor_set
from app.services.clause_ssr.types import EmbeddingSpec
from app.services.clause_ssr.verifications import record_decision
from app.services.knowledge.scope import customer_scope
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


_SET_ID = ""


def _seed_clause_set() -> str:
    scope = customer_scope(CUSTOMER_ID)
    catalog = require_knowledge()
    classification = upsert_classification(
        catalog,
        scope=scope,
        slug="uppsagning",
        question="Är det här en uppsägningsklausul?",
        category="uppsagning",
    )
    verification = record_decision(
        catalog,
        scope=scope,
        classification_id=classification.id,
        unit_id="unit-1",
        reviewer_id="admin-1",
        answer="yes",
    )
    embedding = EmbeddingSpec(model="test", revision="v1", dimension=RESEARCH_TEST_DIM)
    promote_anchor(catalog, verification.id, scope=scope, embedding=embedding)
    return build_anchor_set(catalog, scope=scope, category="uppsagning", embedding=embedding).id


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
    global _SET_ID
    _SET_ID = _seed_clause_set()
    try:
        yield factory
    finally:
        await engine.dispose()


async def _prepare_review(factory) -> int:
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
                anchor_set_id=_SET_ID,
                label="uppsagning",
            ),
        )
        await session.commit()
        return review.id


async def test_fill_reuses_overgraph_units_and_releases_connection(review_db):
    factory = review_db
    units = load_domain_text_units(require_knowledge(), document_version_id="ver-1")
    assert [unit.id for unit in units] == ["unit-1"]
    assert cosine_similarity([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0

    review_id = await _prepare_review(factory)
    await fill_review(
        factory,
        review_id,
        catalog=require_knowledge(),
        embeddings_by_document={"doc-1": {"unit-1": list(_vec(1.0))}},
        customer_id=CUSTOMER_ID,
    )
    async with factory() as session:
        cells = list((await session.execute(select(TabularReviewCell))).scalars().all())
        assert len(cells) == 1
        assert cells[0].status == "hit"
        assert cells[0].text_unit_id == "unit-1"


async def test_fill_fails_when_any_unit_lacks_embedding(review_db):
    factory = review_db
    extra = text_unit_view(
        text="En annan klausul om samråd.",
        id="unit-2",
        document_id="doc-1",
        document_version_id="ver-1",
        customer_id=CUSTOMER_ID,
        locator="§13",
        page_start=3,
    )
    upsert_text_unit(require_knowledge(), replace(text_unit_write(extra), embedding=_vec(0.0, 1.0)))
    review_id = await _prepare_review(factory)
    with pytest.raises(RuntimeError, match="unit-2"):
        await fill_review(
            factory,
            review_id,
            catalog=require_knowledge(),
            embeddings_by_document={"doc-1": {"unit-1": list(_vec(1.0))}},
            customer_id=CUSTOMER_ID,
        )


async def test_fill_resets_unlocked_verdict_when_result_changes(review_db):
    factory = review_db
    review_id = await _prepare_review(factory)
    await fill_review(
        factory,
        review_id,
        catalog=require_knowledge(),
        embeddings_by_document={"doc-1": {"unit-1": list(_vec(1.0))}},
        customer_id=CUSTOMER_ID,
    )
    async with factory() as session:
        cell = (await session.execute(select(TabularReviewCell))).scalar_one()
        cell.review_state = "approved"
        await session.commit()
    stale = text_unit_view(
        text="Detta avtal handlar om samråd och leverans.",
        id="unit-1",
        document_id="doc-1",
        document_version_id="ver-1",
        customer_id=CUSTOMER_ID,
        locator="§12",
        page_start=2,
    )
    extra = text_unit_view(
        text="Avtalet kan sägas upp med tre månaders uppsägningstid.",
        id="unit-2",
        document_id="doc-1",
        document_version_id="ver-1",
        customer_id=CUSTOMER_ID,
        locator="§14",
        page_start=4,
    )
    upsert_text_unit(require_knowledge(), replace(text_unit_write(stale), embedding=_vec(0.0, 1.0)))
    upsert_text_unit(require_knowledge(), replace(text_unit_write(extra), embedding=_vec(1.0)))
    await fill_review(
        factory,
        review_id,
        catalog=require_knowledge(),
        embeddings_by_document={
            "doc-1": {
                "unit-1": list(_vec(0.0, 1.0)),
                "unit-2": list(_vec(1.0)),
            }
        },
        customer_id=CUSTOMER_ID,
    )
    async with factory() as session:
        cell = (await session.execute(select(TabularReviewCell))).scalar_one()
        assert cell.text_unit_id == "unit-2"
        assert cell.review_state == "pending"
