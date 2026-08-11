"""Report threshold configuration and validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.report.recommendation import build_recommendation
from app.services.report.thresholds import (
    ReportThresholds,
    default_report_thresholds,
    normalize_report_thresholds,
    report_thresholds_to_dict,
)


def test_default_thresholds_match_legacy_constants():
    t = default_report_thresholds()
    assert t.verdict.pos_strong == 0.50
    assert t.verdict.pos_mixed == 0.30
    assert t.verdict.crit_weak == 0.50
    assert t.diff.clear == 0.08
    assert t.diff.weak == 0.03
    assert t.topic_drift == 0.10
    assert t.recommendation.score_triggers.strong_pos == 0.45
    assert t.recommendation.action_bands.ready == 75


def test_verdict_and_recommendation_strong_pos_differ_by_design():
    t = default_report_thresholds()
    assert t.verdict.pos_strong == 0.50
    assert t.recommendation.score_triggers.strong_pos == 0.45


def test_invalid_verdict_order_rejected():
    with pytest.raises(ValidationError):
        ReportThresholds.model_validate(
            {
                "verdict": {"pos_strong": 0.30, "pos_mixed": 0.50, "crit_weak": 0.50},
            }
        )


def test_invalid_diff_order_rejected():
    with pytest.raises(ValidationError):
        ReportThresholds.model_validate({"diff": {"clear": 0.03, "weak": 0.08}})


def test_invalid_action_bands_rejected():
    with pytest.raises(ValidationError):
        ReportThresholds.model_validate(
            {"recommendation": {"action_bands": {"ready": 55, "minor_adjust": 75, "revise": 35}}}
        )


def test_normalize_empty_returns_defaults():
    t = normalize_report_thresholds({})
    assert t.verdict.pos_strong == 0.50


def test_round_trip_dict():
    original = default_report_thresholds()
    restored = normalize_report_thresholds(report_thresholds_to_dict(original))
    assert restored == original


def test_custom_thresholds_change_recommendation_action():
    from app.services.report.bundles import RunBundle
    from app.services.report.classify import BundleClassification, TopicPack
    from app.services.report.metrics import compute_report_metrics

    bundle = RunBundle(
        label="A",
        run_id=1,
        run_name="T",
        attempt_id="a1",
        seed="1",
        engine="none",
        agents=[{"index": 1, "member_name": "Anna", "role": "population"}],
        posts=[{"post_id": 1, "user_id": 1, "content": "Hej", "num_likes": 5}],
        comments=[],
        ticks_run=1,
        injection_texts=["Hej"],
    )
    clf = BundleClassification(
        topic_packs=[TopicPack(label="T", keywords=["hej"])],
        topic_shares={"T": 1.0},
        tone_shares={
            "Starkt positiv": 0.5,
            "Något positiv": 0.2,
            "Neutral": 0.3,
            "Något negativ": 0.0,
            "Starkt negativ": 0.0,
        },
        tone_mode="ssr",
    )
    metrics = compute_report_metrics([bundle], [clf])
    strict = default_report_thresholds().model_copy(
        update={
            "recommendation": default_report_thresholds().recommendation.model_copy(
                update={
                    "action_bands": default_report_thresholds()
                    .recommendation.action_bands.model_copy(update={"ready": 60})
                }
            )
        }
    )
    rec_default = build_recommendation(
        metrics, [bundle], [clf], [], locale="sv", thresholds=default_report_thresholds()
    )
    rec_loose = build_recommendation(
        metrics, [bundle], [clf], [], locale="sv", thresholds=strict
    )
    assert rec_default.action == "Publicera efter mindre justeringar"
    assert rec_loose.action == "Redo att publicera"


def test_build_audience_comparisons_uses_configured_diff_clear():
    from app.services.report.segment_analysis import (
        AudienceSegmentSummary,
        SegmentArmSummary,
        SegmentToneRow,
        build_audience_comparisons,
        build_segment_diff_summary,
    )

    tone_a = SegmentToneRow(
        dimension="livssituation",
        label="Sambo, barn",
        text_count=2,
        agent_count=1,
        positive_share=0.35,
        critical_share=0.1,
        engagement_score=12,
        too_few=False,
    )
    tone_b = SegmentToneRow(
        dimension="livssituation",
        label="Sambo, barn",
        text_count=2,
        agent_count=1,
        positive_share=0.30,
        critical_share=0.1,
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
    default_diff = build_segment_diff_summary(arms, locale="sv")
    assert "nära varandra" in default_diff
    assert "leder" not in default_diff

    loose_diff = build_segment_diff_summary(arms, locale="sv", diff_clear=0.04)
    assert "leder" in loose_diff
