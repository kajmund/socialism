"""Tests for reception vs discussion SSR split and honest tone phrasing."""

from __future__ import annotations

import pytest

from app.services.report.bundles import RunBundle
from app.services.report.classify import (
    BundleClassification,
    honest_negative_tone_phrase,
)
from app.services.report.quick import decide_verdict
from app.services.report.metrics import compute_report_metrics, compute_bundle_metrics
from app.services.report.sampling import (
    reception_vs_discussion_rows,
    sample_reactions_for_ssr,
)
from app.services.report.segment_analysis import AudienceSegmentSummary, build_segment_narrative
from app.services.report.segment_ssr import SegmentToneRow
from app.services.ssr import STYLE_LABELS
from app.services.ssr.anchors import TONE_LABELS_SV


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


def test_reception_vs_discussion_rows_splits_comments_by_parent_post():
    bundle = _bundle()
    split = reception_vs_discussion_rows(bundle)
    assert split.injection_post_ids == frozenset({1})
    assert len(split.reception) == 1
    assert split.reception[0].text.startswith("Bra förslag")
    assert len(split.discussion) == 2
    discussion_texts = {row.text for row in split.discussion}
    assert bundle.posts[1]["content"] in discussion_texts
    assert any("finansieringen saknas" in text for text in discussion_texts)


def test_defense_on_citizen_post_is_discussion_not_reception():
    bundle = _bundle(
        reception_comment=None,
        discussion_comment="Jag håller faktiskt med partiet — bra förslag.",
    )
    split = reception_vs_discussion_rows(bundle)
    assert split.reception == ()
    assert len(split.discussion) == 2
    assert any("med partiet" in row.text for row in split.discussion)


def test_repost_of_injection_is_in_injection_post_ids():
    bundle = _bundle(reception_comment=None, discussion_comment=None)
    bundle.posts.append(
        {
            "post_id": 3,
            "user_id": 1,
            "original_post_id": 1,
            "content": "Citerar budskapet",
            "num_likes": 0,
        }
    )
    split = reception_vs_discussion_rows(bundle)
    assert 3 in split.injection_post_ids
    assert all(row.text != "Citerar budskapet" for row in split.discussion)


def test_sample_reactions_for_ssr_uses_reception_only():
    bundle = _bundle()
    result = sample_reactions_for_ssr(bundle)
    assert result.texts == ["Bra förslag, konkret lösning behövs."]
    assert result.meta["scope"] == "reception"
    assert result.meta["reception_eligible_count"] == 1
    assert result.meta["discussion_eligible_count"] == 2


def test_collect_reactions_merges_reception_and_discussion():
    from app.services.report.sampling import _collect_reactions

    bundle = _bundle()
    split = reception_vs_discussion_rows(bundle)
    combined = _collect_reactions(bundle)
    assert len(combined) == len(split.reception) + len(split.discussion)
    combined_texts = {row.text for row in combined}
    assert split.reception[0].text in combined_texts
    assert any(row.text == split.discussion[0].text for row in split.discussion)


def test_engagement_and_opinion_leaders_use_full_bundle_not_ssr_reception():
    """Engagement tiers and top actors read all posts/comments — not reception SSR sample."""
    bundle = _bundle(reception_comment=None)
    metrics = compute_bundle_metrics(bundle)
    assert metrics.comment_count == 1
    assert metrics.post_count == 2
    assert metrics.engagement_score > 0
    actor_samples = {a["sample"] for a in metrics.top_actors}
    assert bundle.comments[0]["content"] in actor_samples or bundle.posts[1]["content"] in actor_samples


def test_honest_negative_tone_phrase_resigned_not_critical():
    style_shares = [(lab, 0.0) for lab in STYLE_LABELS]
    style_shares[1] = ("Uppgiven + vardagsmetafor", 0.7)
    assert honest_negative_tone_phrase(style_shares, locale="sv") == "missnöjd/uppgiven"
    assert (
        honest_negative_tone_phrase(style_shares, locale="en") == "dissatisfied and resigned"
    )


def test_honest_negative_tone_phrase_sarcastic_stays_critical():
    style_shares = [(lab, 0.0) for lab in STYLE_LABELS]
    style_shares[0] = ("Sarkastisk + konkret kritik", 0.6)
    assert honest_negative_tone_phrase(style_shares, locale="sv") == "kritisk"


def test_honest_negative_tone_phrase_falls_back_when_margin_too_small():
    style_shares = [(lab, 0.0) for lab in STYLE_LABELS]
    style_shares[0] = ("Sarkastisk + konkret kritik", 0.35)
    style_shares[1] = ("Uppgiven + vardagsmetafor", 0.30)
    assert honest_negative_tone_phrase(style_shares, locale="sv") == "negativ ton"
    assert honest_negative_tone_phrase(style_shares, locale="en") == "negative tone"


def test_honest_negative_tone_phrase_resigned_when_margin_clear():
    style_shares = [(lab, 0.0) for lab in STYLE_LABELS]
    style_shares[1] = ("Uppgiven + vardagsmetafor", 0.45)
    style_shares[0] = ("Sarkastisk + konkret kritik", 0.30)
    assert honest_negative_tone_phrase(style_shares, locale="sv") == "missnöjd/uppgiven"


def test_segment_narrative_uses_resigned_wording():
    tone = SegmentToneRow(
        dimension="ort",
        label="Hageby",
        text_count=2,
        agent_count=1,
        positive_share=0.1,
        critical_share=0.6,
        engagement_score=3,
        too_few=False,
        style_shares=[("Uppgiven + vardagsmetafor", 0.8)],
    )
    narrative = build_segment_narrative(
        AudienceSegmentSummary(
            dimension="ort",
            dimension_label="Ort",
            label="Hageby",
            tone=tone,
        ),
        locale="sv",
    )
    assert "missnöjd/uppgiven" in narrative
    assert "kritisk ton" not in narrative


def test_verdict_weak_uses_resigned_label_not_critical():
    bundle = _bundle(reception_comment="Väntat i tre timmar på akuten igen.")
    tone = {lab: 0.0 for lab in TONE_LABELS_SV}
    tone["Starkt negativ"] = 0.5
    tone["Något negativ"] = 0.2
    tone["Neutral"] = 0.3
    style_shares = [(lab, 0.0) for lab in STYLE_LABELS]
    style_shares[1] = ("Uppgiven + vardagsmetafor", 0.75)
    clf = BundleClassification(
        tone_shares=tone,
        tone_mode="ssr",
        style_shares=style_shares,
    )
    metrics = compute_report_metrics([bundle], [clf])
    verdict = decide_verdict(metrics, [bundle], locale="sv")
    assert verdict.key == "weak"
    assert "missnöjd/uppgiven" in verdict.detail
    assert "kritisk" not in verdict.detail
