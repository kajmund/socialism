"""Tests for trace enrichment and live_progress catch-up replay."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Population, Run
from app.services.oasis_engagement import read_trace_range, read_trace_since
from app.services.run_live_progress import append_live_progress_entry, read_live_progress
from app.services.run_trace_enrich import (
    activity_items_from_trace_rows,
    enrich_trace_rows,
)
from app.services.run_watch import build_run_replay_payload


def _seed_trace_db(db: Path) -> None:
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE post (
            post_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            content TEXT,
            original_post_id INTEGER,
            quote_content TEXT,
            num_likes INTEGER,
            num_dislikes INTEGER,
            num_shares INTEGER,
            created_at INTEGER
        );
        CREATE TABLE comment (
            comment_id INTEGER PRIMARY KEY,
            post_id INTEGER,
            user_id INTEGER,
            content TEXT,
            num_likes INTEGER,
            num_dislikes INTEGER,
            created_at INTEGER
        );
        CREATE TABLE trace (
            user_id INTEGER,
            created_at INTEGER,
            action TEXT,
            info TEXT
        );
        INSERT INTO post (post_id, user_id, content, original_post_id, quote_content,
            num_likes, num_dislikes, num_shares, created_at)
        VALUES (10, 1, 'Hej världen', NULL, NULL, 0, 0, 0, 1);
        INSERT INTO comment (comment_id, post_id, user_id, content, num_likes,
            num_dislikes, created_at)
        VALUES (5, 10, 2, 'Svar', 0, 0, 2);
        INSERT INTO trace (user_id, created_at, action, info) VALUES
            (1, 1, 'create_post', '{"post_id": 10}');
        INSERT INTO trace (user_id, created_at, action, info) VALUES
            (2, 2, 'create_comment', '{"comment_id": 5}');
        INSERT INTO trace (user_id, created_at, action, info) VALUES
            (3, 3, 'do_nothing', '{}');
        """
    )
    conn.commit()
    conn.close()


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as s:
        pop = Population(name="Livepop", size=0, versions=1, fingerprint=[], recipe={})
        s.add(pop)
        await s.commit()
        yield s
    await engine.dispose()


def test_read_trace_since_includes_created_at(tmp_path: Path):
    db = tmp_path / "simulation.db"
    _seed_trace_db(db)
    rows = read_trace_since(db, 0)
    assert len(rows) == 3
    assert rows[0]["created_at"] == 1
    assert rows[1]["action"] == "create_comment"


def test_read_trace_range_reads_round_slice(tmp_path: Path):
    db = tmp_path / "simulation.db"
    _seed_trace_db(db)
    rows = read_trace_range(db, 1, 3)
    assert len(rows) == 2
    assert rows[0]["action"] == "create_comment"
    assert rows[1]["action"] == "do_nothing"


def test_enrich_trace_rows_attaches_content(tmp_path: Path):
    db = tmp_path / "simulation.db"
    _seed_trace_db(db)
    rows = read_trace_range(db, 0, 3)
    enriched = enrich_trace_rows(db, rows)
    assert enriched[0]["content"] == "Hej världen"
    assert enriched[0]["post_id"] == 10
    assert enriched[1]["content"] == "Svar"
    assert enriched[1]["comment_id"] == 5
    assert enriched[1]["post_id"] == 10


def test_activity_items_match_enriched_rows(tmp_path: Path):
    db = tmp_path / "simulation.db"
    _seed_trace_db(db)
    rows = read_trace_range(db, 0, 2)
    enriched = enrich_trace_rows(db, rows)
    items = activity_items_from_trace_rows(enriched)
    assert items[0] == {
        "user_id": 1,
        "action": "create_post",
        "created_at": 1,
        "post_id": 10,
        "content": "Hej världen",
    }
    assert items[1]["comment_id"] == 5
    assert items[1]["post_id"] == 10


@pytest.mark.asyncio
async def test_build_run_replay_from_live_progress(
    session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db = tmp_path / "simulation.db"
    _seed_trace_db(db)
    pop = await session.get(Population, 1)
    assert pop is not None
    run = Run(
        name="Live",
        status="running",
        population_id=pop.id,
        seed="s",
        main_ticks=[],
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    monkeypatch.setattr(
        "app.services.run_watch.variant_artifact_db",
        lambda run_id, variant_id: tmp_path / "simulation.db",
    )

    await append_live_progress_entry(
        session,
        run_id=run.id,
        variant_id="main",
        entry={
            "tick_index": 0,
            "round_index": 0,
            "trace_start": 0,
            "trace_end": 2,
        },
    )
    await append_live_progress_entry(
        session,
        run_id=run.id,
        variant_id="main",
        entry={
            "tick_index": 0,
            "round_index": 1,
            "trace_start": 2,
            "trace_end": 3,
        },
    )
    await session.refresh(run)

    progress = read_live_progress(run, "main")
    assert len(progress) == 2

    replay = build_run_replay_payload(run, variant_id="main")
    assert replay["type"] == "run.replay"
    assert replay["run_id"] == run.id
    assert replay["variant_id"] == "main"
    assert len(replay["rounds"]) == 2
    assert replay["rounds"][0]["items"][0]["content"] == "Hej världen"
    assert replay["rounds"][1]["items"][0]["action"] == "do_nothing"
