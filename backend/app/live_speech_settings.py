from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class LiveSpeechSettings(BaseModel):
    live_speech_stt_model: str = "gpt-live-transcribe"
    live_speech_noise_reduction: Literal["near_field", "far_field"] = "near_field"
    live_speech_stt_timeout_seconds: float = Field(default=12.0, gt=1, le=120)
    live_speech_tts_model: str = "eleven_v4_turbo"
    live_speech_tts_output_format: str = "pcm_24000"
    live_speech_session_ttl_seconds: int = Field(default=3600, ge=60, le=14400)
    live_speech_idle_timeout_seconds: int = Field(default=120, ge=15, le=1800)
    # Silero VAD probability band: speech opens at the start threshold and closes
    # only below the exit threshold, so windows around the edge do not flicker.
    live_speech_vad_silero_threshold: float = Field(default=0.5, gt=0, lt=1)
    live_speech_vad_silero_exit_threshold: float = Field(default=0.35, gt=0, lt=1)
    live_speech_vad_preroll_ms: int = Field(default=250, ge=0, le=1000)
    live_speech_vad_hangover_ms: int = Field(default=600, ge=100, le=3000)
    live_speech_vad_min_speech_ms: int = Field(default=120, ge=0, le=2000)
    live_speech_vad_urgent_ms: int = Field(default=120, ge=0, le=1000)
    live_speech_backchannel_max_ms: int = Field(default=1200, ge=200, le=4000)
    live_speech_backchannel_confirm_ms: int = Field(default=300, ge=100, le=800)
    live_speech_listener_after_ms: int = Field(default=4000, ge=500, le=20000)
    live_speech_listener_cooldown_ms: int = Field(default=8000, ge=1000, le=30000)
    live_speech_waiting_suppress_ms: int = Field(default=50, ge=50, le=120_000)
    live_speech_phrase_timeout_seconds: float = Field(default=1.5, gt=0.2, le=8)
    # Speculative read-only prefetch on stable partial transcripts (default off).
    live_speech_speculation_enabled: bool = False
    live_speech_speculation_min_chars: int = Field(default=8, ge=4, le=200)
    live_speech_speculation_ttl_ms: int = Field(default=8000, ge=250, le=60_000)
    live_speech_speculation_concurrency: int = Field(default=2, ge=1, le=4)
    live_speech_tts_timeout_seconds: float = Field(default=8.0, gt=1, le=30)
    # ElevenLabs live-speech PCM segment cache (SHA256 keys). Pure disk, no database.
    tts_cache_dir: str = "data/tts_cache"
    # LRU cap for tts_cache_dir: oldest .pcm entries are evicted above it.
    tts_cache_max_bytes: int = Field(default=536_870_912, ge=1_048_576)

    @model_validator(mode="after")
    def require_silero_vad_band_order(self) -> Self:
        if self.live_speech_vad_silero_exit_threshold >= self.live_speech_vad_silero_threshold:
            raise ValueError(
                "LIVE_SPEECH_VAD_SILERO_EXIT_THRESHOLD must be below "
                "LIVE_SPEECH_VAD_SILERO_THRESHOLD"
            )
        return self


def tts_sample_rate(output_format: str) -> int:
    rate = output_format.rsplit("_", 1)[-1]
    if not rate.isdigit():
        raise RuntimeError("LIVE_SPEECH_TTS_OUTPUT_FORMAT must include a sample rate")
    return int(rate)


def vad_client_config(source: LiveSpeechSettings) -> dict[str, float | int]:
    """The same client VAD settings for a single expert and a group."""
    return {
        "silero_threshold": source.live_speech_vad_silero_threshold,
        "silero_exit_threshold": source.live_speech_vad_silero_exit_threshold,
        "preroll_ms": source.live_speech_vad_preroll_ms,
        "hangover_ms": source.live_speech_vad_hangover_ms,
        "min_speech_ms": source.live_speech_vad_min_speech_ms,
        "urgent_ms": source.live_speech_vad_urgent_ms,
    }
