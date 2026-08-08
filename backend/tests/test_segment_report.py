"""Tests for bio-segment SSR, audience analysis, and rule-based recommendation."""

from __future__ import annotations

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, TopicPack
from app.services.report.metrics import compute_report_metrics
from app.services.report.recommendation import build_recommendation
from app.services.report.segment_analysis import build_audience_summaries, detect_themes
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
                "bio": {"livssituation": "Ensamhushåll", "ort": "Hageby", "lutning": "Höger"},
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
