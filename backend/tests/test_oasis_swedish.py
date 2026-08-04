from app.services.oasis_swedish import (
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
