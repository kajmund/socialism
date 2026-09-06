"""Sentence → retrieved-source attribution. Invented citations are stripped."""

from __future__ import annotations

import re

from app.services.rattsunderlag.schemas import (
    ForarbeteRef,
    LagtextRef,
    PraxisRef,
    SummaryClaim,
)

_REF_MARK = re.compile(r"\[\[ref:([^\]]+)\]\]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def known_source_ids(
    *,
    lagtext: list[LagtextRef],
    praxis: list[PraxisRef],
    forarbeten: list[ForarbeteRef],
) -> set[str]:
    ids = {item.sfs_id for item in lagtext}
    ids.update(item.referens for item in praxis)
    ids.update(item.referens for item in forarbeten)
    return ids


def split_sentences(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT.split(stripped) if part.strip()]


def apply_attribution(
    text: str,
    known: set[str],
) -> tuple[str, list[SummaryClaim], list[str]]:
    """Keep only citations that match retrieved sources.

    Sentences without a valid source go in ``unanswered``.
    """
    claims: list[SummaryClaim] = []
    unanswered: list[str] = []
    cleaned_parts: list[str] = []
    for sentence in split_sentences(text):
        refs = [item.strip() for item in _REF_MARK.findall(sentence) if item.strip()]
        valid = [ref for ref in refs if ref in known]
        body = re.sub(r"\s+", " ", _REF_MARK.sub("", sentence)).strip()
        if not body:
            continue
        if valid:
            claims.append(SummaryClaim(text=body, source_refs=valid))
            markers = " ".join(f"[[ref:{ref}]]" for ref in valid)
            cleaned_parts.append(f"{body} {markers}")
        else:
            unanswered.append(body)
            cleaned_parts.append(body)
    return " ".join(cleaned_parts), claims, unanswered


def format_sources_for_prompt(
    *,
    lagtext: list[LagtextRef],
    praxis: list[PraxisRef],
    forarbeten: list[ForarbeteRef],
) -> str:
    lines: list[str] = []
    for item in lagtext:
        lines.append(f"- lagtext {item.sfs_id}: {item.rubrik} — {item.utdrag}")
    for item in praxis:
        lines.append(f"- praxis {item.referens}: {item.instans} — {item.utdrag}")
    for item in forarbeten:
        lines.append(f"- forarbete {item.referens}: {item.titel} — {item.utdrag}")
    return "\n".join(lines)
