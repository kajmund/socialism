import asyncio

import pytest

from app.services.prompt_catalog import default_prompts
from app.services.oasis_swedish import (
    _env_prompt_state,
    apply_swedish_social_environment_prompts,
    enrich_feed_posts,
    set_oasis_user_display_names,
)


def test_enrich_feed_posts_adds_author_names():
    set_oasis_user_display_names(
        {
            0: "Partikonto",
            1: "Susanne Lindgren",
            2: "Lars Berg",
        }
    )
    posts = [
        {
            "post_id": 1,
            "user_id": 0,
            "content": "Budskap",
            "comments": [
                {
                    "comment_id": 1,
                    "user_id": 1,
                    "content": "Pingisbord räcker inte.",
                },
                {
                    "comment_id": 2,
                    "user_id": 2,
                    "content": "Håller med.",
                },
            ],
        }
    ]
    enriched = enrich_feed_posts(posts)
    assert enriched[0]["author_name"] == "Partikonto"
    assert enriched[0]["comments"][0]["author_name"] == "Susanne Lindgren"
    assert enriched[0]["comments"][0]["author_first_name"] == "Susanne"
    assert enriched[0]["comments"][1]["author_first_name"] == "Lars"


def test_enrich_feed_posts_without_mapping_is_noop():
    set_oasis_user_display_names({})
    posts = [{"post_id": 1, "user_id": 1, "content": "hej", "comments": []}]
    assert enrich_feed_posts(posts) == posts


async def test_display_names_are_isolated_across_concurrent_tasks():
    """Concurrent OASIS jobs / A/B variants must not clobber feed author maps."""

    async def enrich_as(mapping: dict[int, str], user_id: int) -> str | None:
        set_oasis_user_display_names(mapping)
        await asyncio.sleep(0.01)
        enriched = enrich_feed_posts(
            [{"post_id": 1, "user_id": user_id, "content": "x", "comments": []}]
        )
        return enriched[0].get("author_name")

    a, b = await asyncio.gather(
        enrich_as({0: "Version A sender", 1: "Anna"}, 0),
        enrich_as({0: "Version B sender", 1: "Bertil"}, 0),
    )
    assert a == "Version A sender"
    assert b == "Version B sender"


async def test_env_prompts_are_isolated_across_concurrent_tasks():
    """Concurrent OASIS jobs must not clobber feed env templates."""
    pytest.importorskip("oasis")

    async def empty_posts_for(marker: str) -> str:
        prompts = dict(default_prompts("sv"))
        prompts["oasis.env.empty_posts"] = marker
        apply_swedish_social_environment_prompts(prompts)
        await asyncio.sleep(0.01)
        return _env_prompt_state().empty_posts

    a, b = await asyncio.gather(
        empty_posts_for("EMPTY-A"),
        empty_posts_for("EMPTY-B"),
    )
    assert a == "EMPTY-A"
    assert b == "EMPTY-B"
