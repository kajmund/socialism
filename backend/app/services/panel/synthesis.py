"""Structured synthesis of generic_panel transcripts into PanelResult."""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import BaseModel, Field

from app.llm import complete_structured
from app.services.panel.competency import CompetencyState
from app.services.panel.research import MISSING_EXPERTISE_SIGNAL
from app.services.panel.result import (
    MISSING_EXPERTISE_REASON,
    PANEL_RESULT_SCHEMA_CURRENT,
    PanelClaim,
    PanelResult,
    UnansweredItem,
)
from app.services.panel.review_intent import session_brief_for_llm
from app.services.panel.schemas import PanelSessionConfig, PanelTurn
from app.services.prompt_catalog import render_prompt

_EVIDENCE_REF_RE = re.compile(r"\[E(\d+)\]", re.IGNORECASE)
_BARE_EVIDENCE_REF_RE = re.compile(r"^E(\d+)$", re.IGNORECASE)

_RAISE_HAND_TOKENS = frozenset({"JA", "NEJ", "YES", "NO", "RAISE"})
_SCRATCHPAD_MATCH_MIN = 12


class SynthesizedClaim(BaseModel):
    claim: str
    evidence: str
    judgment: str
    dissensus: bool = False
    evidence_refs: list[str] = Field(default_factory=list)


class GenericPanelSynthesis(BaseModel):
    summary: str
    claims: list[SynthesizedClaim] = Field(default_factory=list)
    unanswered: list[str] = Field(default_factory=list)


_PLANNING_PHASES = frozenset({"scratchpad", "research_need", "research_plan"})


def public_transcript_text(transcript: list[PanelTurn]) -> str:
    """Public turns only — scratchpads and research planning are not evidence."""
    lines: list[str] = []
    for turn in transcript:
        if turn.phase in _PLANNING_PHASES:
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


def unanswered_notes_from_transcript(transcript: list[PanelTurn]) -> list[str]:
    return [
        turn.content.strip()
        for turn in transcript
        if turn.phase == "unanswered" and turn.content.strip()
    ]


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
    judgment = item.judgment.strip()
    if not claim or not evidence or not judgment:
        return False
    if _is_raise_hand_only(claim) or _is_raise_hand_only(evidence):
        return False
    if _text_only_in_scratchpad(claim, transcript) or _text_only_in_scratchpad(
        evidence, transcript
    ):
        return False
    return True


def _accepted_claims(
    synthesis: GenericPanelSynthesis,
    transcript: list[PanelTurn],
) -> list[SynthesizedClaim]:
    if not _has_public_expert_substance(transcript):
        return []
    return [row for row in synthesis.claims if _usable_claim(row, transcript)]


def extract_evidence_refs(*texts: str) -> list[str]:
    """Collect ``[E1]``-style refs in first-seen order. Does not invent refs."""
    seen: list[str] = []
    for text in texts:
        for match in _EVIDENCE_REF_RE.finditer(text):
            ref = f"E{int(match.group(1))}"
            if ref not in seen:
                seen.append(ref)
    return seen


def _canonical_evidence_ref(raw: str) -> str | None:
    text = raw.strip()
    match = _BARE_EVIDENCE_REF_RE.fullmatch(text) or _EVIDENCE_REF_RE.fullmatch(text)
    if match is None:
        return None
    return f"E{int(match.group(1))}"


def filter_evidence_refs(
    refs: Iterable[str],
    *,
    allowed: frozenset[str] | None,
) -> list[str]:
    """Keep only refs that exist on the attached frozen EvidenceSet."""
    if allowed is None:
        return []
    kept: list[str] = []
    for raw in refs:
        ref = _canonical_evidence_ref(raw)
        if ref is not None and ref in allowed and ref not in kept:
            kept.append(ref)
    return kept


def _claim_evidence_refs(
    item: SynthesizedClaim,
    *,
    allowed: frozenset[str] | None,
) -> list[str]:
    extracted = extract_evidence_refs(item.claim, item.evidence, item.judgment)
    return filter_evidence_refs([*item.evidence_refs, *extracted], allowed=allowed)


def _unanswered_items_for_result(
    unanswered: list[str],
    *,
    transcript: list[PanelTurn],
    competency: CompetencyState | None,
) -> tuple[list[str], list[UnansweredItem]]:
    """Competency state owns missing_expertise. Moderator prose is presentation."""
    notes = list(unanswered)
    if competency is not None and not competency.has_relevant_expert():
        if not notes:
            notes = unanswered_notes_from_transcript(transcript)
        text = notes[0] if notes else MISSING_EXPERTISE_SIGNAL
        if not notes:
            notes = [text]
        return notes, [UnansweredItem(text=text, reason=MISSING_EXPERTISE_REASON)]
    return notes, [UnansweredItem(text=note) for note in notes]


def panel_result_from_synthesis(
    synthesis: GenericPanelSynthesis,
    *,
    transcript: list[PanelTurn],
    allowed_evidence_refs: frozenset[str] | None = None,
    competency: CompetencyState | None = None,
) -> PanelResult:
    accepted = _accepted_claims(synthesis, transcript)
    claims = [
        PanelClaim(
            claim_id=f"claim_{index}",
            claim=item.claim.strip(),
            evidence=item.evidence.strip(),
            judgment=item.judgment.strip(),
            score=None,
            dissensus=item.dissensus,
            evidence_refs=_claim_evidence_refs(
                item, allowed=allowed_evidence_refs
            ),
        )
        for index, item in enumerate(accepted, start=1)
    ]
    unanswered = [note.strip() for note in synthesis.unanswered if note.strip()]
    if not unanswered and not _has_public_expert_substance(transcript):
        unanswered = unanswered_notes_from_transcript(transcript)
    unanswered, unanswered_items = _unanswered_items_for_result(
        unanswered, transcript=transcript, competency=competency
    )
    filtered = GenericPanelSynthesis(
        summary=synthesis.summary.strip(),
        claims=[
            SynthesizedClaim(
                claim=item.claim.strip(),
                evidence=item.evidence.strip(),
                judgment=item.judgment.strip(),
                dissensus=item.dissensus,
                evidence_refs=claim.evidence_refs,
            )
            for item, claim in zip(accepted, claims, strict=True)
        ],
        unanswered=unanswered,
    )
    return PanelResult(
        schema_version=PANEL_RESULT_SCHEMA_CURRENT,
        protocol="generic_panel",
        summary=filtered.summary,
        claims=claims,
        unanswered=unanswered,
        unanswered_items=unanswered_items,
        competency=list(competency.slots) if competency is not None else [],
        payload={"synthesis": filtered.model_dump(mode="json")},
    )


async def synthesize_generic_panel_result(
    *,
    config: PanelSessionConfig,
    transcript: list[PanelTurn],
    moderator_analysis: str,
    prompts: dict[str, str],
    evidence_prompt: str | None = None,
    allowed_evidence_refs: frozenset[str] | None = None,
    competency: CompetencyState | None = None,
) -> PanelResult:
    brief = session_brief_for_llm(config, prompts)
    messages = [{"role": "system", "content": render_prompt(prompts, "panel.moderator.system")}]
    if brief:
        messages.append({"role": "system", "content": brief})
    if evidence_prompt:
        messages.append({"role": "system", "content": evidence_prompt})
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
    return panel_result_from_synthesis(
        synthesis,
        transcript=transcript,
        allowed_evidence_refs=allowed_evidence_refs,
        competency=competency,
    )
