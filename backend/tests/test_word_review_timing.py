"""Word-review timing collector and job-level LLM limiter."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.llm import LLMCallStats, complete_structured, set_structured_completer
from app.services.expertgranskning import word_review
from app.services.expertgranskning.word_review import log_word_review_call_summary
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
        "router_ms",
        "raise_hand_ms",
        "expert_comment_ms",
        "rewrite_convergence_ms",
        "comment_convergence_ms",
        "heading_ms",
        "actor_context_ms",
        "moderation_calls",
        "router_calls",
        "raise_hand_calls",
        "expert_comment_calls",
        "rewrite_convergence_calls",
        "comment_convergence_calls",
        "heading_calls",
        "actor_context_resolver_calls",
        "actor_context_resolved",
        "direct_routed_questions",
        "raise_hand_questions",
        "questions_dropped_invalid_anchor",
        "router_assignments",
        "router_fallback_count",
        "invalid_router_ids",
        "publication_units_completed",
        "actions_published_before_completion",
        "comments_generated",
        "comments_over_soft_length",
        "observations_split",
        "llm_provider",
        "llm_model",
        "llm_reasoning_effort",
        "prompt_tokens",
        "completion_tokens",
        "llm_usage",
        "llm_call_count",
        "structured_retry_count",
        "max_observed_llm_concurrency",
    }
    assert snapshot["llm_provider"] == "cerebras"
    assert snapshot["llm_model"] == "gpt-oss-120b"
    assert snapshot["llm_reasoning_effort"] == "medium"
    assert snapshot["prompt_tokens"] == 0
    assert snapshot["completion_tokens"] == 0
    assert snapshot["llm_usage"] == []
    dumped = repr(snapshot).replace("'prompt_tokens'", "").replace('"prompt_tokens"', "")
    assert "prompt" not in dumped
    assert "document" not in dumped
    assert snapshot["llm_call_count"] == 1
    assert snapshot["structured_retry_count"] == 0
    assert snapshot["moderation_calls"] == 0
    assert snapshot["direct_routed_questions"] == 0
    assert snapshot["raise_hand_questions"] == 0
    assert snapshot["questions_dropped_invalid_anchor"] == 0
    assert snapshot["moderation_ms"] >= 0
    assert snapshot["time_to_first_action_ms"] is not None
    assert snapshot["time_to_first_action_ms"] >= 0


def test_llm_call_summary_logs_counts_without_document_text(monkeypatch):
    messages: list[str] = []

    def capture(fmt: str, *args: object) -> None:
        messages.append(fmt % args if args else fmt)

    monkeypatch.setattr(word_review.logger, "info", capture)
    timings = WordReviewTimings()
    started = timings.begin_call()
    timings.record_category("comment_convergence")
    timings.record_structured_retry()
    timings.end_call("comment_convergence", started)
    log_word_review_call_summary(
        "job_secret", timings.snapshot(), outcome="failed"
    )
    assert len([item for item in messages if "Word review LLM calls" in item]) == 1
    assert len([item for item in messages if "Word review timings" in item]) == 1
    logged = " ".join(messages)
    assert "job_id=job_secret" in logged
    assert "outcome=failed" in logged
    assert "structured_retries=1" in logged
    assert "comment_convergence=1" in logged
    assert "direct_routed_questions=0" in logged
    assert "raise_hand_questions=0" in logged
    assert "router=0" in logged
    assert "router_fallback_count=0" in logged
    assert "invalid_router_ids=0" in logged
    assert "questions_dropped_invalid_anchor=0" in logged
    assert "max_observed_llm_concurrency=" in logged
    assert "provider=cerebras" in logged
    assert "model=gpt-oss-120b" in logged
    assert "reasoning_effort=medium" in logged
    assert "prompt_tokens=0" in logged
    assert "completion_tokens=0" in logged
    assert "llm_usage=" in logged
    assert "prompt " not in logged.replace("prompt_tokens", "")
    assert "document" not in logged
    assert "kommentar" not in logged


def test_publication_progress_records_actions_before_final_unit():
    timings = WordReviewTimings()
    timings.record_publication_progress(
        units_completed=1, units_total=3, actions_created=2
    )
    timings.record_publication_progress(
        units_completed=2, units_total=3, actions_created=5
    )
    timings.record_publication_progress(
        units_completed=3, units_total=3, actions_created=6
    )
    snapshot = timings.snapshot()
    assert snapshot["publication_units_completed"] == 3
    assert snapshot["actions_published_before_completion"] == 5


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
async def test_limiter_records_provider_token_stats(monkeypatch):
    from app.services.expertgranskning.schemas import WordCommentConvergence

    set_structured_completer(None)

    async def fake_create(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"issues":[]}'))
            ],
            usage=SimpleNamespace(prompt_tokens=21, completion_tokens=9),
        )

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    timings = WordReviewTimings()
    limiter = WordReviewLimiter(1, timings)
    parsed = await limiter.run(
        "router",
        lambda: complete_structured(
            [{"role": "user", "content": "group"}],
            WordCommentConvergence,
        ),
    )
    assert parsed.issues == []
    snapshot = timings.snapshot()
    assert snapshot["llm_provider"] == "cerebras"
    assert snapshot["llm_model"] == "gpt-oss-120b"
    assert snapshot["llm_reasoning_effort"] == "medium"
    assert snapshot["prompt_tokens"] == 21
    assert snapshot["completion_tokens"] == 9
    assert snapshot["llm_usage"] == [
        {
            "provider": "cerebras",
            "model": "gpt-oss-120b",
            "reasoning_effort": "medium",
            "prompt_tokens": 21,
            "completion_tokens": 9,
            "calls": 1,
        }
    ]


def test_mixed_model_usage_is_reported_per_model_not_last_call():
    timings = WordReviewTimings()
    timings.record_llm_stats(
        LLMCallStats(
            provider="cerebras",
            model="gpt-oss-120b",
            reasoning_effort="medium",
            prompt_tokens=100,
            completion_tokens=40,
            elapsed_ms=12.0,
            kind="structured",
        )
    )
    timings.record_llm_stats(
        LLMCallStats(
            provider="cerebras",
            model="deepseek-chat",
            reasoning_effort=None,
            prompt_tokens=20,
            completion_tokens=5,
            elapsed_ms=3.0,
            kind="structured",
        )
    )
    snapshot = timings.snapshot()
    assert snapshot["llm_provider"] == "cerebras"
    assert snapshot["llm_model"] == "mixed"
    assert snapshot["llm_reasoning_effort"] == "mixed"
    assert snapshot["prompt_tokens"] == 120
    assert snapshot["completion_tokens"] == 45
    assert snapshot["llm_usage"] == [
        {
            "provider": "cerebras",
            "model": "deepseek-chat",
            "reasoning_effort": None,
            "prompt_tokens": 20,
            "completion_tokens": 5,
            "calls": 1,
        },
        {
            "provider": "cerebras",
            "model": "gpt-oss-120b",
            "reasoning_effort": "medium",
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "calls": 1,
        },
    ]


def test_mixed_model_usage_is_stable_regardless_of_call_order():
    first = WordReviewTimings()
    second = WordReviewTimings()
    global_call = LLMCallStats(
        provider="cerebras",
        model="gpt-oss-120b",
        reasoning_effort="medium",
        prompt_tokens=80,
        completion_tokens=30,
        elapsed_ms=8.0,
        kind="structured",
    )
    router_call = LLMCallStats(
        provider="cerebras",
        model="deepseek-chat",
        reasoning_effort=None,
        prompt_tokens=10,
        completion_tokens=4,
        elapsed_ms=2.0,
        kind="structured",
    )
    first.record_llm_stats(global_call)
    first.record_llm_stats(router_call)
    second.record_llm_stats(router_call)
    second.record_llm_stats(global_call)
    assert first.snapshot()["llm_usage"] == second.snapshot()["llm_usage"]
    assert first.snapshot()["llm_model"] == "mixed"
    assert second.snapshot()["llm_model"] == "mixed"


def test_same_model_usage_accumulates_in_one_bucket():
    timings = WordReviewTimings()
    stats = LLMCallStats(
        provider="cerebras",
        model="gpt-oss-120b",
        reasoning_effort="medium",
        prompt_tokens=11,
        completion_tokens=7,
        elapsed_ms=5.0,
        kind="structured",
    )
    timings.record_llm_stats(stats)
    timings.record_llm_stats(stats)
    snapshot = timings.snapshot()
    assert snapshot["llm_model"] == "gpt-oss-120b"
    assert snapshot["prompt_tokens"] == 22
    assert snapshot["completion_tokens"] == 14
    assert snapshot["llm_usage"] == [
        {
            "provider": "cerebras",
            "model": "gpt-oss-120b",
            "reasoning_effort": "medium",
            "prompt_tokens": 22,
            "completion_tokens": 14,
            "calls": 2,
        }
    ]


def test_mixed_model_summary_logs_per_model_usage(monkeypatch):
    messages: list[str] = []

    def capture(fmt: str, *args: object) -> None:
        messages.append(fmt % args if args else fmt)

    monkeypatch.setattr(word_review.logger, "info", capture)
    timings = WordReviewTimings()
    timings.record_llm_stats(
        LLMCallStats(
            provider="cerebras",
            model="gpt-oss-120b",
            reasoning_effort="medium",
            prompt_tokens=100,
            completion_tokens=40,
            elapsed_ms=12.0,
            kind="structured",
        )
    )
    timings.record_llm_stats(
        LLMCallStats(
            provider="cerebras",
            model="deepseek-chat",
            reasoning_effort=None,
            prompt_tokens=20,
            completion_tokens=5,
            elapsed_ms=3.0,
            kind="structured",
        )
    )
    log_word_review_call_summary("job_secret", timings.snapshot(), outcome="ok")
    logged = " ".join(messages)
    assert "model=mixed" in logged
    assert "prompt_tokens=120" in logged
    assert "completion_tokens=45" in logged
    assert "cerebras/gpt-oss-120b/medium:in=100:out=40:calls=1" in logged
    assert "cerebras/deepseek-chat/:in=20:out=5:calls=1" in logged
    assert "model=deepseek-chat" not in logged
    assert "document" not in logged


@pytest.mark.asyncio
async def test_limiter_rejects_unknown_category():
    limiter = WordReviewLimiter(1, WordReviewTimings())

    async def factory() -> None:
        return None

    with pytest.raises(ValueError, match="unknown Word review timing category"):
        await limiter.run("not-a-phase", factory)
    assert set(TIMING_CATEGORIES) == {
        "moderation",
        "router",
        "raise_hand",
        "expert_comment",
        "rewrite_convergence",
        "comment_convergence",
        "heading",
        "actor_context",
    }
