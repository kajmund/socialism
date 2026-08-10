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
        html = footnote("likes-total")
        assert html == '<span class="fn">*</span>'
        block = tracker.render_block()
        assert "Likes totalt" in block
        assert 'class="fn-block"' in block


def test_footnote_reuses_same_marker_for_repeat_entry():
    with FootnoteContext("sv"):
        first = footnote("likes-total")
        second = footnote("likes-total")
        third = footnote("engagement-score")
        assert first == second == '<span class="fn">*</span>'
        assert third == '<span class="fn">**</span>'


def test_quick_stats_table_includes_section_footnotes():
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
    assert '<span class="fn">*</span>' in html
    assert "Engagemangspoäng" in html
    assert "ordlistan längst ner" not in html


def test_render_quick_html_uses_slutsats_not_verdict():
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
    assert "Slutsats:" in html
    assert 'class="conclusion"' in html
    assert "Starkt mottagande" not in html
    assert 'class="verdict"' not in html
    assert 'class="glossary"' not in html
    assert "Ordlista" not in html


def test_ab_recommendation_names_winning_version():
    bundle_a = _bundle_with_likes(10, label="Version A")
    bundle_b = _bundle_with_likes(2, label="Version B")
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
    assert rec.recommended_label == "Version A"
    assert "Version A rekommenderas" in rec.headline
    assert "Version A:" in rec.comparison_line
    assert "Version B:" in rec.comparison_line
