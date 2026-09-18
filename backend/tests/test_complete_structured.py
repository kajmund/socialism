"""Structured LLM calls send an explicit completion cap."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings, settings
from app.llm import complete_structured, set_structured_completer
from app.llm.structured_schema import strict_json_schema
from app.services.expertgranskning.schemas import WordCommentConvergence


@pytest.mark.asyncio
async def test_complete_structured_sends_explicit_max_tokens(monkeypatch):
    set_structured_completer(None)
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"issues":[]}'))
            ]
        )

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    parsed = await complete_structured(
        [{"role": "user", "content": "group"}],
        WordCommentConvergence,
    )
    assert parsed.issues == []
    assert captured["max_tokens"] == settings.llm_max_tokens
    assert captured["timeout"] == settings.llm_timeout_seconds
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["response_format"]["json_schema"]["schema"] == strict_json_schema(
        WordCommentConvergence.model_json_schema()
    )
    assert captured["messages"] == [{"role": "user", "content": "group"}]


def test_llm_max_tokens_defaults_to_8192():
    assert Settings.model_fields["llm_max_tokens"].default == 8192


@pytest.mark.asyncio
async def test_complete_structured_overrides_request_timeout(monkeypatch):
    set_structured_completer(None)
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"issues":[]}'))
            ]
        )

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    await complete_structured(
        [{"role": "user", "content": "group"}],
        WordCommentConvergence,
        timeout=180,
    )

    assert captured["timeout"] == 180
