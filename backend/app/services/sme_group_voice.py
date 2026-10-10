"""SME group (panel) live voice session foundation — phase 1.

State machine for a human + several expert bots in a panel voice chat.

Rules locked for phase 1:
- Experts not directly addressed by name must raise a hand (silent UI) before speaking.
- Human can always address any expert by name and grant the floor immediately.
- Hands may be raised while someone else is speaking.
- After an expert finishes, the floor automatically returns to open.
- Remaining raised hands are kept or lowered by each expert's own Jev judgment.
- Only the expert can lower their own hand.
- Experts may call tools while listening; a useful result can trigger a hand-raise.
- Tool results that cause a hand-raise are shared among the panel experts.
- Human sees only a simple visual cue that a source was checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.jev.system import HttpJevSystemOne, JevClientError, parse_noul


@dataclass
class SharedToolResult:
    """Tool result attached to a hand-raise and shared with other experts."""

    expert_id: str
    tool_name: str
    result: Any
    summary: str = ""


@dataclass
class GroupVoiceSession:
    """In-memory state for one panel voice session."""

    panel_id: str
    member_ids: set[str]
    member_names: dict[str, str]  # persona_id -> display name

    floor: str | None = None  # None = open, else persona_id holding the floor
    hands: set[str] = field(default_factory=set)
    shared_results: list[SharedToolResult] = field(default_factory=list)
    # expert_id -> True if they currently have a "source checked" indicator
    source_checked: dict[str, bool] = field(default_factory=dict)

    def is_member(self, persona_id: str) -> bool:
        return persona_id in self.member_ids

    def address_by_name(self, utterance: str) -> str | None:
        """Return persona_id if the utterance directly addresses an expert by exact name."""
        text = utterance.lower()
        for persona_id, name in self.member_names.items():
            if name.lower() in text:
                return persona_id
        return None

    def grant_floor(self, persona_id: str) -> None:
        """Human grants floor (by name or accepting a hand)."""
        if not self.is_member(persona_id):
            return
        self.floor = persona_id
        self.hands.discard(persona_id)

    def release_floor(self) -> None:
        """Expert finished speaking; floor returns to open."""
        self.floor = None

    def raise_hand(self, persona_id: str) -> None:
        """Silent hand raise. Allowed even while someone else holds the floor."""
        if not self.is_member(persona_id):
            return
        if self.floor == persona_id:
            return  # already speaking
        self.hands.add(persona_id)

    def lower_hand(self, persona_id: str) -> None:
        """Only the expert themselves (via Jev) may lower their hand."""
        self.hands.discard(persona_id)
        self.source_checked.pop(persona_id, None)

    def attach_tool_result(
        self,
        expert_id: str,
        tool_name: str,
        result: Any,
        summary: str = "",
    ) -> None:
        """Expert found something useful; share the result and mark source checked."""
        if not self.is_member(expert_id):
            return
        self.shared_results.append(
            SharedToolResult(
                expert_id=expert_id,
                tool_name=tool_name,
                result=result,
                summary=summary,
            )
        )
        self.source_checked[expert_id] = True
        self.raise_hand(expert_id)

    async def decide_keep_hands(
        self,
        recent_transcript: str,
        jev: HttpJevSystemOne | None = None,
    ) -> None:
        """After floor returns to open, each remaining hand asks Jev whether to stay raised."""
        if not self.hands:
            return
        client = jev or HttpJevSystemOne()
        to_lower: list[str] = []
        for persona_id in list(self.hands):
            name = self.member_names.get(persona_id, persona_id)
            state = {
                "transcript": recent_transcript,
                "expert": name,
                "shared_results": [
                    {"from": r.expert_id, "tool": r.tool_name, "summary": r.summary}
                    for r in self.shared_results[-5:]
                ],
            }
            questions = {
                "keep_hand": {
                    "type": "noul",
                    "instructions": (
                        f"Is the point {name} wanted to raise still relevant and unanswered "
                        "given the recent discussion? Answer yes if the hand should stay raised."
                    ),
                }
            }
            try:
                result = await client.ask(
                    state=state,
                    questions=questions,
                    model="jev-latest",
                    timeout_seconds=2.0,
                )
                probability = parse_noul(result.answers, "keep_hand")
                if probability < 0.5:
                    to_lower.append(persona_id)
            except JevClientError:
                # On Jev failure, keep the hand (conservative).
                pass
        for persona_id in to_lower:
            self.lower_hand(persona_id)

    def snapshot(self) -> dict[str, Any]:
        """Serializable view for the frontend."""
        floor_name = self.member_names.get(self.floor) if self.floor else None
        return {
            "floor": self.floor,
            "floor_name": floor_name,
            "hands": sorted(self.hands),
            "source_checked": [
                pid for pid, checked in self.source_checked.items() if checked
            ],
            "shared_result_count": len(self.shared_results),
        }
