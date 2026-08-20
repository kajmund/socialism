"""Tests for per-post topic status and reception/discussion split."""

from __future__ import annotations

from app.services.report.bundles import RunBundle
from app.services.report.classify import classify_post_topics, topic_packs_from_injections
from app.services.report.sampling import reception_vs_discussion_rows, sample_reactions_for_ssr


def _bundle(
    *,
    injection_post_id: int = 1,
    injection_text: str = "Stoppa nedsläckningen av belysning i byarna.",
    citizen_post_id: int = 2,
    citizen_post_text: str = "Jag tycker att belysningen är viktig men vem betalar?",
    reception_comment: str | None = "Bra förslag, konkret lösning behövs.",
    discussion_comment: str | None = "Håller med dig, men finansieringen saknas.",
) -> RunBundle:
    posts = [
        {
            "post_id": injection_post_id,
            "user_id": 0,
            "content": injection_text,
            "num_likes": 5,
        },
        {
            "post_id": citizen_post_id,
            "user_id": 1,
            "content": citizen_post_text,
            "num_likes": 2,
        },
    ]
    comments: list[dict] = []
    if reception_comment:
        comments.append(
            {
                "comment_id": 1,
                "post_id": injection_post_id,
                "user_id": 2,
                "content": reception_comment,
                "num_likes": 1,
            }
        )
    if discussion_comment:
        comments.append(
            {
                "comment_id": 2,
                "post_id": citizen_post_id,
                "user_id": 3,
                "content": discussion_comment,
                "num_likes": 0,
            }
        )
    return RunBundle(
        label="A",
        run_id=1,
        run_name="Test",
        attempt_id="att_1",
        seed="42",
        engine="oasis",
        agents=[
            {"index": 0, "member_name": "Parti", "role": "injector"},
            {"index": 1, "member_name": "Anna", "role": "population"},
            {"index": 2, "member_name": "Bo", "role": "population"},
            {"index": 3, "member_name": "Cecilia", "role": "population"},
        ],
        posts=posts,
        comments=comments,
        injection_texts=[injection_text],
    )


def test_on_topic_citizen_post_and_thread_are_reception():
    bundle = _bundle()
    packs = topic_packs_from_injections(bundle.injection_texts)
    post_status = classify_post_topics(bundle, packs)
    assert post_status[2] == "on_topic"
    split = reception_vs_discussion_rows(bundle, post_topic_status=post_status)
    assert len(split.reception) == 3
    assert len(split.discussion) == 0
    texts = {row.text for row in split.reception}
    assert bundle.posts[1]["content"] in texts
    assert any("Bra förslag" in t for t in texts)
    assert any("finansieringen saknas" in t for t in texts)


def test_off_topic_citizen_post_marks_drift_without_extra_drift_event():
    bundle = _bundle(
        reception_comment=None,
        citizen_post_text="Helt unrelated väderprat idag.",
        discussion_comment="Ja det regnar verkligen.",
    )
    packs = topic_packs_from_injections(bundle.injection_texts)
    post_status = classify_post_topics(bundle, packs)
    assert post_status[2] == "drifted"
    split = reception_vs_discussion_rows(bundle, post_topic_status=post_status)
    drifted_posts = [pid for pid, st in post_status.items() if st == "drifted"]
    assert drifted_posts == [2]
    assert len(split.discussion) == 2
    assert len(split.reception) == 0


def test_comment_on_injection_is_on_topic_even_when_off_topic_text():
    bundle = _bundle(
        reception_comment="Totally unrelated weather chat.",
        discussion_comment=None,
        citizen_post_text="Helt unrelated väderprat idag.",
    )
    packs = topic_packs_from_injections(bundle.injection_texts)
    post_status = classify_post_topics(bundle, packs)
    split = reception_vs_discussion_rows(bundle, post_topic_status=post_status)
    assert any("weather chat" in row.text for row in split.reception)
    assert post_status[2] == "drifted"


def test_defense_on_on_topic_citizen_post_is_reception():
    bundle = _bundle(
        reception_comment=None,
        discussion_comment="Jag håller faktiskt med partiet — bra förslag.",
    )
    packs = topic_packs_from_injections(bundle.injection_texts)
    post_status = classify_post_topics(bundle, packs)
    split = reception_vs_discussion_rows(bundle, post_topic_status=post_status)
    assert any("med partiet" in row.text for row in split.reception)
    assert len(split.discussion) == 0


def test_sample_reactions_for_ssr_uses_on_topic_reception():
    bundle = _bundle()
    packs = topic_packs_from_injections(bundle.injection_texts)
    post_status = classify_post_topics(bundle, packs)
    result = sample_reactions_for_ssr(bundle, post_topic_status=post_status)
    assert len(result.texts) == 3
    assert result.meta["scope"] == "reception"
    assert result.meta["reception_eligible_count"] == 3
    assert result.meta["discussion_eligible_count"] == 0


def test_quote_only_post_classifies_and_counts_in_reception():
    injection_text = "Stoppa nedsläckningen av belysning i byarna."
    bundle = RunBundle(
        label="A",
        run_id=1,
        run_name="Test",
        attempt_id="att_1",
        seed="42",
        engine="oasis",
        agents=[
            {"index": 0, "member_name": "Parti", "role": "injector"},
            {"index": 1, "member_name": "Anna", "role": "population"},
            {"index": 2, "member_name": "Bo", "role": "population"},
        ],
        posts=[
            {"post_id": 1, "user_id": 0, "content": injection_text, "num_likes": 5},
            {
                "post_id": 2,
                "user_id": 1,
                "content": "",
                "quote_content": "Belysning i byarna är viktigt.",
                "num_likes": 1,
            },
        ],
        comments=[
            {
                "comment_id": 1,
                "post_id": 2,
                "user_id": 2,
                "content": "Håller med om belysning!",
                "num_likes": 1,
            }
        ],
        injection_texts=[injection_text],
    )
    packs = topic_packs_from_injections(bundle.injection_texts)
    post_status = classify_post_topics(bundle, packs)
    assert post_status[2] == "on_topic"
    split = reception_vs_discussion_rows(bundle, post_topic_status=post_status)
    texts = {row.text for row in split.reception}
    assert "Belysning i byarna är viktigt." in texts
    assert any("Håller med om belysning" in t for t in texts)


def test_empty_repost_inherits_topic_status_for_thread_comments():
    injection_text = "Stoppa nedsläckningen av belysning i byarna."
    bundle = RunBundle(
        label="A",
        run_id=1,
        run_name="Test",
        attempt_id="att_1",
        seed="42",
        engine="oasis",
        agents=[
            {"index": 0, "member_name": "Parti", "role": "injector"},
            {"index": 1, "member_name": "Anna", "role": "population"},
            {"index": 2, "member_name": "Bo", "role": "population"},
        ],
        posts=[
            {"post_id": 1, "user_id": 0, "content": injection_text, "num_likes": 5},
            {
                "post_id": 2,
                "user_id": 1,
                "content": "Helt unrelated väderprat.",
                "num_likes": 1,
            },
            {
                "post_id": 3,
                "user_id": 2,
                "content": "",
                "quote_content": "",
                "original_post_id": 2,
                "num_likes": 0,
            },
        ],
        comments=[
            {
                "comment_id": 1,
                "post_id": 3,
                "user_id": 1,
                "content": "Diskussion under repost",
                "num_likes": 0,
            }
        ],
        injection_texts=[injection_text],
    )
    packs = topic_packs_from_injections(bundle.injection_texts)
    post_status = classify_post_topics(bundle, packs)
    assert post_status[2] == "drifted"
    assert post_status[3] == "drifted"
    split = reception_vs_discussion_rows(bundle, post_topic_status=post_status)
    assert any("Diskussion under repost" in row.text for row in split.discussion)
