"""Deterministic Word paragraph anchors. No domain or LLM matching."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

WordAnchorStatus = Literal["resolved", "stale", "ambiguous", "missing"]


def normalize_word_text(text: str) -> str:
    return text.replace("\r", "").strip()


def hash_word_text(text: str) -> str:
    normalized = normalize_word_text(text)
    return sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WordAnchor:
    paragraph_index: int
    reviewed_text: str
    text_hash: str
    unique_local_id: str | None = None
    previous_text_hash: str | None = None
    next_text_hash: str | None = None


@dataclass(frozen=True)
class WordDocumentParagraphState:
    paragraph_index: int
    text: str
    unique_local_id: str | None = None


@dataclass(frozen=True)
class WordAnchorResolution:
    status: WordAnchorStatus
    paragraph_index: int | None = None


@dataclass(frozen=True)
class _SnapshotItem:
    paragraph_index: int
    text: str
    unique_local_id: str | None


def _optional_id(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def snapshot_paragraphs_from_request(request: dict | None) -> list[_SnapshotItem]:
    if not request:
        return []
    items: list[_SnapshotItem] = []
    seen: set[int] = set()
    for section in request.get("sections") or []:
        if not isinstance(section, dict):
            continue
        heading = section.get("heading")
        heading_index = section.get("heading_paragraph_index")
        if (
            isinstance(heading, str)
            and normalize_word_text(heading)
            and isinstance(heading_index, int)
            and heading_index not in seen
        ):
            items.append(
                _SnapshotItem(
                    paragraph_index=heading_index,
                    text=heading,
                    unique_local_id=_optional_id(section.get("heading_unique_local_id")),
                )
            )
            seen.add(heading_index)
        for paragraph in section.get("paragraphs") or []:
            if not isinstance(paragraph, dict):
                continue
            index = paragraph.get("index")
            text = paragraph.get("text")
            if not isinstance(index, int) or index in seen:
                continue
            items.append(
                _SnapshotItem(
                    paragraph_index=index,
                    text=text if isinstance(text, str) else "",
                    unique_local_id=_optional_id(paragraph.get("unique_local_id")),
                )
            )
            seen.add(index)
    items.sort(key=lambda item: item.paragraph_index)
    return items


def word_anchor_from_snapshot_item(
    items: list[_SnapshotItem],
    position: int,
) -> WordAnchor:
    item = items[position]
    previous_hash = hash_word_text(items[position - 1].text) if position > 0 else None
    next_hash = (
        hash_word_text(items[position + 1].text) if position + 1 < len(items) else None
    )
    return WordAnchor(
        paragraph_index=item.paragraph_index,
        unique_local_id=item.unique_local_id,
        reviewed_text=item.text,
        text_hash=hash_word_text(item.text),
        previous_text_hash=previous_hash,
        next_text_hash=next_hash,
    )


def word_anchor_from_job_request(
    request: dict | None,
    paragraph_index: int,
) -> WordAnchor | None:
    items = snapshot_paragraphs_from_request(request)
    for position, item in enumerate(items):
        if item.paragraph_index == paragraph_index:
            return word_anchor_from_snapshot_item(items, position)
    return None


def reviewed_text_from_job_request(
    request: dict | None,
    paragraph_index: int,
) -> str | None:
    anchor = word_anchor_from_job_request(request, paragraph_index)
    return None if anchor is None else anchor.reviewed_text


def _neighbor_hashes(
    current: list[WordDocumentParagraphState],
    position: int,
) -> tuple[str | None, str | None]:
    previous_hash = hash_word_text(current[position - 1].text) if position > 0 else None
    next_hash = (
        hash_word_text(current[position + 1].text) if position + 1 < len(current) else None
    )
    return previous_hash, next_hash


def _context_matches(
    anchor: WordAnchor,
    previous_hash: str | None,
    next_hash: str | None,
) -> bool:
    has_previous = anchor.previous_text_hash is not None
    has_next = anchor.next_text_hash is not None
    if not has_previous and not has_next:
        return False
    previous_ok = (not has_previous) or previous_hash == anchor.previous_text_hash
    next_ok = (not has_next) or next_hash == anchor.next_text_hash
    return previous_ok and next_ok


def resolve_word_anchor(
    anchor: WordAnchor,
    current: list[WordDocumentParagraphState],
) -> WordAnchorResolution:
    reviewed = normalize_word_text(anchor.reviewed_text)
    if not reviewed:
        return WordAnchorResolution(status="missing")

    by_local_id = {
        paragraph.unique_local_id: paragraph
        for paragraph in current
        if paragraph.unique_local_id
    }
    if anchor.unique_local_id:
        hit = by_local_id.get(anchor.unique_local_id)
        if hit is not None:
            if normalize_word_text(hit.text) == reviewed:
                return WordAnchorResolution(
                    status="resolved",
                    paragraph_index=hit.paragraph_index,
                )
            return WordAnchorResolution(status="stale")

    by_index = {paragraph.paragraph_index: paragraph for paragraph in current}
    at_index = by_index.get(anchor.paragraph_index)
    if at_index is not None and normalize_word_text(at_index.text) == reviewed:
        return WordAnchorResolution(
            status="resolved",
            paragraph_index=at_index.paragraph_index,
        )

    matches = [
        (position, paragraph)
        for position, paragraph in enumerate(current)
        if normalize_word_text(paragraph.text) == reviewed
    ]
    if len(matches) == 1:
        return WordAnchorResolution(
            status="resolved",
            paragraph_index=matches[0][1].paragraph_index,
        )
    if len(matches) > 1:
        disambiguated = [
            paragraph
            for position, paragraph in matches
            if _context_matches(anchor, *_neighbor_hashes(current, position))
        ]
        if len(disambiguated) == 1:
            return WordAnchorResolution(
                status="resolved",
                paragraph_index=disambiguated[0].paragraph_index,
            )
        return WordAnchorResolution(status="ambiguous")

    return WordAnchorResolution(status="missing")
