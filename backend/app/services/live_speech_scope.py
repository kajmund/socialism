"""Session scope for one Live Speech socket."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas.workspace import WorkspaceState


@dataclass(frozen=True, slots=True)
class LiveSpeechScope:
    user_id: str
    customer_id: int
    workspace_id: str
    expert_id: str
    language: str
    voice_id: str
    workspace_state: WorkspaceState
    prompts: dict[str, str] = field(default_factory=dict)
    recent_turns: tuple[tuple[str, str], ...] = ()
    stt_prompt: str = ""
    stt_keywords: tuple[str, ...] = ()
    stt_base_keywords: tuple[str, ...] = ()
    correction_enabled: bool = True
    correction_timeout: float = 2.0
