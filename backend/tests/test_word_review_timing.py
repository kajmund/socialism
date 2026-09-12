"""Word-review timing collector and job-level LLM limiter."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.services.expertgranskning import word_review
from app.services.expertgranskning.word_review_timing import (
    TIMING_CATEGORIES,
    WordReviewLimiter,
    WordReviewTimings,
)


def test_timing_snapshot_has_safe_aggregate_fields_only():
    timings = WordReviewTimings()
    started = timings.begin_call()
    timings.end_call("moderation", started)
    timings.mark_first_action()
    snapshot = timings.snapshot()
    assert set(snapshot) == {
        "total_ms",
        "time_to_first_action_ms",
        "moderation_ms",
        "raise_hand_ms",
        "expert_comment_ms",
        "rewrite_convergence_ms",
        "comment_convergence_ms",
        "heading_ms",
        "moderation_calls",
        "raise_hand_calls",
        "expert_comment_calls",
        "rewrite_convergence_calls",
        "comment_convergence_calls",
        "heading_calls",
        "llm_call_count",
        "structured_retry_count",
        "max_observed_llm_concurrency",
    }
    dumped = repr(snapshot)
    assert "prompt" not in dumped
    assert "document" not in dumped
    assert snapshot["llm_call_count"] == 1
    assert snapshot["structured_retry_count"] == 0
    assert snapshot["moderation_calls"] == 0
    assert snapshot["moderation_ms"] >= 0
    assert snapshot["time_to_first_action_ms"] is not None
    assert snapshot["time_to_first_action_ms"] >= 0


def test_timing_snapshot_omits_first_action_until_marked():
    timings = WordReviewTimings()
    assert timings.snapshot()["time_to_first_action_ms"] is None
    timings.mark_first_action()
    first = timings.snapshot()["time_to_first_action_ms"]
    timings.mark_first_action()
    assert timings.snapshot()["time_to_first_action_ms"] == first


@pytest.mark.asyncio
async def test_first_action_timing_excludes_later_section_publish_delay(monkeypatch):
    """Fails if first-action is stamped only after the whole publish loop."""
    later_publish_delay_s = 0.15
    seen = 0

    async def delayed_publish(_row) -> None:
        nonlocal seen
        if seen:
            await asyncio.sleep(later_publish_delay_s)
        seen += 1

    monkeypatch.setattr(word_review, "publish_action_created", delayed_publish)
    timings = WordReviewTimings()
    actions = [
        SimpleNamespace(id="wa_1"),
        SimpleNamespace(id="wa_2"),
        SimpleNamespace(id="wa_3"),
    ]
    started = time.monotonic()
    published = await word_review.publish_created_actions(actions, timings)
    elapsed_ms = (time.monotonic() - started) * 1000
    first_ms = timings.snapshot()["time_to_first_action_ms"]
    assert published == 3
    assert first_ms is not None
    assert first_ms < later_publish_delay_s * 1000
    assert elapsed_ms >= later_publish_delay_s * 2 * 1000


@pytest.mark.asyncio
async def test_limiter_bounds_observed_llm_concurrency():
    timings = WordReviewTimings()
    limiter = WordReviewLimiter(2, timings)
    current = 0
    observed = 0

    async def one_call() -> None:
        nonlocal current, observed

        async def factory() -> str:
            nonlocal current, observed
            current += 1
            observed = max(observed, current)
            await asyncio.sleep(0.05)
            current -= 1
            return "ok"

        assert await limiter.run("moderation", factory) == "ok"

    await asyncio.gather(*[one_call() for _ in range(6)])
    assert observed == 2
    assert timings.max_observed_llm_concurrency == 2
    assert timings.llm_call_count == 6
    assert timings.snapshot()["moderation_calls"] == 6
    assert timings.snapshot()["structured_retry_count"] == 0
    assert timings.snapshot()["moderation_ms"] >= 40


@pytest.mark.asyncio
async def test_limiter_rejects_unknown_category():
    limiter = WordReviewLimiter(1, WordReviewTimings())

    async def factory() -> None:
        return None

    with pytest.raises(ValueError, match="unknown Word review timing category"):
        await limiter.run("not-a-phase", factory)
    assert set(TIMING_CATEGORIES) == {
        "moderation",
        "raise_hand",
        "expert_comment",
        "rewrite_convergence",
        "comment_convergence",
        "heading",
    }
