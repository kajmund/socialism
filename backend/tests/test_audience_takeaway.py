"""Tests for rule-based audience takeaway paragraphs."""

from __future__ import annotations

from app.services.report.audience_takeaway import (
    build_audience_takeaways,
    build_bundle_takeaway,
)
from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, TopicPack
from app.services.ssr.anchors import TONE_LABELS_SV


def _tone_pmf(pos: float, neu: float = 0.2, neg: float = 0.2) -> dict[str, float]:
    return {
        "Starkt negativ": neg * 0.5,
        "Något negativ": neg * 0.5,
        "Neutral": neu,
        "Något positiv": pos * 0.5,
        "Starkt positiv": pos * 0.5,
    }


def _bundle() -> RunBundle:
    return RunBundle(
        label="Demo — belysning A/B — Version A",
        variant_id="a",
        run_id=1,
        run_name="T",
        attempt_id="a1",
        seed="1",
        engine="oasis",
        agents=[
            {"index": 1, "persona_id": "p1", "member_name": "Anna", "role": "population"},
            {"index": 2, "persona_id": "p2", "member_name": "Bo", "role": "population"},
            {"index": 3, "persona_id": "p3", "member_name": "Eva", "role": "population"},
        ],
        personas=[
            {
                "persona_id": "p1",
                "name": "Anna",
                "bio": {
                    "livssituation": "Sambo, barn",
                    "kön": "Kvinna",
                    "yrke": "Grundskollärare",
                    "age": "38",
                },
            },
            {
                "persona_id": "p2",
                "name": "Bo",
                "bio": {
                    "livssituation": "Ensamhushåll",
                    "kön": "Man",
                    "yrke": "Elektriker",
                    "age": "52",
                },
            },
            {
                "persona_id": "p3",
                "name": "Eva",
                "bio": {
                    "livssituation": "Sambo, barn",
                    "kön": "Kvinna",
                    "yrke": "Undersköterska",
                    "age": "44",
                },
            },
        ],
        posts=[
            {"post_id": 1, "user_id": 1, "content": "Bra förslag", "num_likes": 4},
            {"post_id": 2, "user_id": 3, "content": "Tryggt för barnfamiljer", "num_likes": 3},
            {"post_id": 3, "user_id": 2, "content": "Vem betalar?", "num_likes": 1},
            {"post_id": 4, "user_id": 2, "content": "Skeptisk till finansiering", "num_likes": 0},
        ],
        comments=[],
        injection_texts=["Belysning"],
    )


def _classification() -> BundleClassification:
    return BundleClassification(
        topic_packs=[TopicPack(label="Belysning", keywords=["belysning"])],
        topic_shares={"Belysning": 1.0},
        tone_shares={lab: 0.2 for lab in TONE_LABELS_SV},
        tone_mode="ssr",
        tone_rated_texts=[
            "Bra förslag",
            "Tryggt för barnfamiljer",
            "Vem betalar?",
            "Skeptisk till finansiering",
        ],
        tone_pmfs=[
            _tone_pmf(0.75),
            _tone_pmf(0.72),
            _tone_pmf(0.12, neg=0.6),
            _tone_pmf(0.08, neg=0.7),
        ],
        sample_user_ids=[1, 3, 2, 2],
    )


def test_build_bundle_takeaway_mentions_worst_and_best_segments():
    bundle = _bundle()
    clf = _classification()
    text = build_bundle_takeaway(bundle, clf, locale="sv")
    assert text is not None
    assert "ensamhushåll" in text.casefold()
    assert "sambo, barn" in text.casefold() or "undersköterska" in text.casefold()
    assert "positiv ton" in text.casefold()


def test_build_audience_takeaways_includes_gender_gap():
    bundle = _bundle()
    clf = _classification()
    lines = build_audience_takeaways([bundle], [clf], locale="sv")
    assert any("kvinnor" in line.casefold() for line in lines)
    assert any("män" in line.casefold() for line in lines)


def test_build_bundle_takeaway_respects_configured_takeaway_thresholds():
    from app.services.report.thresholds import ReportThresholds

    bundle = _bundle()
    clf = _classification()
    strict = ReportThresholds.model_validate(
        {
            "takeaway": {
                "positive_strong": 0.95,
                "positive_weak": 0.05,
                "critical_high": 0.99,
                "segment_contrast_gap": 0.50,
            },
        }
    )
    assert build_bundle_takeaway(bundle, clf, locale="sv", thresholds=strict) is None

    loose = ReportThresholds.model_validate(
        {
            "takeaway": {
                "positive_strong": 0.10,
                "positive_weak": 0.05,
                "critical_high": 0.99,
                "segment_contrast_gap": 0.01,
            },
        }
    )
    text = build_bundle_takeaway(bundle, clf, locale="sv", thresholds=loose)
    assert text is not None
    assert "landade bättre" in text.casefold()
    assert "positiv ton" in text.casefold()


def test_gender_sentence_uses_diff_clear_not_takeaway():
    from app.services.report.audience_takeaway import _gender_sentence
    from app.services.report.segment_ssr import SegmentToneRow
    from app.services.report.thresholds import ReportThresholds

    rows = [
        SegmentToneRow(
            dimension="kön",
            label="Kvinna",
            text_count=2,
            agent_count=1,
            positive_share=0.50,
            critical_share=0.10,
            engagement_score=3,
            too_few=False,
            agent_ids=frozenset({1}),
        ),
        SegmentToneRow(
            dimension="kön",
            label="Man",
            text_count=2,
            agent_count=1,
            positive_share=0.44,
            critical_share=0.10,
            engagement_score=2,
            too_few=False,
            agent_ids=frozenset({2}),
        ),
    ]
    narrow = ReportThresholds.model_validate({"diff": {"clear": 0.10, "weak": 0.03}})
    wide = ReportThresholds.model_validate({"diff": {"clear": 0.04, "weak": 0.03}})

    similar = _gender_sentence(rows, locale="sv", gender_gap=narrow.diff.clear)
    assert similar is not None
    assert "liknande" in similar.casefold()
    directional = _gender_sentence(rows, locale="sv", gender_gap=wide.diff.clear)
    assert directional is not None
    assert "liknande" not in directional.casefold()
    assert "kvinnor" in directional.casefold()
