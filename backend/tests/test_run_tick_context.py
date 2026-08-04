"""Unit tests for post-hoc tick feed slicing."""

import pytest

from app.services.run_tick_context import build_persona_feed_context


def _variant() -> dict:
    return {
        "agents": [
            {
                "index": 0,
                "username": "inj",
                "member_name": "Nyhet",
                "persona_id": None,
                "role": "injector",
            },
            {
                "index": 1,
                "username": "anna",
                "member_name": "Anna",
                "persona_id": "p-anna",
                "role": "population",
            },
            {
                "index": 2,
                "username": "bo",
                "member_name": "Bo",
                "persona_id": "p-bo",
                "role": "population",
            },
        ],
        "tick_markers": [
            {
                "tick_index": 0,
                "day": 1,
                "silent": False,
                "key": "t1",
                "rounds": 1,
                "time_start": 0,
                "time_end": 10,
            },
            {
                "tick_index": 1,
                "day": 2,
                "silent": False,
                "key": "t2",
                "rounds": 1,
                "time_start": 11,
                "time_end": 20,
            },
        ],
        "posts": [
            {
                "post_id": 1,
                "user_id": 0,
                "content": "Nyhet dag 1",
                "created_at": 5,
            },
            {
                "post_id": 2,
                "user_id": 0,
                "content": "Nyhet dag 2 — hemlig",
                "created_at": 15,
            },
        ],
        "comments": [
            {
                "comment_id": 1,
                "post_id": 1,
                "user_id": 1,
                "content": "Anna kommenterar dag 1",
                "created_at": 6,
            },
            {
                "comment_id": 2,
                "post_id": 2,
                "user_id": 2,
                "content": "Bo kommenterar dag 2",
                "created_at": 16,
            },
        ],
        "trace": [
            {
                "user_id": 1,
                "created_at": 7,
                "action": "like_post",
                "info": "{}",
            },
            {
                "user_id": 1,
                "created_at": 17,
                "action": "create_comment",
                "info": "{}",
            },
        ],
    }


def test_feed_context_excludes_future_tick_content():
    text, meta = build_persona_feed_context(
        _variant(),
        persona_id="p-anna",
        through_tick_index=0,
    )
    assert meta["day"] == 1
    assert meta["tick_index"] == 0
    assert "Nyhet dag 1" in text
    assert "Anna kommenterar dag 1" in text
    assert "Nyhet dag 2" not in text
    assert "Bo kommenterar dag 2" not in text
    assert "like post" in text
    assert "create comment" not in text


def test_feed_context_through_second_tick_includes_later_posts():
    text, _meta = build_persona_feed_context(
        _variant(),
        persona_id="p-anna",
        through_tick_index=1,
    )
    assert "Nyhet dag 2 — hemlig" in text
    assert "Bo kommenterar dag 2" in text


def test_feed_context_rejects_bad_tick_index():
    with pytest.raises(ValueError):
        build_persona_feed_context(
            _variant(),
            persona_id="p-anna",
            through_tick_index=9,
        )
