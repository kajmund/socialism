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
