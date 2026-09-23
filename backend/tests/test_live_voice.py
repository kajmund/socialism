import pytest

from app.config import settings
from app.services.elevenlabs_live import ElevenLabsLiveVoiceProvider
from app.services.gemini_live import GeminiLiveVoiceProvider
from app.services.live_voice import get_live_voice_provider


def test_get_live_voice_provider_selects_gemini(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "live_voice_provider", "gemini")
    assert isinstance(get_live_voice_provider(), GeminiLiveVoiceProvider)


def test_get_live_voice_provider_selects_elevenlabs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "live_voice_provider", "elevenlabs")
    assert isinstance(get_live_voice_provider(), ElevenLabsLiveVoiceProvider)
