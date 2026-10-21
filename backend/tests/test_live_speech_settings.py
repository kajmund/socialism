"""Live speech client VAD settings: mapping and fail-fast band order."""

import pytest
from pydantic import ValidationError

from app.config import Settings


def _settings(**overrides) -> Settings:
    # Ignore the developer's backend/.env so the defaults under test stay defaults.
    return Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite://",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="secret",
        openai_api_key="openai-key",
        cerebras_api_key="cerebras-key",
        **overrides,
    )


def test_silero_vad_band_defaults_are_sane() -> None:
    fields = Settings.model_fields
    assert fields["live_speech_vad_silero_threshold"].default == 0.5
    assert fields["live_speech_vad_silero_exit_threshold"].default == 0.35


def test_silero_vad_band_order_is_enforced() -> None:
    with pytest.raises(ValidationError):
        _settings(
            live_speech_vad_silero_threshold=0.4,
            live_speech_vad_silero_exit_threshold=0.4,
        )


def test_speculation_and_tts_timeout_defaults() -> None:
    configured = _settings()
    assert configured.live_speech_speculation_enabled is False
    assert configured.live_speech_speculation_ttl_ms == 8000
    assert configured.live_speech_speculation_concurrency == 2
    assert configured.live_speech_tts_timeout_seconds == 8.0


def test_silero_vad_band_accepts_a_wider_band() -> None:
    configured = _settings(
        live_speech_vad_silero_threshold=0.6,
        live_speech_vad_silero_exit_threshold=0.3,
    )
    assert configured.live_speech_vad_silero_threshold == 0.6
    assert configured.live_speech_vad_silero_exit_threshold == 0.3
