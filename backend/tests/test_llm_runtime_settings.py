"""LLM runtime settings catalog, apply, and probe API."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import settings
from app.llm import reset_client
from app.services import llm_runtime_settings as runtime


@pytest.fixture(autouse=True)
def _restore_llm_settings():
    previous = (
        settings.llm_provider,
        settings.llm_model,
        settings.llm_reasoning_effort,
        settings.llm_max_tokens,
        settings.llm_temperature,
        settings.llm_top_p,
        settings.cerebras_api_key,
        settings.deepseek_api_key,
        settings.deepseek_model,
    )
    yield
    (
        settings.llm_provider,
        settings.llm_model,
        settings.llm_reasoning_effort,
        settings.llm_max_tokens,
        settings.llm_temperature,
        settings.llm_top_p,
        settings.cerebras_api_key,
        settings.deepseek_api_key,
        settings.deepseek_model,
    ) = previous
    reset_client()


def test_catalog_has_four_profiles_with_per_model_effort():
    rows = {row["id"]: row for row in runtime.catalog_as_dicts()}
    assert set(rows) == {
        "deepseek-flash",
        "deepseek-v4-pro",
        "gpt-oss-120b",
        "qwen-3.8-27b",
    }
    gpt = {p["key"]: p for p in rows["gpt-oss-120b"]["params"]}
    qwen = {p["key"]: p for p in rows["qwen-3.8-27b"]["params"]}
    flash = {p["key"]: p for p in rows["deepseek-flash"]["params"]}
    pro = {p["key"]: p for p in rows["deepseek-v4-pro"]["params"]}
    assert flash["reasoning_effort"]["choices"] == ["none", "low", "high", "max"]
    assert flash["reasoning_effort"]["default"] == "high"
    assert pro["reasoning_effort"]["choices"] == ["none", "low", "high", "max"]
    assert gpt["reasoning_effort"]["choices"] == ["low", "medium", "high"]
    assert gpt["max_tokens"]["maximum"] == 40_000
    assert qwen["reasoning_effort"]["choices"] == ["low", "medium", "high"]
    assert qwen["reasoning_effort"]["default"] == "high"
    assert qwen["max_tokens"]["maximum"] == 40_000
    assert flash["max_tokens"]["maximum"] == 393_216


def test_legacy_deepseek_chat_profile_maps_to_flash():
    assert runtime.resolve_profile_id("deepseek-chat") == "deepseek-flash"
    normalized = runtime.validate_and_normalize(
        profile_id="deepseek-chat",
        temperature=1.0,
        top_p=1.0,
        max_tokens=8192,
        reasoning_effort=None,
    )
    assert normalized["profile_id"] == "deepseek-flash"
    assert normalized["reasoning_effort"] == "high"


def test_validate_allows_deepseek_393216_max_tokens():
    normalized = runtime.validate_and_normalize(
        profile_id="deepseek-flash",
        temperature=1.0,
        top_p=1.0,
        max_tokens=393_216,
        reasoning_effort="high",
    )
    assert normalized["max_tokens"] == 393_216


def test_validate_allows_gpt_oss_40k_max_tokens():
    normalized = runtime.validate_and_normalize(
        profile_id="gpt-oss-120b",
        temperature=1.0,
        top_p=1.0,
        max_tokens=40_000,
        reasoning_effort="medium",
    )
    assert normalized["max_tokens"] == 40_000


def test_validate_allows_qwen_40k_max_tokens():
    normalized = runtime.validate_and_normalize(
        profile_id="qwen-3.8-27b",
        temperature=1.0,
        top_p=1.0,
        max_tokens=40_000,
        reasoning_effort="high",
    )
    assert normalized["max_tokens"] == 40_000


def test_validate_rejects_qwen_xhigh_effort():
    with pytest.raises(ValueError, match="reasoning_effort"):
        runtime.validate_and_normalize(
            profile_id="qwen-3.8-27b",
            temperature=0.7,
            top_p=0.9,
            max_tokens=1024,
            reasoning_effort="xhigh",
        )


def test_apply_qwen_sets_cerebras_and_high():
    settings.cerebras_api_key = "cb-test"
    runtime.apply_runtime_settings(
        profile_id="qwen-3.8-27b",
        temperature=0.2,
        top_p=0.95,
        max_tokens=2048,
        reasoning_effort="high",
    )
    assert settings.llm_provider == "cerebras"
    assert settings.llm_model == "qwen-3.8-27b"
    assert settings.llm_temperature == 0.2
    assert settings.llm_top_p == 0.95
    assert settings.llm_max_tokens == 2048
    assert settings.llm_reasoning_effort == "high"


def test_apply_deepseek_flash_sets_effort():
    settings.deepseek_api_key = "ds-test"
    runtime.apply_runtime_settings(
        profile_id="deepseek-flash",
        temperature=0.5,
        top_p=1.0,
        max_tokens=8192,
        reasoning_effort="low",
    )
    assert settings.llm_provider == "deepseek"
    assert settings.llm_model == "deepseek-flash"
    assert settings.deepseek_model == "deepseek-flash"
    assert settings.llm_reasoning_effort == "low"
    assert settings.selected_reasoning_effort == "low"


def test_chat_create_kwargs_includes_sampling_and_deepseek_effort():
    from app import llm as llm_mod

    settings.llm_provider = "deepseek"
    settings.llm_model = "deepseek-flash"
    settings.deepseek_api_key = "ds-test"
    settings.llm_temperature = 0.4
    settings.llm_top_p = 0.8
    settings.llm_max_tokens = 512
    settings.llm_reasoning_effort = "max"
    kwargs = llm_mod._chat_create_kwargs(model="deepseek-flash", messages=[])
    assert kwargs["temperature"] == 0.4
    assert kwargs["top_p"] == 0.8
    assert kwargs["max_tokens"] == 512
    assert (
        kwargs.get("reasoning_effort") == "max"
        or (kwargs.get("extra_body") or {}).get("reasoning_effort") == "max"
    )


def test_chat_create_kwargs_reasoning_only_for_cerebras():
    from app import llm as llm_mod

    settings.llm_provider = "cerebras"
    settings.llm_model = "gpt-oss-120b"
    settings.cerebras_api_key = "cb-test"
    settings.llm_reasoning_effort = "low"
    settings.llm_temperature = None
    settings.llm_top_p = None
    kwargs = llm_mod._chat_create_kwargs(model="gpt-oss-120b", messages=[])
    if "reasoning_effort" in llm_mod._openai_create_params:
        assert kwargs["reasoning_effort"] == "low"
    assert "temperature" not in kwargs


@pytest.mark.asyncio
async def test_get_llm_requires_admin(client, user_token, admin_token):
    client.headers["Authorization"] = f"Bearer {user_token}"
    denied = await client.get("/llm")
    assert denied.status_code == 403
    client.headers["Authorization"] = f"Bearer {admin_token}"
    ok = await client.get("/llm")
    assert ok.status_code == 200
    body = ok.json()
    assert "catalog" in body and "active" in body and "credentials" in body


@pytest.mark.asyncio
async def test_put_llm_persists_and_applies(client_db):
    client, factory = client_db
    settings.cerebras_api_key = "cb-test"
    response = await client.put(
        "/llm",
        json={
            "profile_id": "qwen-3.8-27b",
            "temperature": 0.5,
            "top_p": 0.9,
            "max_tokens": 1024,
            "reasoning_effort": "high",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["profile_id"] == "qwen-3.8-27b"
    assert body["model"] == "qwen-3.8-27b"
    assert settings.llm_model == "qwen-3.8-27b"
    assert settings.llm_reasoning_effort == "high"

    # Reset in-memory settings, then reload from DB.
    settings.llm_provider = "deepseek"
    settings.llm_model = "deepseek-flash"
    settings.llm_reasoning_effort = "medium"
    async with factory() as session:
        loaded = await runtime.load_runtime_settings(session)
    assert loaded is True
    assert settings.llm_model == "qwen-3.8-27b"
    assert settings.llm_reasoning_effort == "high"


@pytest.mark.asyncio
async def test_probe_returns_metrics(client, monkeypatch):
    settings.cerebras_api_key = "cb-test"
    settings.llm_provider = "cerebras"
    settings.llm_model = "gpt-oss-120b"

    async def fake_metrics(messages):
        assert messages[-1]["content"] == "ping"
        return SimpleNamespace(
            text="pong",
            prompt_tokens=3,
            completion_tokens=7,
            elapsed_ms=250.0,
            time_to_first_token_ms=40.0,
            finish_reason="stop",
        )

    monkeypatch.setattr(
        "app.api.llm_settings.stream_text_with_metrics",
        fake_metrics,
    )
    response = await client.post("/llm/probe", json={"prompt": "ping"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response"] == "pong"
    assert body["prompt_tokens"] == 3
    assert body["completion_tokens"] == 7
    assert body["total_tokens"] == 10
    assert body["round_trip_ms"] == 250.0
    assert body["time_to_first_token_ms"] == 40.0
    assert body["completion_tokens_per_second"] == pytest.approx(28.0)


@pytest.mark.asyncio
async def test_probe_keeps_admin_save_when_settings_change_during_probe(
    client, monkeypatch
):
    settings.cerebras_api_key = "cb-test"
    settings.deepseek_api_key = "ds-test"
    runtime.apply_runtime_settings(
        profile_id="gpt-oss-120b",
        temperature=1.0,
        top_p=1.0,
        max_tokens=8192,
        reasoning_effort="medium",
    )

    async def fake_metrics(messages):
        runtime.apply_runtime_settings(
            profile_id="deepseek-flash",
            temperature=0.3,
            top_p=0.8,
            max_tokens=2048,
            reasoning_effort="low",
        )
        return SimpleNamespace(
            text="pong",
            prompt_tokens=1,
            completion_tokens=1,
            elapsed_ms=10.0,
            time_to_first_token_ms=1.0,
            finish_reason="stop",
        )

    monkeypatch.setattr(
        "app.api.llm_settings.stream_text_with_metrics",
        fake_metrics,
    )
    response = await client.post(
        "/llm/probe",
        json={"prompt": "ping", "profile_id": "qwen-3.8-27b"},
    )
    assert response.status_code == 200, response.text
    assert settings.llm_model == "deepseek-flash"
    assert settings.llm_reasoning_effort == "low"


@pytest.mark.asyncio
async def test_save_runtime_settings_does_not_apply_when_commit_fails(
    client_db, monkeypatch
):
    _client, factory = client_db
    settings.cerebras_api_key = "cb-test"
    runtime.apply_runtime_settings(
        profile_id="gpt-oss-120b",
        temperature=1.0,
        top_p=1.0,
        max_tokens=8192,
        reasoning_effort="medium",
    )
    before_model = settings.llm_model
    before_revision = runtime.settings_revision()

    async def fail_commit(self):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(
        "sqlalchemy.ext.asyncio.session.AsyncSession.commit",
        fail_commit,
    )
    async with factory() as session:
        with pytest.raises(RuntimeError, match="commit failed"):
            await runtime.save_runtime_settings(
                session,
                profile_id="qwen-3.8-27b",
                temperature=0.5,
                top_p=0.9,
                max_tokens=1024,
                reasoning_effort="high",
            )
    assert settings.llm_model == before_model
    assert runtime.settings_revision() == before_revision
