"""SME group (panel) live voice session foundation — phase 1.

State machine for a human + several expert bots in a panel voice chat.

Rules locked for phase 1:
- The expert closest to what was said speaks. Others raise a hand when they have something to add.
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

import logging
from dataclasses import dataclass, field
from typing import Any

from app.jev.system import HttpJevSystemOne, JevClientError, parse_noul
from app.services.sme_group_voice_names import addressed_member

logger = logging.getLogger(__name__)

# The raise-hand question asks for a strong yes before someone should get the floor.
# Live answers for the person who should speak still land around 0.3, under the usual 0.5.
_HAND_FLOOR = 0.25
_HAND_GAP = 0.12


def _wants_to_add(probability: float, best: float) -> bool:
    return probability >= _HAND_FLOOR and probability + _HAND_GAP >= best


def raised_hand_line(others: list[str]) -> str:
    """The speaker knows why the hand is up, and does not talk about the hand."""
    line = (
        "Du har räckt upp handen för att du har något att tillägga om det som just sades. "
        "Säg bara det tillägget. "
        "Nämn inte handen, ordet eller att du blev vald. "
        "Byt inte ämne och ta inte upp en annan fråga."
    )
    if others:
        return f"{line} Lämna det andra experter redan har sagt."
    return line


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
    floor_reason: str | None = None  # "hand" when they raised it, "name" when addressed
    last_utterance: str = ""
    hands: set[str] = field(default_factory=set)
    shared_results: list[SharedToolResult] = field(default_factory=list)
    # expert_id -> True if they currently have a "source checked" indicator
    source_checked: dict[str, bool] = field(default_factory=dict)

    def is_member(self, persona_id: str) -> bool:
        return persona_id in self.member_ids

    def address_by_name(self, utterance: str) -> str | None:
        """Return persona_id if a token names one expert, including mishearings like Claes for Klas."""
        return addressed_member(utterance, self.member_names)

    def grant_floor(self, persona_id: str, *, lower_hand: bool = True) -> None:
        """Human grants floor (by name or accepting a hand)."""
        if not self.is_member(persona_id):
            return
        self.floor = persona_id
        self.floor_reason = "hand" if persona_id in self.hands else "name"
        if lower_hand:
            self.hands.discard(persona_id)

    def release_floor(self) -> None:
        """Expert finished speaking; floor returns to open and that hand comes down."""
        speaker = self.floor
        self.floor = None
        self.floor_reason = None
        if speaker:
            self.lower_hand(speaker)

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
        keep_hand_prompt: str | None = None,
    ) -> None:
        """After floor returns to open, each remaining hand asks Jev whether to stay raised."""
        if not self.hands:
            return
        client = jev or HttpJevSystemOne()
        instruction_template = keep_hand_prompt or (
            "Is the point {name} wanted to raise still relevant and unanswered "
            "given the recent discussion? Answer yes if the hand should stay raised."
        )
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
                    "instructions": instruction_template.format(name=name),
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
                # Surface the failure; do not silently keep the hand.
                raise
        for persona_id in to_lower:
            self.lower_hand(persona_id)

    async def decide_raise_hands(
        self,
        utterance: str,
        jev: HttpJevSystemOne | None = None,
        raise_hand_prompt: str | None = None,
    ) -> str | None:
        """Ask who has something to add. Raise those hands, and return who is closest to the floor."""
        template = raise_hand_prompt or (
            "Does {name} have a distinct point to add after what was just said? "
            "Answer yes only if they should speak. Answer no if listening is enough."
        )
        questions: dict[str, dict[str, str]] = {}
        for persona_id in sorted(self.member_ids):
            if self.floor == persona_id:
                continue
            name = self.member_names.get(persona_id, persona_id)
            questions[persona_id] = {
                "type": "noul",
                "instructions": template.format(name=name),
            }
        if not questions:
            return None
        client = jev or HttpJevSystemOne()
        result = await client.ask(
            state={"transcript": utterance},
            questions=questions,
            model="jev-latest",
            timeout_seconds=4.0,
        )
        winner: str | None = None
        best = -1.0
        scores: dict[str, float] = {}
        for persona_id in questions:
            probability = parse_noul(result.answers, persona_id)
            scores[persona_id] = probability
            if probability > best:
                best = probability
                winner = persona_id
        self._replace_interest_hands()
        for persona_id, probability in scores.items():
            if _wants_to_add(probability, best):
                self.raise_hand(persona_id)
        logger.info(
            "group voice speaker %s %.2f hands %s scores %s",
            winner,
            best,
            sorted(self.hands),
            {persona_id: round(score, 2) for persona_id, score in scores.items()},
        )
        return winner

    def _replace_interest_hands(self) -> None:
        """Each utterance is a new judgment. A hand from a tool result stays."""
        kept = {persona_id for persona_id in self.hands if self.source_checked.get(persona_id)}
        self.hands.clear()
        self.hands.update(kept)

    def snapshot(self) -> dict[str, Any]:
        """Serializable view for the frontend."""
        floor_name = self.member_names.get(self.floor) if self.floor else None
        return {
            "floor": self.floor,
            "floor_name": floor_name,
            "hands": sorted(self.hands),
            "members": [
                {"id": persona_id, "name": self.member_names.get(persona_id, persona_id)}
                for persona_id in sorted(self.member_ids)
            ],
            "source_checked": [
                pid for pid, checked in self.source_checked.items() if checked
            ],
            "shared_result_count": len(self.shared_results),
        }
