from pydantic import Field


class LiveSpeechSettings:
    live_speech_stt_model: str = "gpt-live-transcribe"
    live_speech_stt_timeout_seconds: float = Field(default=12.0, gt=1, le=120)
    live_speech_tts_model: str = "eleven_v4_turbo"
    live_speech_tts_output_format: str = "pcm_24000"
    live_speech_session_ttl_seconds: int = Field(default=3600, ge=60, le=14400)
    live_speech_idle_timeout_seconds: int = Field(default=120, ge=15, le=1800)
    live_speech_vad_threshold: float = Field(default=0.018, gt=0, le=1)
    live_speech_vad_preroll_ms: int = Field(default=250, ge=0, le=1000)
    live_speech_vad_hangover_ms: int = Field(default=600, ge=100, le=3000)
    live_speech_vad_min_speech_ms: int = Field(default=300, ge=0, le=2000)
    live_speech_vad_urgent_ms: int = Field(default=120, ge=0, le=1000)
    live_speech_backchannel_max_ms: int = Field(default=1200, ge=200, le=4000)
    live_speech_backchannel_confirm_ms: int = Field(default=300, ge=100, le=800)
    live_speech_listener_after_ms: int = Field(default=4000, ge=500, le=20000)
    live_speech_listener_cooldown_ms: int = Field(default=8000, ge=1000, le=30000)
    live_speech_waiting_suppress_ms: int = Field(default=350, ge=50, le=2000)
    live_speech_tool_progress_ms: int = Field(default=800, ge=100, le=5000)
    live_speech_phrase_timeout_seconds: float = Field(default=1.5, gt=0.2, le=8)
