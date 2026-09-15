"""Vision attachments in persona chat: multimodal parts, MIME guards, capabilities."""

from __future__ import annotations

import base64

import pytest

from app.config import settings
from app.llm.tool_messages import normalize_messages_for_openai
from app.llm.vision_content import user_content_with_optional_image
from app.services import image_cache
from app.services import llm_runtime_settings as runtime


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture(autouse=True)
def _restore_llm_and_cache(tmp_path, monkeypatch):
    previous = (
        settings.llm_provider,
        settings.llm_model,
        settings.llm_temperature,
        settings.llm_top_p,
        settings.llm_max_tokens,
        settings.llm_reasoning_effort,
        settings.deepseek_api_key,
        settings.cerebras_api_key,
        settings.image_cache_dir,
    )
    monkeypatch.setattr(settings, "image_cache_dir", str(tmp_path / "image_cache"))
    image_cache.clear_image_cache()
    yield
    (
        settings.llm_provider,
        settings.llm_model,
        settings.llm_temperature,
        settings.llm_top_p,
        settings.llm_max_tokens,
        settings.llm_reasoning_effort,
        settings.deepseek_api_key,
        settings.cerebras_api_key,
        settings.image_cache_dir,
    ) = previous
    image_cache.clear_image_cache()


def _activate(profile_id: str, *, effort: str) -> None:
    settings.deepseek_api_key = "ds-test"
    settings.cerebras_api_key = "cb-test"
    runtime.apply_runtime_settings(
        profile_id=profile_id,
        temperature=1.0,
        top_p=1.0,
        max_tokens=1024,
        reasoning_effort=effort,
    )


def test_catalog_vision_flags():
    rows = {row["id"]: row for row in runtime.catalog_as_dicts()}
    assert rows["deepseek-flash"]["supports_vision"] is True
    assert rows["deepseek-v4-pro"]["supports_vision"] is False
    assert rows["qwen-3.8-27b"]["supports_vision"] is True
    assert rows["gpt-oss-120b"]["supports_vision"] is False
    assert rows["qwen-3.8-27b"]["allowed_image_types"] == [
        "image/jpeg",
        "image/png",
    ]


def test_multimodal_parts_for_vision_model():
    _activate("deepseek-flash", effort="high")
    entry, _hit = image_cache.store_raw_image(
        _PNG,
        content_type="image/png",
        allowed_types=frozenset({"image/png", "image/jpeg"}),
    )
    content = user_content_with_optional_image("vad syns?", entry["sha256"])
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "vad syns?"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_gpt_oss_rejects_image():
    _activate("gpt-oss-120b", effort="medium")
    with pytest.raises(ValueError, match="does not support image"):
        user_content_with_optional_image("hej", "a" * 64)


def test_qwen_accepts_png_rejects_webp():
    _activate("qwen-3.8-27b", effort="high")
    allowed = runtime.allowed_image_types_for_active()
    entry, _hit = image_cache.store_raw_image(
        _PNG, content_type="image/png", allowed_types=allowed
    )
    content = user_content_with_optional_image("", entry["sha256"])
    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"

    with pytest.raises(ValueError, match="Unsupported image type"):
        image_cache.store_raw_image(
            b"RIFF....WEBP", content_type="image/webp", allowed_types=allowed
        )


def test_history_replay_keeps_image_url():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "titta"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,abc"},
                },
            ],
        }
    ]
    out = normalize_messages_for_openai(messages)
    assert out[0]["content"][1]["type"] == "image_url"
    assert out[0]["content"][1]["image_url"]["url"].startswith("data:image/png")


@pytest.mark.asyncio
async def test_capabilities_endpoint_non_admin(user_client):
    _activate("deepseek-flash", effort="high")
    response = await user_client.get("/llm/capabilities")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["supports_vision"] is True
    assert body["profile_id"] == "deepseek-flash"
    assert "image/png" in body["allowed_image_types"]


@pytest.mark.asyncio
async def test_capabilities_gpt_oss_no_vision(user_client):
    _activate("gpt-oss-120b", effort="medium")
    response = await user_client.get("/llm/capabilities")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["supports_vision"] is False
    assert body["allowed_image_types"] == []
