"""Structured DeepSeek calls send an explicit completion cap."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings, settings
from app.llm import complete_structured, set_structured_completer
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
    assert captured["max_tokens"] == settings.deepseek_max_tokens
    assert captured["response_format"] == {"type": "json_object"}


def test_deepseek_max_tokens_defaults_to_8192():
    assert Settings.model_fields["deepseek_max_tokens"].default == 8192
