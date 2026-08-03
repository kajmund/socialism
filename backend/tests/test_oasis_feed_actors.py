"""Tests for reading likes/shares from OASIS artifact DB."""

import sqlite3
from pathlib import Path

from app.services.oasis_run import _read_oasis_results


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE post (
            post_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            original_post_id INTEGER,
            content TEXT,
            quote_content TEXT,
            created_at TEXT,
            num_likes INTEGER DEFAULT 0,
            num_dislikes INTEGER DEFAULT 0,
            num_shares INTEGER DEFAULT 0
        );
        CREATE TABLE comment (
            comment_id INTEGER PRIMARY KEY,
            post_id INTEGER,
            user_id INTEGER,
            content TEXT,
            created_at TEXT,
            num_likes INTEGER DEFAULT 0,
            num_dislikes INTEGER DEFAULT 0
        );
        CREATE TABLE like (
            like_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            post_id INTEGER,
            created_at TEXT
        );
        CREATE TABLE comment_like (
            comment_like_id INTEGER PRIMARY KEY,
            user_id INTEGER,
            comment_id INTEGER,
            created_at TEXT
        );
        INSERT INTO post VALUES (1, 0, NULL, 'Original', NULL, 't', 2, 0, 1);
        INSERT INTO post VALUES (2, 3, 1, 'Original', '', 't', 0, 0, 0);
        INSERT INTO post VALUES (3, 4, 1, 'Original', 'Citat', 't', 0, 0, 0);
        INSERT INTO like VALUES (1, 2, 1, 't');
        INSERT INTO like VALUES (2, 5, 1, 't');
        INSERT INTO comment VALUES (1, 1, 2, 'Bra', 't', 1, 0);
        INSERT INTO comment_like VALUES (1, 4, 1, 't');
        """
    )
    conn.commit()
    conn.close()


def test_read_oasis_results_includes_liked_by_and_shared_by(tmp_path: Path):
    db = tmp_path / "simulation.db"
    _make_db(db)
    feed = _read_oasis_results(db)
    original = next(p for p in feed["posts"] if p["post_id"] == 1)
    assert original["liked_by"] == [2, 5]
    assert original["shared_by"] == [
        {"user_id": 3, "kind": "repost", "share_post_id": 2},
        {"user_id": 4, "kind": "quote", "share_post_id": 3},
    ]
    comment = feed["comments"][0]
    assert comment["liked_by"] == [4]
