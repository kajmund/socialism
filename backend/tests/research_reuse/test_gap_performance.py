import asyncio
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.services.lagen_nu.followup_validation import record_gap_timings, validate_followups
from app.services.lagen_nu.question_validation import LegalNeedNormalizer, keep_verdict
from app.services.research.followup import FollowUpNeedDraft

pytestmark = pytest.mark.research_reuse


def draft(question):
    return FollowUpNeedDraft(
        question=question,
        why_needed="Missing cases",
        source_types=["swedish_case_law"],
        parent_research_need_id="main",
        source_gap="Missing cases",
    )


async def test_checks_are_bounded_parallel_and_keep_input_order(monkeypatch):
    monkeypatch.setattr(settings, "research_need_concurrency", 2)
    entered, release = asyncio.Event(), asyncio.Event()
    active = maximum = 0

    async def check(item):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        if active == 2:
            entered.set()
        await release.wait()
        active -= 1
        return [item]

    items = [draft(str(i)) for i in range(5)]
    timings = {}
    with record_gap_timings(timings):
        task = asyncio.create_task(validate_followups(items, check))
        await asyncio.wait_for(entered.wait(), 1)
        assert not task.done()
        release.set()
        assert await task == items
    assert maximum == 2
    assert set(timings) == {"legal_validation", *(f"legal_validation_{i}" for i in range(1, 6))}


async def test_failure_cancels_siblings_before_returning():
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def check(item):
        if item.question == "failure":
            await entered.wait()
            raise ValueError("Model failed")
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    with pytest.raises(ExceptionGroup, match="unhandled errors"):
        await validate_followups([draft("failure"), draft("pending")], check)
    assert cancelled.is_set()


async def test_duplicate_question_is_validated_once_and_merges_sources():
    validator = AsyncMock()
    validator.validate.return_value = keep_verdict("Same question")
    normalizer = LegalNeedNormalizer(validator)
    second = draft("Same question")
    second.source_types.append("swedish_preparatory_works")
    result = await normalizer.normalize_follow_up_drafts([draft("Same question"), second])
    validator.validate.assert_awaited_once()
    assert result[0].source_types == ["swedish_case_law", "swedish_preparatory_works"]


async def test_caller_cancellation_waits_for_all_checks():
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def check(item):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    task = asyncio.create_task(validate_followups([draft("pending")], check))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
