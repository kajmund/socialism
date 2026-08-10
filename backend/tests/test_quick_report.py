"""Unit tests for snabbrapport verdict rules."""

from __future__ import annotations

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, TopicPack
from app.services.report.charts import (
    prefill_quick_chart_slots,
    render_quick_ab_bars,
    render_quick_stats_table,
)
from app.services.report.metrics import BundleMetrics, ReportMetrics, compute_report_metrics
from app.services.report.quick import (
    _diff_band,
    _style_html,
    _style_relative_diff,
    decide_verdict,
)
from app.services.ssr.anchors import TONE_LABELS_SV


def _tone(**overrides: float) -> dict[str, float]:
    base = {lab: 0.0 for lab in TONE_LABELS_SV}
    base.update(overrides)
    return base


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


def test_verdict_strong_when_positive_majority():
    b = _bundle_with_likes(5)
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares=_tone(**{"Starkt positiv": 0.4, "Något positiv": 0.2, "Neutral": 0.4}),
        tone_mode="ssr",
    )
    m = compute_report_metrics([b], [clf])
    v = decide_verdict(m, [b], locale="sv")
    assert v.key == "strong"


def test_verdict_zero_when_no_injection_likes():
    b = _bundle_with_likes(0)
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares=_tone(**{"Starkt positiv": 0.6, "Neutral": 0.4}),
        tone_mode="ssr",
    )
    m = compute_report_metrics([b], [clf])
    v = decide_verdict(m, [b], locale="sv")
    assert v.key == "zero"


def test_verdict_weak_when_critical_dominates():
    b = _bundle_with_likes(2)
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares=_tone(
            **{"Starkt negativ": 0.4, "Något negativ": 0.2, "Starkt positiv": 0.1, "Neutral": 0.3}
        ),
        tone_mode="ssr",
    )
    m = compute_report_metrics([b], [clf])
    v = decide_verdict(m, [b], locale="sv")
    assert v.key == "weak"


def test_style_relative_diff_noise_is_none_band():
    # 9.0 vs 8.9 ≈ 1.1% of top — below weak threshold (3%)
    assert _style_relative_diff(9.0, 8.9) < 0.03
    assert _diff_band(_style_relative_diff(9.0, 8.9)) == "none"
    assert _diff_band(_style_relative_diff(5.0, 4.7)) == "weak"  # 6%
    assert _diff_band(_style_relative_diff(5.0, 3.0)) == "clear"  # 40%


def _metrics_with_styles(styles: list[tuple[str, float]]) -> ReportMetrics:
    agg = BundleMetrics(
        label="A",
        agent_count=1,
        post_count=1,
        comment_count=0,
        ticks_run=1,
        gini=0.0,
        zero_like_agents=0,
        mid_agents=0,
        top_agents=1,
        post_likes=0,
        comment_likes=0,
        likes_total=0,
        shares=0,
        dislikes=0,
        follow_edges=0,
        engagement_score=0,
        injection_likes=0,
        topic_shares={"Belysning": 1.0},
        tone_shares=_tone(**{"Neutral": 1.0}),
        style_avg_likes=styles,
        top_actors=[],
    )
    return ReportMetrics(
        n_runs=1,
        bundles=[agg],
        aggregate=agg,
        cross_table=[],
        tone_mode="ssr",
    )


def test_style_html_does_not_crown_winner_on_noise():
    m = _metrics_with_styles(
        [
            ("Sarkastisk + konkret kritik", 9.0),
            ("Fakta + yrkesauktoritet", 8.9),
            ("Provocerande / konfronterande", 0.0),
        ]
    )
    html = _style_html(m, locale="sv")
    assert "Ingen meningsfull skillnad" in html
    assert "Vinnande stil" not in html
    assert "inom brus" in html


def test_style_html_clear_difference_names_winner():
    m = _metrics_with_styles(
        [
            ("Sarkastisk + konkret kritik", 5.0),
            ("Fakta + yrkesauktoritet", 3.0),
            ("Provocerande / konfronterande", 0.0),
        ]
    )
    html = _style_html(m, locale="sv")
    assert "Tydlig skillnad" in html
    assert "Vinnande stil" in html
    assert "Näst" in html


def test_quick_stats_table_includes_engagement_columns():
    b = _bundle_with_likes(4)
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares=_tone(**{"Neutral": 1.0}),
        tone_mode="ssr",
    )
    m = compute_report_metrics([b], [clf])
    html = render_quick_stats_table(m, locale="sv")
    assert '<span class="fn">*</span>' in html
    assert "Likes testbudskap" in html
    assert "Delningar" in html
    assert "4" in html


def _ab_metrics() -> ReportMetrics:
    bundles = [
        RunBundle(
            label="Version A",
            run_id=1,
            run_name="T",
            attempt_id="a1",
            seed="1",
            engine="none",
            agents=[{"index": 1, "member_name": "Anna", "role": "population"}],
            posts=[{"post_id": 1, "user_id": 1, "content": "Bra", "num_likes": 10}],
            comments=[],
            ticks_run=3,
            variant_id="a",
        ),
        RunBundle(
            label="Version B",
            run_id=1,
            run_name="T",
            attempt_id="a1",
            seed="1",
            engine="none",
            agents=[{"index": 1, "member_name": "Anna", "role": "population"}],
            posts=[{"post_id": 1, "user_id": 1, "content": "Uselt", "num_likes": 3}],
            comments=[],
            ticks_run=3,
            variant_id="b",
        ),
    ]
    clfs = [
        BundleClassification(
            topic_packs=[TopicPack(label="T", keywords=["t"])],
            topic_shares={"T": 1.0},
            tone_shares=_tone(**{"Starkt positiv": 0.6, "Neutral": 0.4}),
            tone_mode="ssr",
        ),
        BundleClassification(
            topic_packs=[TopicPack(label="T", keywords=["t"])],
            topic_shares={"T": 1.0},
            tone_shares=_tone(**{"Starkt negativ": 0.5, "Neutral": 0.5}),
            tone_mode="ssr",
        ),
    ]
    return compute_report_metrics(bundles, clfs)


def test_quick_ab_bars_renders_comparison():
    m = _ab_metrics()
    html = render_quick_ab_bars(m, locale="sv")
    assert "A/B" in html
    assert "Version A" in html
    assert "Version B" in html
    assert '<span class="fn">*</span>' in html


def test_prefill_quick_chart_slots_ab_mode():
    m = _ab_metrics()
    bundles = [
        RunBundle(
            label="Version A",
            run_id=1,
            run_name="T",
            attempt_id="a1",
            seed="1",
            engine="none",
            agents=[],
            ticks_run=1,
            variant_id="a",
        ),
        RunBundle(
            label="Version B",
            run_id=1,
            run_name="T",
            attempt_id="a1",
            seed="1",
            engine="none",
            agents=[],
            ticks_run=1,
            variant_id="b",
        ),
    ]
    slots = prefill_quick_chart_slots(m, bundles, locale="sv", ab=True)
    assert "stats-table" in slots["stats_html"]
    assert "ab-compare" in slots["charts_html"]
    assert "ab-tone-grid" in slots["charts_html"]
