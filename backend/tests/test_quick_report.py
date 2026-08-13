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
from app.services.report.quick_glossary import FootnoteContext
from app.services.report.quick import (
    _diff_band,
    _style_html,
    _style_relative_diff,
    decide_verdict,
)
from app.services.report.thresholds import default_report_thresholds
from app.services.ssr.anchors import TONE_LABELS_SV

_DEFAULT_THRESHOLDS = default_report_thresholds()


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
    assert _diff_band(_style_relative_diff(9.0, 8.9), _DEFAULT_THRESHOLDS) == "none"
    assert _diff_band(_style_relative_diff(5.0, 4.7), _DEFAULT_THRESHOLDS) == "weak"  # 6%
    assert _diff_band(_style_relative_diff(5.0, 3.0), _DEFAULT_THRESHOLDS) == "clear"  # 40%


def _metrics_with_styles(styles: list[tuple[str, float]]) -> ReportMetrics:
    agg = BundleMetrics(
        label="A",
        agent_count=1,
        injector_count=1,
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
        style_shares=styles,
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
            ("Sarkastisk + konkret kritik", 0.45),
            ("Fakta + yrkesauktoritet", 0.445),
            ("Provocerande / konfronterande", 0.0),
        ]
    )
    html = _style_html(m, locale="sv", thresholds=_DEFAULT_THRESHOLDS)
    assert "Ingen meningsfull skillnad" in html
    assert "Vanligaste stilen" not in html
    assert "inom brus" in html


def test_style_html_clear_difference_names_most_common_style():
    m = _metrics_with_styles(
        [
            ("Sarkastisk + konkret kritik", 0.5),
            ("Fakta + yrkesauktoritet", 0.3),
            ("Provocerande / konfronterande", 0.0),
        ]
    )
    html = _style_html(m, locale="sv", thresholds=_DEFAULT_THRESHOLDS)
    assert "Tydlig skillnad" in html
    assert "Vanligaste stilen" in html
    assert "50 % av reaktionerna" in html or "50% av reaktionerna" in html
    assert "Näst" in html


def test_style_html_reports_absent_style_as_missing_not_as_zero_reception():
    m = _metrics_with_styles(
        [
            ("Sarkastisk + konkret kritik", 0.6),
            ("Fakta + yrkesauktoritet", 0.4),
            ("Provocerande / konfronterande", 0.0),
        ]
    )
    html = _style_html(m, locale="sv")
    assert "stilen saknas i underlaget" in html
    assert "bekräftat" not in html.lower()


def test_quick_stats_table_includes_engagement_columns():
    b = _bundle_with_likes(4)
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares=_tone(**{"Neutral": 1.0}),
        tone_mode="ssr",
    )
    m = compute_report_metrics([b], [clf])
    with FootnoteContext("sv"):
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
    with FootnoteContext("sv"):
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
