"""Tests for bio-segment SSR, audience analysis, and rule-based recommendation."""

from __future__ import annotations

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, TopicPack
from app.services.report.metrics import compute_report_metrics
from app.services.report.recommendation import build_recommendation
from app.services.report.segment_analysis import (
    SegmentArmSummary,
    SegmentInterviewSnippet,
    AudienceSegmentSummary,
    build_audience_comparisons,
    build_audience_summaries,
    build_segment_diff_summary,
    detect_themes,
    interview_relevance,
    rank_interviews_for_display,
)
from app.services.report.segment_ssr import SegmentToneRow
from app.services.report.charts import render_audience_section
from app.services.report.segment_ssr import build_segment_tone_rows
from app.services.ssr.anchors import TONE_LABELS_SV


def _tone_pmf(pos: float, neu: float = 0.2, neg: float = 0.2) -> dict[str, float]:
    return {
        "Starkt negativ": neg * 0.5,
        "Något negativ": neg * 0.5,
        "Neutral": neu,
        "Något positiv": pos * 0.5,
        "Starkt positiv": pos * 0.5,
    }


def _bundle_with_bio() -> RunBundle:
    return RunBundle(
        label="Test",
        run_id=1,
        run_name="T",
        attempt_id="a1",
        seed="1",
        engine="oasis",
        agents=[
            {"index": 1, "persona_id": "p1", "member_name": "Anna", "role": "population"},
            {"index": 2, "persona_id": "p2", "member_name": "Bo", "role": "population"},
        ],
        personas=[
            {
                "persona_id": "p1",
                "name": "Anna",
                "bio": {"livssituation": "Sambo, barn", "ort": "Centrum", "lutning": "Vänster"},
            },
            {
                "persona_id": "p2",
                "name": "Bo",
                "bio": {
                    "livssituation": "Ensamhushåll",
                    "ort": "Hageby",
                    "lutning": "Höger",
                    "yrke": "Elektriker",
                    "kön": "Man",
                    "age": "55",
                },
            },
        ],
        posts=[
            {
                "post_id": 1,
                "user_id": 1,
                "content": "Bra förslag om trygg belysning.",
                "num_likes": 5,
            },
            {
                "post_id": 2,
                "user_id": 2,
                "content": "Vem ska betala? Finansieringen är oklar.",
                "num_likes": 3,
            },
        ],
        comments=[],
        ticks_run=2,
        injection_texts=["Belysning"],
        trace=[
            {
                "user_id": 1,
                "created_at": 2,
                "action": "interview",
                "info": '{"prompt": "Vad tycker du?", "response": "Bra och tryggt för barnfamiljer."}',
            },
        ],
    )


def test_build_segment_tone_rows_groups_by_livssituation():
    bundle = _bundle_with_bio()
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=[
            "Bra förslag om trygg belysning.",
            "Vem ska betala? Finansieringen är oklar.",
        ],
        tone_pmfs=[
            _tone_pmf(0.7, neg=0.1),
            _tone_pmf(0.1, neg=0.6),
        ],
        sample_user_ids=[1, 2],
    )
    rows = build_segment_tone_rows(bundle, clf, locale="sv")
    by_label = {r.label: r for r in rows if r.dimension == "livssituation"}
    assert "Sambo, barn" in by_label
    assert "Ensamhushåll" in by_label
    assert by_label["Sambo, barn"].positive_share > by_label["Ensamhushåll"].positive_share


def test_detect_themes_finds_financing():
    assert "finansiering" in detect_themes("Vem ska betala finansieringen?")


def test_audience_summaries_include_interviews():
    bundle = _bundle_with_bio()
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=["Bra", "Finansiering oklar"],
        tone_pmfs=[_tone_pmf(0.6), _tone_pmf(0.2, neg=0.5)],
        sample_user_ids=[1, 2],
    )
    summaries = build_audience_summaries(bundle, clf, locale="sv")
    fam = next(s for s in summaries if s.label == "Sambo, barn")
    assert fam.interviews
    assert "trygghet" in fam.themes or fam.interviews[0].themes


def test_build_recommendation_produces_score_and_action():
    bundle = _bundle_with_bio()
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={
            **{lab: 0.0 for lab in TONE_LABELS_SV},
            **{"Något positiv": 0.35, "Starkt positiv": 0.15, "Neutral": 0.3, "Något negativ": 0.1, "Starkt negativ": 0.1},
        },
        tone_mode="ssr",
        tone_rated_texts=["a", "b"],
        tone_pmfs=[_tone_pmf(0.5), _tone_pmf(0.3)],
        sample_user_ids=[1, 2],
    )
    metrics = compute_report_metrics([bundle], [clf])
    audience = build_audience_summaries(bundle, clf, locale="sv")
    rec = build_recommendation(metrics, [bundle], [clf], audience, locale="sv")
    assert 0 <= rec.score <= 100
    assert "Rekommendation" in rec.action or "rekommendation" in rec.action.lower()
    assert rec.headline.startswith("Simulerat stöd")


def test_rank_interviews_prefers_financing_and_insight_themes():
    bundle = RunBundle(
        label="T",
        run_id=1,
        run_name="T",
        attempt_id="a",
        seed=None,
        engine=None,
        injection_texts=["Socialdemokraterna vill stoppa nedsläckningen av belysning"],
    )
    generic = SegmentInterviewSnippet(
        agent_name="A",
        question="Tycker du om förslaget?",
        answer="Ja, fine.",
        tick_index=0,
        themes=[],
    )
    insightful = SegmentInterviewSnippet(
        agent_name="B",
        question="Finansiering?",
        answer="Bra idé men finansieringen måste förklaras tydligare med konkret budget.",
        tick_index=1,
        themes=["finansiering", "konkret", "vaghet"],
    )
    ranked = rank_interviews_for_display([generic, insightful], bundle)
    assert ranked[0].agent_name == "B"
    assert interview_relevance(insightful, injection_keywords=["belysning"]) > interview_relevance(
        generic, injection_keywords=["belysning"]
    )


def test_audience_summary_tracks_interview_total():
    bundle = _bundle_with_bio()
    bundle.trace.append(
        {
            "user_id": 1,
            "created_at": 5,
            "action": "interview",
            "info": '{"prompt": "Finansiering?", "response": "Vill se tydlig budget och finansiering."}',
        }
    )
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=["a"],
        tone_pmfs=[_tone_pmf(0.5)],
        sample_user_ids=[1],
    )
    fam = next(
        s
        for s in build_audience_summaries(bundle, clf, locale="sv")
        if s.label == "Sambo, barn"
    )
    assert fam.interview_total == 2
    assert len(fam.interviews) <= 3


def test_interviews_include_respondent_profile():
    bundle = _bundle_with_bio()
    bundle.trace.append(
        {
            "user_id": 2,
            "created_at": 3,
            "action": "interview",
            "info": '{"prompt": "Vad tycker du om belysning?", "response": "Bra idé men finansieringen måste förklaras."}',
        }
    )
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=["Bra", "Finansiering oklar"],
        tone_pmfs=[_tone_pmf(0.6), _tone_pmf(0.2, neg=0.5)],
        sample_user_ids=[1, 2],
    )
    ensam = next(
        s
        for s in build_audience_summaries(bundle, clf, locale="sv")
        if s.label == "Ensamhushåll"
    )
    assert ensam.interviews
    assert "Elektriker" in ensam.interviews[0].profile_line
    assert "ensamhushåll" not in ensam.interviews[0].profile_line.casefold()
    html = render_audience_section([bundle], [clf], locale="sv")
    assert "Elektriker" in html
    assert "qa-profile" in html or "55 år" in html


def test_interviews_shown_on_segments_with_matching_personas():
    bundle = _bundle_with_bio()
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=["Bra", "Finansiering oklar"],
        tone_pmfs=[_tone_pmf(0.6), _tone_pmf(0.2, neg=0.5)],
        sample_user_ids=[1, 2],
    )
    summaries = build_audience_summaries(bundle, clf, locale="sv")
    liv = next(s for s in summaries if s.dimension == "livssituation" and s.label == "Sambo, barn")
    assert liv.interviews
    assert liv.narrative
    assert liv.tone is not None
    assert liv.tone.tone_shares


def test_render_audience_section_includes_mini_reports():
    bundle = _bundle_with_bio()
    clf = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=["Bra", "Finansiering oklar"],
        tone_pmfs=[_tone_pmf(0.6), _tone_pmf(0.2, neg=0.5)],
        sample_user_ids=[1, 2],
    )
    html = render_audience_section([bundle], [clf], locale="sv")
    assert "aud-report" in html
    assert "aud-narrative" in html
    assert "aud-eng-chart" in html
    assert "Enkätfrågor" in html or "enkät" in html.lower()


def _ab_bundles() -> tuple[RunBundle, RunBundle]:
    base = _bundle_with_bio()
    bundle_a = RunBundle(
        **{
            **base.__dict__,
            "label": "Test — Version A",
            "variant_id": "a",
            "injection_texts": ["Belysning A"],
        }
    )
    bundle_b = RunBundle(
        **{
            **base.__dict__,
            "label": "Test — Version B",
            "variant_id": "b",
            "injection_texts": ["Belysning B"],
        }
    )
    return bundle_a, bundle_b


def test_audience_comparisons_group_by_segment_not_version():
    bundle_a, bundle_b = _ab_bundles()
    clf_a = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=[
            "Bra förslag om trygg belysning.",
            "Vem ska betala? Finansieringen är oklar.",
        ],
        tone_pmfs=[_tone_pmf(0.8, neg=0.05), _tone_pmf(0.1, neg=0.6)],
        sample_user_ids=[1, 2],
    )
    clf_b = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=[
            "Bra förslag om trygg belysning.",
            "Vem ska betala? Finansieringen är oklar.",
        ],
        tone_pmfs=[_tone_pmf(0.2, neg=0.5), _tone_pmf(0.75, neg=0.1)],
        sample_user_ids=[1, 2],
    )
    comparisons = build_audience_comparisons(
        [bundle_a, bundle_b], [clf_a, clf_b], locale="sv"
    )
    sambo = next(c for c in comparisons if c.label == "Sambo, barn")
    assert len(sambo.arms) == 2
    assert sambo.arms[0].arm_label == "Version A"
    assert sambo.arms[1].arm_label == "Version B"
    assert sambo.arms[0].summary is not None
    assert sambo.arms[1].summary is not None


def test_render_audience_ab_shows_side_by_side_arms():
    bundle_a, bundle_b = _ab_bundles()
    clf_a = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=[
            "Bra förslag om trygg belysning.",
            "Vem ska betala? Finansieringen är oklar.",
        ],
        tone_pmfs=[_tone_pmf(0.8, neg=0.05), _tone_pmf(0.1, neg=0.6)],
        sample_user_ids=[1, 2],
    )
    clf_b = BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=[
            "Bra förslag om trygg belysning.",
            "Vem ska betala? Finansieringen är oklar.",
        ],
        tone_pmfs=[_tone_pmf(0.2, neg=0.5), _tone_pmf(0.75, neg=0.1)],
        sample_user_ids=[1, 2],
    )
    html = render_audience_section([bundle_a, bundle_b], [clf_a, clf_b], locale="sv")
    assert "aud-compare" in html
    assert "aud-arm-grid" in html
    assert "aud-ab-diff" in html
    assert "aud-ab-legend" in html
    assert "Version A" in html
    assert "Version B" in html
    assert html.count("aud-bundle-title") == 0


def test_segment_diff_summary_includes_engagement_and_critical_tone():
    tone_a = SegmentToneRow(
        dimension="livssituation",
        label="Sambo, barn",
        text_count=2,
        agent_count=1,
        positive_share=0.5,
        critical_share=0.1,
        engagement_score=12,
        too_few=False,
    )
    tone_b = SegmentToneRow(
        dimension="livssituation",
        label="Sambo, barn",
        text_count=2,
        agent_count=1,
        positive_share=0.3,
        critical_share=0.35,
        engagement_score=4,
        too_few=False,
    )
    arms = [
        SegmentArmSummary(
            arm_label="Version A",
            summary=AudienceSegmentSummary(
                dimension="livssituation",
                dimension_label="Livssituation",
                label="Sambo, barn",
                tone=tone_a,
            ),
        ),
        SegmentArmSummary(
            arm_label="Version B",
            summary=AudienceSegmentSummary(
                dimension="livssituation",
                dimension_label="Livssituation",
                label="Sambo, barn",
                tone=tone_b,
            ),
        ),
    ]
    diff = build_segment_diff_summary(arms, locale="sv")
    assert "50% positiv" in diff
    assert "10% kritisk" in diff
    assert "engagemang 12" in diff
    assert "35% kritisk" in diff
    assert "engagemang 4" in diff
    assert "mer kritisk" in diff
    assert "högre engagemang" in diff
