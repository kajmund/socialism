"""Job-level Word-review LLM limiter, call counts, and aggregate timings.

Records durations, category counts, retries, and concurrency only.
Never stores prompt or document text.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

TIMING_CATEGORIES = (
    "moderation",
    "raise_hand",
    "expert_comment",
    "rewrite_convergence",
    "comment_convergence",
    "heading",
)


class WordReviewTimings:
    def __init__(self) -> None:
        self._started_at = time.monotonic()
        self._first_action_at: float | None = None
        self._totals_ms = {name: 0.0 for name in TIMING_CATEGORIES}
        self._calls = {name: 0 for name in TIMING_CATEGORIES}
        self.llm_call_count = 0
        self.structured_retry_count = 0
        self.max_observed_llm_concurrency = 0
        self.direct_routed_questions = 0
        self.raise_hand_questions = 0
        self.questions_dropped_invalid_anchor = 0
        self._in_flight = 0

    def mark_first_action(self) -> None:
        if self._first_action_at is None:
            self._first_action_at = time.monotonic()

    def record_category(self, category: str) -> None:
        self._calls[category] += 1

    def record_structured_retry(self) -> None:
        self.structured_retry_count += 1
        self.llm_call_count += 1

    def record_direct_routed_questions(self, count: int) -> None:
        self.direct_routed_questions += count

    def record_raise_hand_questions(self, count: int) -> None:
        self.raise_hand_questions += count

    def record_dropped_invalid_anchor(self, count: int = 1) -> None:
        self.questions_dropped_invalid_anchor += count

    def begin_call(self) -> float:
        self._in_flight += 1
        self.llm_call_count += 1
        if self._in_flight > self.max_observed_llm_concurrency:
            self.max_observed_llm_concurrency = self._in_flight
        return time.monotonic()

    def end_call(self, category: str, started_at: float) -> None:
        self._in_flight -= 1
        self._totals_ms[category] += (time.monotonic() - started_at) * 1000

    def snapshot(self) -> dict[str, int | None]:
        now = time.monotonic()
        first_action_ms = (
            round((self._first_action_at - self._started_at) * 1000)
            if self._first_action_at is not None
            else None
        )
        return {
            "total_ms": round((now - self._started_at) * 1000),
            "time_to_first_action_ms": first_action_ms,
            "moderation_ms": round(self._totals_ms["moderation"]),
            "raise_hand_ms": round(self._totals_ms["raise_hand"]),
            "expert_comment_ms": round(self._totals_ms["expert_comment"]),
            "rewrite_convergence_ms": round(self._totals_ms["rewrite_convergence"]),
            "comment_convergence_ms": round(self._totals_ms["comment_convergence"]),
            "heading_ms": round(self._totals_ms["heading"]),
            "moderation_calls": self._calls["moderation"],
            "raise_hand_calls": self._calls["raise_hand"],
            "expert_comment_calls": self._calls["expert_comment"],
            "rewrite_convergence_calls": self._calls["rewrite_convergence"],
            "comment_convergence_calls": self._calls["comment_convergence"],
            "heading_calls": self._calls["heading"],
            "direct_routed_questions": self.direct_routed_questions,
            "raise_hand_questions": self.raise_hand_questions,
            "questions_dropped_invalid_anchor": self.questions_dropped_invalid_anchor,
            "llm_call_count": self.llm_call_count,
            "structured_retry_count": self.structured_retry_count,
            "max_observed_llm_concurrency": self.max_observed_llm_concurrency,
        }


class WordReviewLimiter:
    """Bounds in-flight Word-review LLM calls for one job."""

    def __init__(self, max_concurrency: int, timings: WordReviewTimings) -> None:
        if max_concurrency < 1:
            raise ValueError("WORD_REVIEW_MAX_CONCURRENCY must be >= 1")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self.timings = timings

    async def run(
        self,
        category: str,
        factory: Callable[[], Awaitable[T]],
    ) -> T:
        if category not in TIMING_CATEGORIES:
            raise ValueError(f"unknown Word review timing category: {category}")
        async with self._semaphore:
            self.timings.record_category(category)
            started_at = self.timings.begin_call()
            try:
                return await factory()
            finally:
                self.timings.end_call(category, started_at)
