"""Tests for anchor validation warnings in snabbrapport."""

from __future__ import annotations

from app.services.report.quick import build_anchor_validation_html


def test_validation_html_empty_when_ok():
    html = build_anchor_validation_html(
        {
            "tone": {"validation_status": "ok", "name": "tone_sv"},
            "style": {"validation_status": "ok", "name": "style_sv"},
        },
        locale="sv",
    )
    assert html == ""


def test_validation_html_warns_on_stale():
    html = build_anchor_validation_html(
        {
            "tone": {
                "validation_status": "stale",
                "name": "tone_sv",
                "accuracy": 0.7,
            },
            "style": {"validation_status": "ok", "name": "style_sv"},
        },
        locale="sv",
    )
    assert "ssr-validation-warning" in html
    assert "inaktuella" in html
    assert "tone_sv" in html


def test_validation_html_warns_untested_en():
    html = build_anchor_validation_html(
        {
            "tone": {"validation_status": "untested", "name": "tone_en"},
            "style": {"validation_status": "untested", "name": "style_en"},
        },
        locale="en",
    )
    assert "SSR anchor validation warning" in html
    assert "not been calibration-tested" in html
