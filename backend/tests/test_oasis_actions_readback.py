"""Unit tests for OASIS action lists and SQLite readback (no camel-oasis)."""

import sqlite3
from pathlib import Path

from app.database.models import PopulationMember
from app.services.oasis_profiles import build_user_char, population_action_rules
from app.services.oasis_run import (
    _read_oasis_results,
    parse_oasis_options,
    population_action_names,
)


def _member() -> PopulationMember:
    return PopulationMember(
        id=1,
        population_id=1,
        persona_id=None,
        name="Anna Andersson",
        initials="AA",
        age=42,
        occ="Lärare",
        district="Centrum",
        trait="pragmatisk",
        persona=None,
    )


def test_population_action_names_default_excludes_create_post():
    names = population_action_names()
    assert "CREATE_POST" not in names
    assert "LIKE_POST" in names
    assert "FOLLOW" in names
    assert "UNFOLLOW" in names
    assert "MUTE" in names
    assert "SEARCH_POSTS" in names
    assert "REPORT_POST" in names
    assert "TREND" in names


def test_population_action_names_with_create_post():
    names = population_action_names(allow_population_create_post=True)
    assert names[0] == "CREATE_POST"
    assert "CREATE_COMMENT" in names


def test_parse_oasis_options_defaults():
    opts = parse_oasis_options(None)
    assert opts.allow_population_create_post is False
    opts2 = parse_oasis_options({"allow_population_create_post": True})
    assert opts2.allow_population_create_post is True


def test_user_char_reflects_create_post_flag():
    blocked = build_user_char(_member(), allow_create_post=False)
    assert "Skapa INTE egna inlägg" in blocked
    allowed = build_user_char(_member(), allow_create_post=True)
    assert "FÅR skapa egna inlägg" in allowed
    assert "Skapa INTE egna inlägg" not in allowed


def test_population_action_rules_helpers():
    assert "follow" in population_action_rules(allow_create_post=False).casefold()
    assert "create_post" in population_action_rules(allow_create_post=True).casefold()


def test_read_oasis_results_follow_mute_report_trace(tmp_path: Path):
    db_path = tmp_path / "simulation.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE user (user_id INTEGER PRIMARY KEY);
            CREATE TABLE post (
                post_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                original_post_id INTEGER,
                content TEXT,
                quote_content TEXT,
                num_likes INTEGER,
                num_dislikes INTEGER,
                num_shares INTEGER,
                created_at TEXT
            );
            CREATE TABLE comment (
                comment_id INTEGER PRIMARY KEY,
                post_id INTEGER,
                user_id INTEGER,
                content TEXT,
                num_likes INTEGER,
                num_dislikes INTEGER,
                created_at TEXT
            );
            CREATE TABLE like (like_id INTEGER PRIMARY KEY, user_id INTEGER, post_id INTEGER);
            CREATE TABLE dislike (
                dislike_id INTEGER PRIMARY KEY, user_id INTEGER, post_id INTEGER
            );
            CREATE TABLE comment_like (
                comment_like_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                comment_id INTEGER
            );
            CREATE TABLE comment_dislike (
                comment_dislike_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                comment_id INTEGER
            );
            CREATE TABLE follow (
                follow_id INTEGER PRIMARY KEY,
                follower_id INTEGER,
                followee_id INTEGER,
                created_at TEXT
            );
            CREATE TABLE mute (
                mute_id INTEGER PRIMARY KEY,
                muter_id INTEGER,
                mutee_id INTEGER,
                created_at TEXT
            );
            CREATE TABLE report (
                report_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                post_id INTEGER,
                report_reason TEXT,
                created_at TEXT
            );
            CREATE TABLE trace (
                user_id INTEGER,
                created_at TEXT,
                action TEXT,
                info TEXT
            );
            INSERT INTO post VALUES (1, 0, NULL, 'hej', NULL, 1, 0, 0, '2026-01-01');
            INSERT INTO follow VALUES (1, 2, 0, '2026-01-01');
            INSERT INTO mute VALUES (1, 3, 0, '2026-01-01');
            INSERT INTO report VALUES (1, 2, 1, 'spam', '2026-01-01');
            INSERT INTO trace VALUES (2, '2026-01-01', 'follow', '{}');
            INSERT INTO trace VALUES (2, '2026-01-02', 'like_post', '{}');
            INSERT INTO trace VALUES (3, '2026-01-02', 'like_post', '{}');
            """
        )
        conn.commit()
    finally:
        conn.close()

    feed = _read_oasis_results(db_path)
    assert len(feed["posts"]) == 1
    assert feed["follows"] == [
        {
            "follow_id": 1,
            "follower_id": 2,
            "followee_id": 0,
            "created_at": "2026-01-01",
        }
    ]
    assert feed["mutes"][0]["mute_id"] == 1
    assert feed["mutes"][0]["muter_id"] == 3
    assert feed["reports"][0]["report_id"] == 1
    assert feed["reports"][0]["report_reason"] == "spam"
    assert feed["action_histogram"][0] == {"action": "like_post", "count": 2}
    assert {"action": "follow", "count": 1} in feed["action_histogram"]


def test_read_oasis_results_missing_db(tmp_path: Path):
    feed = _read_oasis_results(tmp_path / "missing.db")
    assert feed["posts"] == []
    assert feed["follows"] == []
    assert feed["action_histogram"] == []
