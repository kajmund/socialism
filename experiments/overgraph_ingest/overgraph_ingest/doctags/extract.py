"""Jev tag extraction. One call per document. Catalog injected at runtime."""

from __future__ import annotations

from overgraph_ingest.doctags.catalog import (
    TAG_CLASSES,
    classes_for_type,
    value_criteria,
)
from overgraph_ingest.doctags.source import validate_source
from overgraph_ingest.doctags.variant_a import _proposal, _unique
from overgraph_ingest.jev.client import JevClient, JevError
from overgraph_ingest.jev.questions import parse_confidence
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.tabular.jev_io import proposed_spans

SLOTS = 2
EXTRACT_INSTRUCTIONS = (
    "Extract tags that are present in the listed excerpts. "
    "A tag is a typed value, not the document type. "
    "Pick none when the class is absent or there is no further value. "
    "A document may have several values in the same class. "
    "Do not invent text. Do not treat a valid excerpt as legal proof."
)


def extract_b(
    client: JevClient,
    *,
    relative_path: str,
    document_id: str,
    document_type: str,
    title: str,
    opening: str,
    units: list[StoredUnit],
    model: str,
    timeout_seconds: float,
) -> tuple[list[dict[str, object]], float, int, str]:
    classes = classes_for_type(document_type)
    examined = _priority_units(units, classes)
    spans = proposed_spans(examined)
    excerpt_criteria = {span["id"]: span["text"] for span in spans}
    excerpt_criteria["none"] = "No listed excerpt supports a further tag."
    questions: dict[str, object] = {}
    for tag_class in classes:
        spec = TAG_CLASSES[tag_class]
        criteria = value_criteria(tag_class)
        for slot in range(1, SLOTS + 1):
            questions[f"{tag_class}_value_{slot}"] = {
                "type": "choice",
                "instructions": (
                    f"{EXTRACT_INSTRUCTIONS} "
                    f"Value {slot} for {spec.label} ({tag_class})."
                ),
                "criteria": criteria,
            }
            questions[f"{tag_class}_excerpt_{slot}"] = {
                "type": "choice",
                "instructions": (
                    f"Pick a listed excerpt for value {slot} of {spec.label}. "
                    "Pick none if that value is unused."
                ),
                "criteria": excerpt_criteria,
            }
    result = client.ask(
        state={
            "task": "document_tags",
            "relative_path": relative_path,
            "document_type": document_type,
            "title": title,
            "opening": opening,
            "tag_classes": [
                {
                    "tag_class": tag_class,
                    "label": TAG_CLASSES[tag_class].label,
                    "values": [
                        {"value": item.value, "display_value": item.display_value}
                        for item in TAG_CLASSES[tag_class].values
                    ],
                }
                for tag_class in classes
            ],
            "excerpts": spans,
        },
        questions=questions,
        model=model,
        timeout_seconds=timeout_seconds,
    )
    by_id = {span["id"]: span for span in spans}
    by_key = {unit.key: unit for unit in examined}
    proposals = []
    for tag_class in classes:
        for slot in range(1, SLOTS + 1):
            value, confidence, probabilities = _parse_value(
                result.answers,
                f"{tag_class}_value_{slot}",
                tag_class,
            )
            if value is None:
                continue
            excerpt_id = _parse_excerpt(
                result.answers,
                f"{tag_class}_excerpt_{slot}",
                set(excerpt_criteria),
            )
            span = by_id.get(excerpt_id)
            unit = by_key.get(span["unit_id"]) if span else None
            excerpt = span["text"] if span else ""
            source = validate_source(excerpt, unit=unit, document_id=document_id)
            proposals.append(
                _proposal(
                    relative_path,
                    document_id,
                    tag_class,
                    value,
                    source,
                    method="jev",
                    model=str(result.model or model),
                    confidence=confidence,
                    probabilities=probabilities,
                )
            )
    return _unique(proposals), result.latency_ms, 1, str(result.model or model)


def _priority_units(units: list[StoredUnit], classes: tuple[str, ...]) -> list[StoredUnit]:
    needles = [
        needle
        for tag_class in classes
        for needle in TAG_CLASSES[tag_class].needles
    ]
    if not needles:
        return units[:8]
    matched = [
        unit
        for unit in units
        if any(needle in unit.text.casefold() for needle in needles)
    ]
    return matched or units[:8]


def _parse_value(
    answers: dict[str, object],
    key: str,
    tag_class: str,
) -> tuple[str | None, float | None, dict[str, object] | None]:
    row = answers.get(key)
    if not isinstance(row, dict):
        raise JevError(f"Jev response missing choice for {key}", category="schema_validation")
    raw = str(row.get("choice") or "").strip()
    if raw in {"", "none"}:
        return None, parse_confidence(row, key=key), _distribution(row)
    allowed = {item.value: item.value for item in TAG_CLASSES[tag_class].values}
    allowed.update({item.display_value.casefold(): item.value for item in TAG_CLASSES[tag_class].values})
    value = allowed.get(raw) or allowed.get(raw.casefold())
    if value is None:
        raise JevError(f"invalid Jev tag value {raw!r} for {key}", category="schema_validation")
    return value, parse_confidence(row, key=key), _distribution(row)


def _parse_excerpt(answers: dict[str, object], key: str, allowed: set[str]) -> str:
    row = answers.get(key)
    if not isinstance(row, dict):
        raise JevError(f"Jev response missing choice for {key}", category="schema_validation")
    choice = str(row.get("choice") or "").strip()
    if choice not in allowed:
        raise JevError(f"invalid Jev excerpt {choice!r} for {key}", category="schema_validation")
    return choice


def _distribution(row: dict[str, object]) -> dict[str, object] | None:
    for name in ("probabilities", "distribution", "scores"):
        value = row.get(name)
        if isinstance(value, dict):
            return {str(key): value[key] for key in value}
    return None


def document_title(units: list[StoredUnit], relative_path: str) -> str:
    if units:
        first = units[0].text.strip().splitlines()
        if first:
            return first[0][:160]
    return relative_path


def document_opening(units: list[StoredUnit], chars: int = 400) -> str:
    return "".join(unit.text for unit in units)[:chars]
