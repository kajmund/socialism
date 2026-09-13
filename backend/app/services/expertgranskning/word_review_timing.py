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
    "router",
    "raise_hand",
    "expert_comment",
    "rewrite_convergence",
    "comment_convergence",
    "heading",
    "actor_context",
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
        self.router_assignments = 0
        self.router_fallback_count = 0
        self.invalid_router_ids = 0
        self.actor_context_resolved = 0
        self.publication_units_completed = 0
        self.actions_published_before_completion = 0
        self.comments_generated = 0
        self.comments_over_soft_length = 0
        self.observations_split = 0
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

    def record_router_assignments(self, count: int) -> None:
        self.router_assignments += count

    def record_router_fallback(self, count: int = 1) -> None:
        self.router_fallback_count += count

    def record_invalid_router_ids(self, count: int) -> None:
        self.invalid_router_ids += count

    def record_actor_context_resolved(self, resolved: bool) -> None:
        self.actor_context_resolved = 1 if resolved else 0

    def record_comment_generated(self, *, over_soft_length: bool) -> None:
        self.comments_generated += 1
        if over_soft_length:
            self.comments_over_soft_length += 1

    def record_observations_split(self, count: int) -> None:
        if count > 1:
            self.observations_split += 1

    def record_publication_progress(
        self,
        *,
        units_completed: int,
        units_total: int,
        actions_created: int,
    ) -> None:
        self.publication_units_completed = units_completed
        if units_completed < units_total:
            self.actions_published_before_completion = actions_created

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
            "router_ms": round(self._totals_ms["router"]),
            "raise_hand_ms": round(self._totals_ms["raise_hand"]),
            "expert_comment_ms": round(self._totals_ms["expert_comment"]),
            "rewrite_convergence_ms": round(self._totals_ms["rewrite_convergence"]),
            "comment_convergence_ms": round(self._totals_ms["comment_convergence"]),
            "heading_ms": round(self._totals_ms["heading"]),
            "actor_context_ms": round(self._totals_ms["actor_context"]),
            "moderation_calls": self._calls["moderation"],
            "router_calls": self._calls["router"],
            "raise_hand_calls": self._calls["raise_hand"],
            "expert_comment_calls": self._calls["expert_comment"],
            "rewrite_convergence_calls": self._calls["rewrite_convergence"],
            "comment_convergence_calls": self._calls["comment_convergence"],
            "heading_calls": self._calls["heading"],
            "actor_context_resolver_calls": self._calls["actor_context"],
            "actor_context_resolved": self.actor_context_resolved,
            "direct_routed_questions": self.direct_routed_questions,
            "raise_hand_questions": self.raise_hand_questions,
            "questions_dropped_invalid_anchor": self.questions_dropped_invalid_anchor,
            "router_assignments": self.router_assignments,
            "router_fallback_count": self.router_fallback_count,
            "invalid_router_ids": self.invalid_router_ids,
            "publication_units_completed": self.publication_units_completed,
            "actions_published_before_completion": (
                self.actions_published_before_completion
            ),
            "comments_generated": self.comments_generated,
            "comments_over_soft_length": self.comments_over_soft_length,
            "observations_split": self.observations_split,
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
