"""Tests for tick-by-tick stats and interview Q&A extraction."""

from __future__ import annotations

from app.services.report.bundles import RunBundle
from app.services.report.charts import render_interview_qa_section, render_tick_timeline
from app.services.report.tick_report import build_tick_stats, extract_interview_qa
from app.services.run_measurements import build_measurements
from app.schemas.domain import Tick


def _bundle_with_ticks() -> RunBundle:
    ticks = [
        Tick(key="d1", day=1, measurements=["opinion_snapshot"]),
        Tick(
            key="d2",
            day=2,
            measurements=["engagement_decay"],
            interviews=[
                {"key": "iv1", "persona_id": "p1", "prompt": "Hur påverkade budskapet dig?"},
            ],
        ),
    ]
    posts = [
        {"post_id": 1, "user_id": 1, "content": "Bra", "num_likes": 4, "created_at": 1},
        {"post_id": 2, "user_id": 2, "content": "Mer", "num_likes": 2, "created_at": 5},
    ]
    comments = [
        {"comment_id": 1, "post_id": 1, "user_id": 2, "content": "Håller med", "num_likes": 1, "created_at": 2},
    ]
    markers = [
        {"tick_index": 0, "day": 1, "silent": False, "key": "d1", "rounds": 2, "time_start": 0, "time_end": 3},
        {"tick_index": 1, "day": 2, "silent": False, "key": "d2", "rounds": 2, "time_start": 4, "time_end": 8},
    ]
    measurements = build_measurements(
        ticks,
        posts=posts,
        comments=comments,
        agents=[{"index": 1, "member_name": "Anna", "persona_id": "p1", "role": "population"}],
        follows=[],
        ticks_run=2,
    )
    return RunBundle(
        label="Test",
        run_id=1,
        run_name="T",
        attempt_id="a1",
        seed="1",
        engine="oasis",
        agents=[{"index": 1, "member_name": "Anna", "persona_id": "p1", "role": "population"}],
        posts=posts,
        comments=comments,
        measurements=measurements,
        tick_markers=markers,
        trace=[
            {
                "user_id": 1,
                "created_at": 6,
                "action": "interview",
                "info": '{"prompt": "Hur påverkade budskapet dig?", "response": "Det känns hoppfullt."}',
            }
        ],
        ticks_run=2,
    )


def test_build_tick_stats_window_and_cumulative():
    rows = build_tick_stats(_bundle_with_ticks())
    assert len(rows) == 2
    assert rows[0].window_posts == 1
    assert rows[1].window_posts == 1
    assert rows[1].cumulative_posts == 2
    assert rows[0].measurement_points
    assert rows[0].measurement_points[0]["id"] == "opinion_snapshot"


def test_extract_interview_qa_from_trace():
    qa = extract_interview_qa(_bundle_with_ticks())
    assert len(qa) == 1
    assert qa[0].agent_name == "Anna"
    assert "Hur påverkade" in qa[0].question
    assert "hoppfullt" in qa[0].answer
    assert qa[0].tick_index == 1
    assert qa[0].day == 2


def test_render_tick_and_qa_html():
    bundle = _bundle_with_ticks()
    tick_html = render_tick_timeline([bundle], locale="sv")
    qa_html = render_interview_qa_section([bundle], locale="sv")
    assert "tick-timeline" in tick_html
    assert "Tick 1" in tick_html
    assert "qa-section" in qa_html
    assert "Frågor konfigurerade" in qa_html or "F:" in qa_html
