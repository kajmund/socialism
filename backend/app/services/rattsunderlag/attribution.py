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
_REF_TOKEN = re.compile(r"\[\[ref:[^\]]+\]\]")
_TERMINATORS = frozenset(".!?")

# Swedish legal / citation abbreviations. Combined with "next char is a
# digit or lowercase letter" so "4 kap. 1 §" and "NJA 2018 s. 723" stay intact.
_ABBREVIATIONS = frozenset(
    {
        "kap",
        "prop",
        "s",
        "ref",
        "nr",
        "art",
        "st",
        "mom",
        "p",
        "pkt",
        "jfr",
        "jmf",
        "f",
        "ff",
        "bet",
        "dir",
        "not",
        "par",
        "lit",
        "ex",
        "tex",
        "t.ex",
        "bl.a",
        "bla",
        "m.m",
        "mm",
        "m.fl",
        "mfl",
        "fl",
        "d.v.s",
        "dvs",
        "a.a",
        "a.prop",
        "e.g",
        "i.e",
        "vs",
    }
)


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


def _word_before_period(text: str, index: int) -> str:
    i = index
    while i > 0 and (text[i - 1].isalpha() or text[i - 1] == "."):
        i -= 1
    return text[i:index].lower()


def _is_abbreviation(text: str, period_index: int) -> bool:
    word = _word_before_period(text, period_index)
    if not word:
        return False
    if word in _ABBREVIATIONS:
        return True
    letters = word.replace(".", "")
    return len(letters) == 1 and letters.isalpha()


def _skip_spaces(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _consume_trailing_markers(text: str, index: int) -> int:
    while True:
        nxt = _skip_spaces(text, index)
        match = _REF_TOKEN.match(text, nxt)
        if match is None:
            return index
        index = match.end()


def _is_sentence_boundary(text: str, index: int) -> bool:
    if text[index] not in _TERMINATORS:
        return False
    if text[index] == "." and _is_abbreviation(text, index):
        return False
    look = index + 1
    while look < len(text) and text[look] in _TERMINATORS:
        look += 1
    nxt = _skip_spaces(text, look)
    if nxt >= len(text):
        return True
    if text.startswith("[[ref:", nxt):
        return True
    ch = text[nxt]
    if ch.isdigit() or ch.islower():
        return False
    return True


def split_sentences(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    units: list[str] = []
    start = 0
    i = 0
    n = len(stripped)
    while i < n:
        if _is_sentence_boundary(stripped, i):
            end = i + 1
            while end < n and stripped[end] in _TERMINATORS:
                end += 1
            end = _consume_trailing_markers(stripped, end)
            part = stripped[start:end].strip()
            if part:
                units.append(part)
            start = end
            i = end
            continue
        i += 1
    tail = stripped[start:].strip()
    if tail:
        units.append(tail)
    return units


def apply_attribution(
    text: str,
    known: set[str],
) -> tuple[str, list[SummaryClaim], list[str]]:
    """Keep only citations that match retrieved sources.

    Displayed text never includes ``[[ref:]]`` markers. Valid refs live on
    ``claims`` so a later UI can attach clickable citations.
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
        cleaned_parts.append(body)
        if valid:
            claims.append(SummaryClaim(text=body, source_refs=valid))
        else:
            unanswered.append(body)
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
