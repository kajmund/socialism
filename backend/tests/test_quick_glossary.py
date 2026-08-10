"""Tests for snabbrapport footnotes and glossary."""

from __future__ import annotations

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, TopicPack
from app.services.report.charts import render_quick_stats_table
from app.services.report.metrics import compute_report_metrics
from app.services.report.quick import build_quick_slots, render_quick_html
from app.services.report.quick_glossary import footnote, render_quick_glossary
from app.services.ssr.anchors import TONE_LABELS_SV


def _bundle_with_likes(injection_likes: int = 3) -> RunBundle:
    return RunBundle(
        label="A",
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


def test_footnote_links_to_glossary_entry():
    html = footnote("likes-total")
    assert 'href="#fn-likes-total"' in html
    assert "<sup" in html


def test_render_quick_glossary_sv_contains_key_terms():
    html = render_quick_glossary(locale="sv")
    assert 'id="ordlista"' in html
    assert "Likes totalt" in html
    assert "Engagemangspoäng" in html
    assert "Simulerat ≠ verkligt" in html
    assert 'id="fn-likes-total"' in html


def test_quick_stats_table_includes_footnotes():
    bundle = _bundle_with_likes(4)
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.0 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
    )
    metrics = compute_report_metrics([bundle], [clf])
    html = render_quick_stats_table(metrics, locale="sv")
    assert 'href="#fn-likes-total"' in html
    assert 'href="#fn-engagement-score"' in html
    assert "ordlistan längst ner" in html


def test_render_quick_html_includes_glossary_section():
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
    assert 'class="glossary"' in html
    assert "Ordlista" in html
    assert 'href="#fn-positive-tone"' in html
    assert "verdict_detail_html" not in html
