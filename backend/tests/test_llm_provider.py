"""OpenAI-compatible chat provider selection (Cerebras default, DeepSeek A/B)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import (
    CEREBRAS_DEFAULT_BASE_URL,
    CEREBRAS_DEFAULT_MODEL,
    Settings,
    settings,
)
from app.llm import (
    LLMCallStats,
    bind_usage_recorder,
    complete_structured,
    complete_with_tools,
    get_client,
    reset_client,
    reset_usage_recorder,
    set_structured_completer,
    set_text_completer,
    set_tools_completer,
)
from app.schemas.domain import FollowUpQuestions
from app.services.expertgranskning.schemas import WordCommentConvergence


@pytest.fixture(autouse=True)
def _restore_llm_settings():
    previous = (
        settings.llm_provider,
        settings.llm_model,
        settings.llm_reasoning_effort,
        settings.cerebras_api_key,
        settings.deepseek_api_key,
        settings.deepseek_model,
        settings.deepseek_base_url,
        settings.cerebras_base_url,
    )
    yield
    (
        settings.llm_provider,
        settings.llm_model,
        settings.llm_reasoning_effort,
        settings.cerebras_api_key,
        settings.deepseek_api_key,
        settings.deepseek_model,
        settings.deepseek_base_url,
        settings.cerebras_base_url,
    ) = previous
    reset_client()
    set_structured_completer(None)
    set_text_completer(None)
    set_tools_completer(None)


def test_default_config_selects_cerebras_gpt_oss_120b_medium():
    assert Settings.model_fields["llm_provider"].default == "cerebras"
    assert Settings.model_fields["llm_model"].default == ""
    assert Settings.model_fields["llm_reasoning_effort"].default == "medium"
    assert Settings.model_fields["llm_max_tokens"].default == 8192
    assert Settings.model_fields["cerebras_base_url"].default == CEREBRAS_DEFAULT_BASE_URL
    assert Settings.model_fields["word_review_router_model"].default == ""
    assert settings.llm_provider == "cerebras"
    assert settings.selected_llm_model == CEREBRAS_DEFAULT_MODEL
    assert settings.selected_reasoning_effort == "medium"
    assert settings.word_review_router_model_override is None


def test_deepseek_provider_uses_existing_deepseek_settings():
    previous = (
        settings.llm_provider,
        settings.llm_model,
        settings.deepseek_model,
        settings.deepseek_base_url,
        settings.deepseek_api_key,
    )
    try:
        settings.llm_provider = "deepseek"
        settings.llm_model = ""
        settings.deepseek_model = "deepseek-chat"
        settings.deepseek_base_url = "https://api.deepseek.com"
        settings.deepseek_api_key = "sk-deepseek-test"
        assert settings.selected_llm_model == "deepseek-chat"
        assert settings.selected_llm_base_url == "https://api.deepseek.com"
        assert settings.selected_llm_api_key == "sk-deepseek-test"
        assert settings.selected_reasoning_effort is None
        assert settings.chat_llm_key_env_name == "DEEPSEEK_API_KEY"
    finally:
        (
            settings.llm_provider,
            settings.llm_model,
            settings.deepseek_model,
            settings.deepseek_base_url,
            settings.deepseek_api_key,
        ) = previous


def test_selected_provider_missing_key_fails_loud_without_fallback():
    previous_key = settings.cerebras_api_key
    try:
        settings.llm_provider = "cerebras"
        settings.cerebras_api_key = ""
        settings.deepseek_api_key = "sk-deepseek-unused"
        reset_client()
        with pytest.raises(RuntimeError, match="CEREBRAS_API_KEY"):
            get_client()
    finally:
        settings.cerebras_api_key = previous_key
        reset_client()


def test_settings_require_selected_provider_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "cerebras")
    monkeypatch.setenv("CEREBRAS_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-unused")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "secret")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "role")
    with pytest.raises(ValidationError, match="CEREBRAS_API_KEY"):
        Settings()


def test_get_client_rebuilds_when_provider_changes():
    settings.llm_provider = "cerebras"
    settings.cerebras_api_key = "csk-test"
    settings.cerebras_base_url = CEREBRAS_DEFAULT_BASE_URL
    reset_client()
    cerebras = get_client()
    settings.llm_provider = "deepseek"
    settings.deepseek_api_key = "sk-deepseek-test"
    settings.deepseek_base_url = "https://api.deepseek.com"
    deepseek = get_client()
    assert cerebras is not deepseek
    assert "cerebras.ai" in str(cerebras.base_url)
    assert "deepseek.com" in str(deepseek.base_url)
    settings.llm_provider = "cerebras"
    reset_client()


@pytest.mark.asyncio
async def test_complete_structured_cerebras_sends_reasoning_effort(monkeypatch):
    set_structured_completer(None)
    captured: dict = {}
    settings.llm_provider = "cerebras"
    settings.llm_model = ""
    settings.llm_reasoning_effort = "medium"

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"issues":[]}'))
            ],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
        )

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    recorded: list[LLMCallStats] = []
    token = bind_usage_recorder(recorded.append)
    try:
        parsed = await complete_structured(
            [{"role": "user", "content": "group"}],
            WordCommentConvergence,
        )
    finally:
        reset_usage_recorder(token)
    assert parsed.issues == []
    assert captured["model"] == CEREBRAS_DEFAULT_MODEL
    assert captured["reasoning_effort"] == "medium"
    response_format = captured["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "WordCommentConvergence"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == (
        WordCommentConvergence.model_json_schema()
    )
    assert "tools" not in captured
    assert captured["max_tokens"] == settings.llm_max_tokens
    assert recorded[0].provider == "cerebras"
    assert recorded[0].model == CEREBRAS_DEFAULT_MODEL
    assert recorded[0].reasoning_effort == "medium"
    assert recorded[0].prompt_tokens == 11
    assert recorded[0].completion_tokens == 7


@pytest.mark.asyncio
async def test_complete_structured_deepseek_omits_reasoning_effort(monkeypatch):
    set_structured_completer(None)
    captured: dict = {}
    settings.llm_provider = "deepseek"
    settings.llm_model = ""
    settings.deepseek_model = "deepseek-chat"

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"issues":[]}'))
            ],
            usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2),
        )

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    try:
        parsed = await complete_structured(
            [{"role": "user", "content": "group"}],
            WordCommentConvergence,
        )
        assert parsed.issues == []
        assert captured["model"] == "deepseek-chat"
        assert "reasoning_effort" not in captured
        assert captured["response_format"] == {"type": "json_object"}
        schema_dump = json.dumps(
            WordCommentConvergence.model_json_schema(), ensure_ascii=False
        )
        assert schema_dump in captured["messages"][-1]["content"]
    finally:
        settings.llm_provider = "cerebras"


def _structured_completion(content: str) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2),
    )


@pytest.mark.asyncio
async def test_complete_structured_cerebras_sends_follow_up_json_schema(
    monkeypatch,
):
    set_structured_completer(None)
    captured: dict = {}
    settings.llm_provider = "cerebras"
    settings.llm_model = ""

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _structured_completion(
            '{"questions":["Hur mår du?","Vad händer sen?"]}'
        )

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    parsed = await complete_structured(
        [{"role": "user", "content": "chips"}],
        FollowUpQuestions,
    )
    assert parsed.questions == ["Hur mår du?", "Vad händer sen?"]
    response_format = captured["response_format"]
    schema = FollowUpQuestions.model_json_schema()
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "FollowUpQuestions"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == schema
    assert "questions" in schema["required"]
    assert response_format["json_schema"]["schema"]["required"] == ["questions"]
    guide = captured["messages"][-1]["content"]
    assert json.dumps(schema, ensure_ascii=False) not in guide
    assert "tools" not in captured


@pytest.mark.asyncio
async def test_complete_structured_rejects_empty_follow_up_payload(monkeypatch):
    """Reproduce the production {} payload; Pydantic still rejects it locally."""
    set_structured_completer(None)
    settings.llm_provider = "cerebras"
    settings.llm_model = ""

    async def fake_create(**kwargs):
        return _structured_completion("{}")

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    with pytest.raises(ValidationError, match="questions") as exc_info:
        await complete_structured(
            [{"role": "user", "content": "chips"}],
            FollowUpQuestions,
        )
    assert exc_info.value.error_count() == 1
    assert exc_info.value.errors()[0]["type"] == "missing"


@pytest.mark.asyncio
async def test_complete_structured_rejects_malformed_follow_up_payload(
    monkeypatch,
):
    set_structured_completer(None)
    settings.llm_provider = "cerebras"
    settings.llm_model = ""

    async def fake_create(**kwargs):
        return _structured_completion('{"questions":"not-a-list"}')

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    with pytest.raises(ValidationError, match="questions"):
        await complete_structured(
            [{"role": "user", "content": "chips"}],
            FollowUpQuestions,
        )


@pytest.mark.asyncio
async def test_complete_structured_deepseek_follow_ups_keep_json_object(
    monkeypatch,
):
    set_structured_completer(None)
    captured: dict = {}
    settings.llm_provider = "deepseek"
    settings.llm_model = ""
    settings.deepseek_model = "deepseek-chat"

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _structured_completion('{"questions":["A?","B?"]}')

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    try:
        parsed = await complete_structured(
            [{"role": "user", "content": "chips"}],
            FollowUpQuestions,
        )
        assert parsed.questions == ["A?", "B?"]
        assert captured["response_format"] == {"type": "json_object"}
        schema_dump = json.dumps(
            FollowUpQuestions.model_json_schema(), ensure_ascii=False
        )
        assert schema_dump in captured["messages"][-1]["content"]
        assert "json_schema" not in captured["response_format"]
    finally:
        settings.llm_provider = "cerebras"


@pytest.mark.asyncio
async def test_complete_with_tools_normalizes_per_provider(monkeypatch):
    set_tools_completer(None)
    set_text_completer(None)
    seen: list[list] = []

    async def fake_create(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )

    monkeypatch.setattr(
        "app.llm.get_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    messages = [
        {
            "role": "assistant",
            "content": None,
            "reasoning_content": "plan",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "get_run", "arguments": "{}"}}
            ],
        }
    ]
    settings.llm_provider = "deepseek"
    await complete_with_tools(messages, None)
    settings.llm_provider = "cerebras"
    await complete_with_tools(messages, None)
    deepseek_kwargs, cerebras_kwargs = seen
    assert deepseek_kwargs["messages"][0]["reasoning_content"] == "plan"
    assert "reasoning_content" not in cerebras_kwargs["messages"][0]
    assert cerebras_kwargs["messages"][0]["tool_calls"][0]["type"] == "function"
    assert "response_format" not in deepseek_kwargs
    assert "response_format" not in cerebras_kwargs


@pytest.mark.asyncio
async def test_injectable_structured_completer_still_used():
    async def fake(_messages, response_model):
        return response_model.model_validate({"issues": []})

    set_structured_completer(fake)
    parsed = await complete_structured(
        [{"role": "user", "content": "group"}],
        WordCommentConvergence,
    )
    assert parsed.issues == []
    set_structured_completer(None)


def test_word_review_has_no_hidden_deepseek_router_override():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app" / "services" / "expertgranskning"
    for name in ("word_review.py", "actor_context.py"):
        text = (root / name).read_text()
        assert "deepseek-chat" not in text
        assert "word_review_router_model_override" in text
