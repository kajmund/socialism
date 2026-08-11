"""Tests for SSR anchor pool items and centroid SSR."""

from __future__ import annotations

import pytest

from app.services.anchor_pool import compute_centroid, drop_centroid_cache
from app.services.ssr import rate_texts, set_embedder, tone_anchors


@pytest.fixture
def mock_embedder():
    async def _mock(texts: list[str]) -> list[list[float]]:
        return [[float((hash(t) + i) % 7) for i in range(8)] for t in texts]

    set_embedder(_mock)
    drop_centroid_cache()
    yield
    set_embedder(None)
    drop_centroid_cache()


def test_compute_centroid_mean():
    vecs = [[1.0, 0.0], [3.0, 0.0]]
    assert compute_centroid(vecs) == pytest.approx([2.0, 0.0])


async def test_pool_add_and_remove(client, mock_embedder):
    listed = await client.get("/anchor-sets?status=published&kind=tone&locale=sv")
    anchor_id = listed.json()[0]["id"]

    create = await client.post(
        f"/anchor-sets/{anchor_id}/pool",
        json={
            "label": "Starkt negativ",
            "text": "Det här är helt oacceptabelt.",
            "source_type": "comment",
            "source_run_id": 1,
            "source_attempt_id": "a1",
            "source_variant_id": "a",
            "source_ref": {"type": "comment", "comment_id": 1},
        },
    )
    assert create.status_code == 201, create.text
    item_id = create.json()["id"]

    pool = await client.get(f"/anchor-sets/{anchor_id}/pool")
    assert pool.status_code == 200
    assert any(row["id"] == item_id for row in pool.json())

    deleted = await client.delete(f"/anchor-sets/{anchor_id}/pool/{item_id}")
    assert deleted.status_code == 204

    pool_after = await client.get(f"/anchor-sets/{anchor_id}/pool")
    assert not any(row["id"] == item_id for row in pool_after.json())


async def test_rate_texts_with_centroid_vectors(mock_embedder):
    anchors = tone_anchors(locale="sv")
    seed_vecs = [[1.0 if i == j else 0.0 for j in range(8)] for i in range(5)]
    result = await rate_texts(
        ["test"],
        anchors,
        temperature=0.1,
        anchor_vectors=seed_vecs,
    )
    assert result.shares
    assert sum(result.shares.values()) == pytest.approx(1.0)


async def test_duplicate_pool_item_rejected(client, mock_embedder):
    listed = await client.get("/anchor-sets?status=published&kind=tone&locale=sv")
    anchor_id = listed.json()[0]["id"]
    body = {
        "label": "Neutral",
        "text": "Unik pooltext för dedup-test.",
        "source_type": "comment",
        "source_ref": {"type": "comment", "comment_id": 99},
    }
    first = await client.post(f"/anchor-sets/{anchor_id}/pool", json=body)
    assert first.status_code == 201
    second = await client.post(f"/anchor-sets/{anchor_id}/pool", json=body)
    assert second.status_code == 400
    other = await client.post(
        f"/anchor-sets/{anchor_id}/pool",
        json={**body, "text": "Annan unik pooltext efter dubblett."},
    )
    assert other.status_code == 201


@pytest.mark.asyncio
async def test_same_session_recovers_after_duplicate_integrity_error(mock_embedder):
    """flush() IntegrityError poisons the session until rollback — verify recovery."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.database.base import Base
    from app.database.models import SsrAnchorSet
    from app.services.anchor_pool import AnchorPoolError, add_pool_item
    from app.services.anchor_store import ensure_default_anchor_sets

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        await ensure_default_anchor_sets(session)
        await session.commit()

    async with session_factory() as session:
        result = await session.execute(
            select(SsrAnchorSet).where(
                SsrAnchorSet.status == "published",
                SsrAnchorSet.kind == "tone",
            )
        )
        row = result.scalars().first()
        assert row is not None
        anchor_id = int(row.id)

        await add_pool_item(
            session,
            anchor_set_id=anchor_id,
            label="Neutral",
            text="Session recovery test text.",
            source_type="comment",
            source_run_id=None,
            source_attempt_id=None,
            source_variant_id=None,
            source_ref={"type": "comment", "comment_id": 1},
        )
        await session.commit()

        with pytest.raises(AnchorPoolError):
            await add_pool_item(
                session,
                anchor_set_id=anchor_id,
                label="Neutral",
                text="Session recovery test text.",
                source_type="comment",
                source_run_id=None,
                source_attempt_id=None,
                source_variant_id=None,
                source_ref={"type": "comment", "comment_id": 1},
            )

        item = await add_pool_item(
            session,
            anchor_set_id=anchor_id,
            label="Neutral",
            text="Session recovery test text — annan.",
            source_type="comment",
            source_run_id=None,
            source_attempt_id=None,
            source_variant_id=None,
            source_ref={"type": "comment", "comment_id": 2},
        )
        await session.commit()
        assert item.id is not None

    await engine.dispose()
