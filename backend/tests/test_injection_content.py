"""Tests for injection content passed to OASIS CREATE_POST."""

import pytest

from app.schemas.domain import Injection
from app.services.oasis_run import _prepare_injection_content


@pytest.mark.asyncio
async def test_prepare_injection_content_passes_text_unchanged():
    injection = Injection(
        key="i1",
        type="news_post",
        sender="@Nyheter",
        text="Partiet vill införa en svensk maffialag för att kollektivt kunna döma kriminella nätverk.",
    )
    out = await _prepare_injection_content(injection)
    assert out == injection.text


@pytest.mark.asyncio
async def test_prepare_injection_content_empty_when_no_body():
    injection = Injection(
        key="i1",
        type="news_post",
        sender="@Nyheter",
        text="",
    )
    assert await _prepare_injection_content(injection) == ""
