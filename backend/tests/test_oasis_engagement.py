"""Unit tests for OASIS stratified engagement model (no camel-oasis)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.services.oasis_engagement import (
    StimulusEngagement,
    comment_ids_from_trace,
    comment_post_ids,
    injector_post_ids_after,
    make_round_rng,
    max_post_id,
    read_trace_since,
    sample_fraction,
    stratified_agent_sample,
    trace_row_count,
)


def test_sample_fraction_first_vs_later():
    assert sample_fraction(0) > sample_fraction(1)
    assert sample_fraction(0) == 0.6
    assert sample_fraction(2) == 0.35


def test_stratified_sample_covers_strata():
    eligible = {0, 1, 2, 3, 4, 5}
    strata = {0: "A", 1: "A", 2: "B", 3: "B", 4: "C", 5: "C"}
    rng = make_round_rng("seed", 0, 0)
    picked = stratified_agent_sample(
        eligible, strata=strata, fraction=0.5, rng=rng
    )
    assert picked
    assert {strata[i] for i in picked} == {"A", "B", "C"}


def test_engagement_passive_excludes_from_eligible():
    session = StimulusEngagement()
    session.reset_for_stimulus({10})
    session.passive.add(2)
    session.engaged.add(1)
    eligible = session.eligible_agents({0, 1, 2, 3})
    assert eligible == {0, 1, 3}


def test_engagement_comment_requires_prior_engagement():
    session = StimulusEngagement()
    session.reset_for_stimulus({10})
    assert session.may_comment(0) is False
    session.engaged.add(0)
    assert session.may_comment(0) is True


def test_engagement_record_trace_marks_passive_and_engaged():
    session = StimulusEngagement()
    session.reset_for_stimulus({42})
    session.record_trace_rows(
        [
            {"user_id": 1, "action": "do_nothing", "info": "{}"},
            {"user_id": 2, "action": "like_post", "info": '{"post_id": 42}'},
            {"user_id": 3, "action": "like_comment", "info": '{"comment_id": 7}'},
        ],
        comment_to_post={7: 42},
    )
    assert 1 in session.passive
    assert 2 in session.engaged
    assert 3 in session.engaged
    assert session.may_comment(2)
    assert session.may_comment(1) is False


def test_engagement_engaged_not_marked_passive_on_do_nothing():
    session = StimulusEngagement()
    session.reset_for_stimulus({5})
    session.engaged.add(4)
    session.record_trace_rows(
        [{"user_id": 4, "action": "do_nothing", "info": "{}"}],
        comment_to_post={},
    )
    assert 4 in session.engaged
    assert 4 not in session.passive


def test_injector_post_ids_and_trace_helpers(tmp_path: Path):
    db = tmp_path / "sim.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE post (post_id INTEGER PRIMARY KEY, user_id INTEGER, content TEXT,
            original_post_id INTEGER, quote_content TEXT, num_likes INTEGER,
            num_dislikes INTEGER, num_shares INTEGER, created_at INTEGER);
        CREATE TABLE comment (comment_id INTEGER PRIMARY KEY, post_id INTEGER,
            user_id INTEGER, content TEXT, num_likes INTEGER, num_dislikes INTEGER,
            created_at INTEGER);
        CREATE TABLE trace (user_id INTEGER, created_at INTEGER, action TEXT, info TEXT);
        INSERT INTO post (post_id, user_id, content, original_post_id, quote_content,
            num_likes, num_dislikes, num_shares, created_at)
        VALUES (1, 0, 'old', NULL, NULL, 0, 0, 0, 1);
        INSERT INTO post (post_id, user_id, content, original_post_id, quote_content,
            num_likes, num_dislikes, num_shares, created_at)
        VALUES (2, 99, 'inject', NULL, NULL, 0, 0, 0, 2);
        INSERT INTO comment (comment_id, post_id, user_id, content, num_likes,
            num_dislikes, created_at)
        VALUES (5, 2, 3, 'hej', 0, 0, 3);
        INSERT INTO trace (user_id, created_at, action, info)
        VALUES (1, 1, 'do_nothing', '{}');
        INSERT INTO trace (user_id, created_at, action, info)
        VALUES (2, 2, 'like_post', '{"post_id": 2}');
        """
    )
    conn.commit()
    conn.close()

    assert max_post_id(db) == 2
    assert injector_post_ids_after(db, injector_indices={99}, after_post_id=1) == frozenset(
        {2}
    )
    assert trace_row_count(db) == 2
    rows = read_trace_since(db, 1)
    assert len(rows) == 1
    assert rows[0]["action"] == "like_post"
    assert comment_post_ids(db, {5}) == {5: 2}
    assert comment_ids_from_trace(
        [{"user_id": 0, "action": "create_comment", "info": '{"comment_id": 5}'}]
    ) == {5}
