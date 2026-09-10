"""Deterministic frozen EvidenceSet → compact prompt evidence.

Does not dump provenance JSON. Citation refs are assigned from persisted
ordinal order among ``found`` items only: ``[E1]``, ``[E2]``, …
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.database.models import EvidenceSetItem

_NO_POSITIVE_EVIDENCE = "No positive evidence was found."
_GAPS_HEADER = "Known gaps (not evidence):"


@dataclass(frozen=True)
class EvidenceRef:
    ref: str
    item_id: str
    original_evidence_id: str | None
    ordinal: int


@dataclass(frozen=True)
class RenderedEvidence:
    prompt_body: str
    refs: dict[str, EvidenceRef]
    found_count: int
    gap_count: int

    def mapping(self) -> dict[str, dict[str, str | int | None]]:
        return {
            ref: {
                "item_id": item.item_id,
                "original_evidence_id": item.original_evidence_id,
                "ordinal": item.ordinal,
            }
            for ref, item in self.refs.items()
        }


def _sorted_items(items: Sequence[EvidenceSetItem]) -> list[EvidenceSetItem]:
    return sorted(items, key=lambda item: (item.ordinal, item.id))


def _source_label(item: EvidenceSetItem) -> str:
    for candidate in (item.title, item.source_id, item.source_type):
        if candidate and str(candidate).strip():
            return str(candidate).strip()
    return item.source_type


def _useful_url(url: str | None) -> str | None:
    text = (url or "").strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return None


def _format_found(ref: str, item: EvidenceSetItem) -> str:
    lines = [f"[{ref}] {_source_label(item)}", f"Source type: {item.source_type}"]
    if item.provider and item.provider.strip():
        lines.append(f"Provider: {item.provider.strip()}")
    if item.locator and item.locator.strip():
        lines.append(f"Locator: {item.locator.strip()}")
    if item.excerpt and item.excerpt.strip():
        lines.append(f'Excerpt: "{item.excerpt.strip()}"')
    url = _useful_url(item.source_url)
    if url is not None:
        lines.append(f"URL: {url}")
    return "\n".join(lines)


def _format_gap(item: EvidenceSetItem) -> str:
    detail = ""
    if item.title and item.title.strip():
        detail = item.title.strip()
    elif item.excerpt and item.excerpt.strip():
        detail = item.excerpt.strip()
    parts = [item.status, item.source_type]
    if detail:
        parts.append(detail)
    return "- " + " · ".join(parts)


def render_frozen_evidence(items: Sequence[EvidenceSetItem]) -> RenderedEvidence:
    """Turn frozen items into compact prompt evidence plus a citation map."""
    found_blocks: list[str] = []
    gap_lines: list[str] = []
    refs: dict[str, EvidenceRef] = {}
    found_index = 0
    for item in _sorted_items(items):
        if item.status == "found":
            found_index += 1
            ref = f"E{found_index}"
            refs[ref] = EvidenceRef(
                ref=ref,
                item_id=item.id,
                original_evidence_id=item.original_evidence_id,
                ordinal=item.ordinal,
            )
            found_blocks.append(_format_found(ref, item))
            continue
        gap_lines.append(_format_gap(item))

    if found_blocks:
        found_text = "\n\n".join(found_blocks)
    else:
        found_text = _NO_POSITIVE_EVIDENCE

    sections = [found_text]
    if gap_lines:
        sections.append(_GAPS_HEADER + "\n" + "\n".join(gap_lines))
    return RenderedEvidence(
        prompt_body="\n\n".join(sections),
        refs=refs,
        found_count=len(found_blocks),
        gap_count=len(gap_lines),
    )
