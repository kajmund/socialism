"""Tests for snabbrapport footnotes and per-section definitions."""

from __future__ import annotations

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, TopicPack
from app.services.report.charts import render_quick_stats_table
from app.services.report.metrics import compute_report_metrics
from app.services.report.quick import build_quick_slots, render_quick_html
from app.services.report.quick_glossary import FootnoteContext, footnote
from app.services.report.recommendation import build_recommendation
from app.services.ssr.anchors import TONE_LABELS_SV


def _bundle_with_likes(injection_likes: int = 3, label: str = "A") -> RunBundle:
    return RunBundle(
        label=label,
        run_id=1,
        run_name="T",
        attempt_id="a1",
        seed="1",
        engine="none",
        agents=[
            {"index": 0, "member_name": "Partikonto", "role": "injector"},
            {"index": 1, "member_name": "Anna", "role": "population"},
        ],
        posts=[
            {
                "post_id": 1,
                "user_id": 0,
                "content": "Stoppa nedsläckningen av belysning i byarna.",
                "num_likes": injection_likes,
            }
        ],
        comments=[],
        ticks_run=3,
        injection_texts=["Stoppa nedsläckningen av belysning i byarna."],
    )


def test_footnote_uses_asterisks():
    with FootnoteContext("sv") as tracker:
        html = footnote("likes-injection")
        assert html == '<span class="fn">*</span>'
        block = tracker.render_block()
        assert "Likes på testbudskap" in block
        assert "SSR" not in block


def test_unknown_footnote_returns_empty():
    with FootnoteContext("sv"):
        assert footnote("does-not-exist") == ""


def test_quick_stats_table_has_few_footnotes():
    bundle = _bundle_with_likes(4)
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.0 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
    )
    metrics = compute_report_metrics([bundle], [clf])
    with FootnoteContext("sv") as tracker:
        html = render_quick_stats_table(metrics, locale="sv") + tracker.render_block()
    assert html.count('<span class="fn">') <= 2
    assert "×" not in html
    assert "SSR" not in html


def test_render_quick_html_recommendation_section():
    bundle = _bundle_with_likes(5)
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={
            **{lab: 0.0 for lab in TONE_LABELS_SV},
            **{"Starkt positiv": 0.6, "Neutral": 0.4},
        },
        tone_mode="ssr",
    )
    metrics = compute_report_metrics([bundle], [clf])
    slots = build_quick_slots(
        title="Test",
        bundles=[bundle],
        classifications=[clf],
        metrics=metrics,
        locale="sv",
        timing={"total_seconds": 0.1, "embed_seconds": 0.1},
    )
    html = render_quick_html(slots, locale="sv")
    assert "Rekommendation" in html
    assert 'class="conclusion"' in html
    assert "Publicera" in html or "publicera" in html
    assert "Starkt mottagande" not in html


def test_ab_recommendation_names_winning_version():
    bundle_a = _bundle_with_likes(10, label="Demo — Version A")
    bundle_b = _bundle_with_likes(2, label="Demo — Version B")
    bundle_a = RunBundle(**{**bundle_a.__dict__, "variant_id": "a"})
    bundle_b = RunBundle(**{**bundle_b.__dict__, "variant_id": "b"})
    clf_a = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={
            **{lab: 0.0 for lab in TONE_LABELS_SV},
            **{"Starkt positiv": 0.6, "Neutral": 0.4},
        },
        tone_mode="ssr",
    )
    clf_b = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={
            **{lab: 0.0 for lab in TONE_LABELS_SV},
            **{"Starkt negativ": 0.5, "Neutral": 0.5},
        },
        tone_mode="ssr",
    )
    metrics = compute_report_metrics([bundle_a, bundle_b], [clf_a, clf_b])
    rec = build_recommendation(
        metrics,
        [bundle_a, bundle_b],
        [clf_a, clf_b],
        audience=[],
        locale="sv",
    )
    assert rec.recommended_arm == "Version A"
    assert len(rec.ab_rows) == 2
    assert any(row.is_winner and row.arm == "Version A" for row in rec.ab_rows)


def test_segment_engagement_bars_renders_footnote_html():
    from app.services.report.charts import _segment_engagement_bars
    from app.services.report.segment_ssr import SegmentToneRow

    tone = SegmentToneRow(
        dimension="ort",
        label="Centrum",
        text_count=5,
        agent_count=2,
        positive_share=0.5,
        critical_share=0.1,
        engagement_score=12,
        too_few=False,
        post_count=3,
        comment_count=2,
        likes_total=8,
        shares_total=1,
    )
    with FootnoteContext("sv"):
        html = _segment_engagement_bars(tone, locale="sv")
    assert "Segmentpoäng<span class=\"fn\">*</span>" in html
    assert "&lt;span" not in html
