"""Event-driven conversation turn-taking policy for live speech (§3, §10).

The controller owns floor, user-speech and model-work as separate tracks.
It never blocks audio or model work, and it never lets a stale turn mutate
the current turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ConversationState = Literal[
    "IDLE",
    "USER_SPEAKING",
    "USER_PAUSED",
    "AI_THINKING",
    "AI_SPEAKING",
    "OVERLAPPING",
    "AI_INTERRUPTED",
]
EventKind = Literal[
    "user_vad_start",
    "user_vad_commit",
    "user_partial",
    "user_final",
    "ai_think",
    "ai_speak",
    "ai_idle",
    "barge_interrupt",
    "barge_amend",
    "barge_backchannel",
    "cancel",
    "session_reset",
]
Floor = Literal["none", "user", "ai"]
UserSpeech = Literal["silent", "speaking", "paused"]
ModelWork = Literal["idle", "thinking", "speaking"]

_TURN_OWNED = frozenset(
    {
        "ai_think",
        "ai_speak",
        "ai_idle",
        "barge_interrupt",
        "barge_amend",
        "cancel",
    }
)


@dataclass(frozen=True, slots=True)
class ConversationEvent:
    kind: EventKind
    turn_id: str | None = None
    utterance_id: str | None = None
    sequence: int | None = None


@dataclass(frozen=True, slots=True)
class ConversationSnapshot:
    state: ConversationState
    accepted: bool
    ignore_reason: str | None
    turn_id: str | None
    floor: Floor
    user_speech: UserSpeech
    model_work: ModelWork
    session_epoch: int


def wire_state(state: ConversationState) -> str:
    """Project the detailed state onto the UI wire state."""
    if state == "AI_THINKING":
        return "thinking"
    if state == "AI_SPEAKING":
        return "speaking"
    return "listening"


class ConversationController:
    def __init__(self) -> None:
        self.state: ConversationState = "IDLE"
        self.turn_id: str | None = None
        self.utterance_id: str | None = None
        self.session_epoch = 0
        self.floor: Floor = "none"
        self.user_speech: UserSpeech = "silent"
        self.model_work: ModelWork = "idle"
        self._commit_seq = 0
        self._final_seq = 0
        self._partial_key: tuple[str | None, int | None] | None = None
        self._interrupted = False

    def reject_reason(self, event: ConversationEvent) -> str | None:
        return self._reject(event)

    def handle(self, event: ConversationEvent) -> ConversationSnapshot:
        reason = self.reject_reason(event)
        if reason is not None:
            return self.snapshot(accepted=False, ignore_reason=reason)
        self._apply(event)
        self._project()
        return self.snapshot(accepted=True)

    def snapshot(
        self,
        *,
        accepted: bool,
        ignore_reason: str | None = None,
    ) -> ConversationSnapshot:
        return ConversationSnapshot(
            state=self.state,
            accepted=accepted,
            ignore_reason=ignore_reason,
            turn_id=self.turn_id,
            floor=self.floor,
            user_speech=self.user_speech,
            model_work=self.model_work,
            session_epoch=self.session_epoch,
        )

    def user_speaking(self) -> ConversationState:
        return self.handle(ConversationEvent(kind="user_vad_start")).state

    def user_committed(self) -> ConversationState:
        return self.handle(ConversationEvent(kind="user_vad_commit")).state

    def ai_thinking(self) -> ConversationState:
        return self.handle(ConversationEvent(kind="ai_think")).state

    def ai_speaking(self) -> ConversationState:
        return self.handle(ConversationEvent(kind="ai_speak")).state

    def ai_interrupted(self) -> ConversationState:
        return self.handle(ConversationEvent(kind="barge_interrupt")).state

    def idle(self) -> ConversationState:
        return self.handle(ConversationEvent(kind="ai_idle")).state

    def reset(self) -> ConversationState:
        return self.handle(ConversationEvent(kind="session_reset")).state

    def _reject(self, event: ConversationEvent) -> str | None:
        if event.kind == "session_reset":
            return None
        owned = self._stale_turn(event)
        if owned is not None:
            return owned
        return self._stale_user(event)

    def _stale_turn(self, event: ConversationEvent) -> str | None:
        if event.kind not in _TURN_OWNED or event.turn_id is None or self.turn_id is None:
            return None
        if event.turn_id != self.turn_id:
            return "stale_turn"
        return None

    def _stale_user(self, event: ConversationEvent) -> str | None:
        if event.kind == "user_partial":
            return self._stale_partial(event)
        if event.kind != "user_final":
            return None
        if (
            event.utterance_id is not None
            and self.utterance_id is not None
            and event.utterance_id != self.utterance_id
        ):
            return "stale_utterance"
        if event.sequence is not None and event.sequence != self._commit_seq:
            return "stale_final"
        if self._commit_seq and self._final_seq == self._commit_seq:
            return "duplicate_final"
        return None

    def _stale_partial(self, event: ConversationEvent) -> str | None:
        key = (event.utterance_id, event.sequence)
        if (
            event.utterance_id is not None
            and self.utterance_id is not None
            and event.utterance_id != self.utterance_id
        ):
            return "stale_utterance"
        if event.sequence is not None and key == self._partial_key:
            return "duplicate_partial"
        return None

    def _apply(self, event: ConversationEvent) -> None:
        if event.kind.startswith("user_"):
            self._apply_user(event)
            return
        if event.kind.startswith("barge_") or event.kind == "cancel":
            self._apply_barge(event)
            return
        self._apply_session(event)

    def _apply_user(self, event: ConversationEvent) -> None:
        if event.kind == "user_vad_start":
            self.user_speech = "speaking"
            self.floor = "user"
            self._interrupted = False
            self.utterance_id = event.utterance_id
            self._partial_key = None
            return
        if event.kind == "user_vad_commit":
            live = self.user_speech == "speaking" or self.state == "OVERLAPPING"
            self.user_speech = "paused"
            self._commit_seq = (
                event.sequence if event.sequence is not None else self._commit_seq + 1
            )
            if live:
                self.model_work = "thinking"
                self._interrupted = False
            return
        if event.kind == "user_partial":
            self._partial_key = (event.utterance_id, event.sequence)
            if event.utterance_id is not None:
                self.utterance_id = event.utterance_id
            return
        self.user_speech = "silent"
        self.model_work = "thinking"
        self._interrupted = False
        self._final_seq = self._commit_seq
        if event.turn_id is not None:
            self.turn_id = event.turn_id

    def _apply_barge(self, event: ConversationEvent) -> None:
        if event.kind == "barge_backchannel":
            return
        if (
            event.kind != "barge_amend"
            and self.model_work == "idle"
            and self.floor == "none"
            and not self._interrupted
        ):
            return
        self.floor = "none"
        self._interrupted = event.kind != "barge_amend"
        self.model_work = "thinking" if event.kind == "barge_amend" else "idle"
        if event.kind == "cancel":
            self.turn_id = None

    def _apply_session(self, event: ConversationEvent) -> None:
        if event.kind == "session_reset":
            epoch = self.session_epoch + 1
            self.__init__()
            self.session_epoch = epoch
            return
        if event.kind == "ai_think":
            self.model_work = "thinking"
            self._interrupted = False
            if event.turn_id is not None:
                self.turn_id = event.turn_id
            return
        if event.kind == "ai_speak":
            self.model_work = "speaking"
            self.floor = "ai"
            self._interrupted = False
            return
        self.model_work = "idle"
        self.user_speech = "silent"
        self.floor = "none"
        self._interrupted = False
        self.turn_id = None

    def _project(self) -> None:
        if self._interrupted:
            self.state = "AI_INTERRUPTED"
            return
        talking = self.user_speech == "speaking"
        busy = self.model_work != "idle"
        if talking and busy:
            self.state = "OVERLAPPING"
        elif self.model_work == "speaking":
            self.state = "AI_SPEAKING"
        elif self.model_work == "thinking":
            self.state = "AI_THINKING"
        elif talking:
            self.state = "USER_SPEAKING"
        elif self.user_speech == "paused":
            self.state = "USER_PAUSED"
        else:
            self.state = "IDLE"
