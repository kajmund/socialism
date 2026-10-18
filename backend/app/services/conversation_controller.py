"""Conversation turn-taking state machine for live speech (§3, §10).

The controller owns who holds the floor; it never blocks audio or model work.
"""

from __future__ import annotations

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

    def user_speaking(self) -> ConversationState:
        self.state = (
            "OVERLAPPING"
            if self.state in {"AI_SPEAKING", "AI_THINKING"}
            else "USER_SPEAKING"
        )
        return self.state

    def user_committed(self) -> ConversationState:
        self.state = (
            "AI_THINKING"
            if self.state in {"USER_SPEAKING", "OVERLAPPING"}
            else "USER_PAUSED"
        )
        return self.state

    def ai_thinking(self) -> ConversationState:
        self.state = "AI_THINKING"
        return self.state

    def ai_speaking(self) -> ConversationState:
        self.state = "AI_SPEAKING"
        return self.state

    def ai_interrupted(self) -> ConversationState:
        self.state = "AI_INTERRUPTED"
        return self.state

    def idle(self) -> ConversationState:
        self.state = "IDLE"
        return self.state
