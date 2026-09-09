"""Structured synthesis of generic_panel transcripts into PanelResult."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.llm import complete_structured
from app.services.panel.result import PanelClaim, PanelResult
from app.services.panel.schemas import PanelSessionConfig, PanelTurn
from app.services.prompt_catalog import render_prompt

_RAISE_HAND_TOKENS = frozenset({"JA", "NEJ", "YES", "NO", "RAISE"})
_SCRATCHPAD_MATCH_MIN = 12


class SynthesizedClaim(BaseModel):
    claim: str
    evidence: str
    judgment: str
    dissensus: bool = False


class GenericPanelSynthesis(BaseModel):
    summary: str
    claims: list[SynthesizedClaim] = Field(default_factory=list)
    unanswered: list[str] = Field(default_factory=list)


def public_transcript_text(transcript: list[PanelTurn]) -> str:
    """Public turns only — scratchpads are never synthesis evidence."""
    lines: list[str] = []
    for turn in transcript:
        if turn.phase == "scratchpad":
            continue
        if turn.phase == "raise_hand":
            lines.append(f"{turn.speaker} (raise_hand): {turn.content}")
            continue
        lines.append(f"{turn.speaker}: {turn.content}")
    return "\n".join(lines)


def _expert_list(config: PanelSessionConfig) -> str:
    return "\n".join(
        f"- {slot.label}: {slot.profile or slot.label}" for slot in config.expert_slots
    )


def _has_public_expert_substance(transcript: list[PanelTurn]) -> bool:
    return any(turn.phase == "expert" and turn.content.strip() for turn in transcript)


def _is_raise_hand_only(text: str) -> bool:
    tokens = [
        part.strip().upper().rstrip(".!,")
        for part in text.replace("/", " ").split()
    ]
    return bool(tokens) and all(token in _RAISE_HAND_TOKENS for token in tokens)


def _text_only_in_scratchpad(text: str, transcript: list[PanelTurn]) -> bool:
    needle = text.strip()
    if len(needle) < _SCRATCHPAD_MATCH_MIN:
        return False
    in_scratch = any(
        turn.phase == "scratchpad" and needle in turn.content for turn in transcript
    )
    if not in_scratch:
        return False
    return needle not in public_transcript_text(transcript)


def _usable_claim(item: SynthesizedClaim, transcript: list[PanelTurn]) -> bool:
    claim = item.claim.strip()
    evidence = item.evidence.strip()
    if not claim:
        return False
    if _is_raise_hand_only(claim) or _is_raise_hand_only(evidence):
        return False
    if _text_only_in_scratchpad(claim, transcript) or _text_only_in_scratchpad(
        evidence, transcript
    ):
        return False
    return True


def panel_result_from_synthesis(
    synthesis: GenericPanelSynthesis,
    *,
    transcript: list[PanelTurn],
) -> PanelResult:
    raw_claims = synthesis.claims
    if not _has_public_expert_substance(transcript):
        raw_claims = []
    claims = [
        PanelClaim(
            claim_id=f"claim_{index}",
            claim=item.claim.strip(),
            evidence=item.evidence.strip(),
            judgment=item.judgment.strip(),
            score=None,
            dissensus=item.dissensus,
        )
        for index, item in enumerate(
            (row for row in raw_claims if _usable_claim(row, transcript)),
            start=1,
        )
    ]
    unanswered = [note.strip() for note in synthesis.unanswered if note.strip()]
    return PanelResult(
        protocol="generic_panel",
        summary=synthesis.summary.strip(),
        claims=claims,
        unanswered=unanswered,
        payload={"synthesis": synthesis.model_dump(mode="json")},
    )


async def synthesize_generic_panel_result(
    *,
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    moderator_analysis: str,
    prompts: dict[str, str],
) -> PanelResult:
    brief = (config.brief or "").strip()
    messages = [{"role": "system", "content": render_prompt(prompts, "panel.moderator.system")}]
    if brief:
        messages.append({"role": "system", "content": brief})
    messages.append(
        {
            "role": "user",
            "content": render_prompt(
                prompts,
                "panel.generic.synthesis",
                topic=config.topic,
                brief=brief or config.topic,
                expert_list=_expert_list(config),
                transcript=public_transcript_text(transcript),
                moderator_analysis=moderator_analysis,
            ),
        }
    )
    synthesis = await complete_structured(messages, GenericPanelSynthesis)
    return panel_result_from_synthesis(synthesis, transcript=transcript)
