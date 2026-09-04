"""Tests for trace enrichment and live_progress catch-up replay."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Population, PopulationMember, Run
from app.services.oasis_engagement import read_trace_range, read_trace_since
from app.services.run_live_progress import append_live_progress_entry, read_live_progress
from app.services.run_trace_enrich import (
    activity_items_from_trace_rows,
    enrich_trace_rows,
)
from app.services.run_watch import build_run_replay_payload, snapshot_live_feed_rounds


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
        pop = Population(
            customer_id=1, name="Livepop", size=0, versions=1, fingerprint=[], recipe={}
        )
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
        "info": {"post_id": 10},
    }
    assert items[1]["comment_id"] == 5
    assert items[1]["post_id"] == 10
    assert items[1]["post_preview"] == "Hej världen"
    assert items[1]["info"]["post_user_id"] == 1


def _seed_social_trace_db(db: Path) -> None:
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
        CREATE TABLE follow (
            follow_id INTEGER PRIMARY KEY,
            follower_id INTEGER,
            followee_id INTEGER,
            created_at INTEGER
        );
        CREATE TABLE report (
            report_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            post_id INTEGER,
            report_reason TEXT,
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
        VALUES (7, 99, 'Olämpligt inlägg', NULL, NULL, 0, 0, 0, 1);
        INSERT INTO comment (comment_id, post_id, user_id, content, num_likes, num_dislikes, created_at)
        VALUES (11, 7, 2, 'En kommentar i tråden', 1, 0, 3);
        INSERT INTO follow (follow_id, follower_id, followee_id, created_at)
        VALUES (3, 1, 2, 1);
        INSERT INTO report (report_id, user_id, post_id, report_reason, created_at)
        VALUES (4, 1, 7, 'spam', 2);
        INSERT INTO trace (user_id, created_at, action, info) VALUES
            (1, 1, 'follow', '{"follow_id": 3}');
        INSERT INTO trace (user_id, created_at, action, info) VALUES
            (1, 2, 'mute', '{"mutee_id": 99}');
        INSERT INTO trace (user_id, created_at, action, info) VALUES
            (1, 3, 'report_post', '{"post_id": 7, "report_id": 4}');
        INSERT INTO trace (user_id, created_at, action, info) VALUES
            (2, 4, 'like_post', '{"post_id": 7}');
        INSERT INTO trace (user_id, created_at, action, info) VALUES
            (1, 5, 'like_comment', '{"comment_id": 11}');
        """
    )
    conn.commit()
    conn.close()


def test_enrich_trace_rows_resolves_social_targets(tmp_path: Path):
    db = tmp_path / "simulation.db"
    _seed_social_trace_db(db)
    rows = read_trace_range(db, 0, 5)
    enriched = enrich_trace_rows(db, rows)
    assert enriched[0]["followee_id"] == 2
    assert enriched[1]["mutee_id"] == 99
    assert enriched[2]["post_id"] == 7
    assert enriched[2]["report_reason"] == "spam"
    assert enriched[2]["post_preview"] == "Olämpligt inlägg"
    assert enriched[4]["comment_id"] == 11
    assert enriched[4]["comment_preview"] == "En kommentar i tråden"
    assert enriched[4]["post_id"] == 7

    items = activity_items_from_trace_rows(enriched)
    assert items[0]["info"] == {"follow_id": 3, "followee_id": 2}
    assert items[1]["info"] == {"mutee_id": 99}
    assert items[2]["info"] == {
        "post_id": 7,
        "report_id": 4,
        "report_reason": "spam",
        "post_user_id": 99,
    }
    assert items[2]["post_preview"] == "Olämpligt inlägg"
    assert items[2]["post_id"] == 7
    assert items[3]["action"] == "like_post"
    assert items[3]["post_preview"] == "Olämpligt inlägg"
    assert items[3]["post_id"] == 7
    assert items[3]["info"]["post_user_id"] == 99
    assert items[4]["action"] == "like_comment"
    assert items[4]["comment_id"] == 11
    assert items[4]["comment_preview"] == "En kommentar i tråden"
    assert items[4]["post_id"] == 7
    assert items[4]["info"]["comment_user_id"] == 2


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
    member = PopulationMember(
        population_id=pop.id,
        name="Anna Holm",
        initials="AH",
        age=40,
        occ="Lärare",
        district="Centrum",
        trait="",
    )
    session.add(member)
    await session.flush()
    run = Run(
        name="Live",
        project_id=1,
        status="running",
        population_id=pop.id,
        seed="s",
        main_ticks=[
            {
                "key": "t1",
                "day": 1,
                "silent": False,
                "injections": [
                    {
                        "key": "i1",
                        "type": "party_post",
                        "sender": "Socialdemokraterna",
                        "text": "Hej",
                        "mode": "text",
                        "url": "",
                        "fetching": False,
                        "sourceDomain": "",
                        "isVideo": False,
                        "message_id": None,
                    }
                ],
                "rounds": 1,
                "measurements": [],
                "interviews": [],
            }
        ],
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

    replay = build_run_replay_payload(
        run,
        variant_id="main",
        members=[member],
    )
    assert replay["type"] == "run.replay"
    assert replay["run_id"] == run.id
    assert replay["variant_id"] == "main"
    assert replay["agents"][0]["member_name"] == "Socialdemokraterna"
    assert replay["agents"][0]["role"] == "injector"
    assert replay["agents"][1]["member_name"] == "Anna Holm"
    assert replay["agents"][1]["index"] == 1
    assert len(replay["rounds"]) == 2
    assert replay["rounds"][0]["items"][0]["content"] == "Hej världen"
    assert replay["rounds"][1]["items"][0]["action"] == "do_nothing"
    frozen = snapshot_live_feed_rounds(run, "main")
    assert frozen == replay["rounds"]
