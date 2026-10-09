from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.elevenlabs_live import ElevenLabsLiveVoiceProvider
from app.services.gemini_live import GeminiLiveVoiceProvider
from app.services.live_voice import (
    LiveVoiceUnavailable,
    expert_live_voice,
    get_live_voice_provider,
)


def test_get_live_voice_provider_selects_gemini(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "live_voice_provider", "gemini")
    assert isinstance(get_live_voice_provider(), GeminiLiveVoiceProvider)


def test_get_live_voice_provider_selects_elevenlabs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "live_voice_provider", "elevenlabs")
    assert isinstance(get_live_voice_provider(), ElevenLabsLiveVoiceProvider)


def test_socialism_live_speech_uses_saved_elevenlabs_voice():
    persona = SimpleNamespace(
        live_voice_provider="socialism",
        live_voice="expert-voice",
    )

    assert expert_live_voice(persona) == ("socialism", "expert-voice")
    with pytest.raises(
        LiveVoiceUnavailable,
        match="socialism_live_speech_workspace_required",
    ):
        get_live_voice_provider("socialism")
