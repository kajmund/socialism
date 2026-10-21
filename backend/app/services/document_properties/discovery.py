"""Deterministic document-property discovery. No LLM.

Groups TextUnits by document version and matches frozen taxonomy markers to
propose typed properties with source grounding. High recall; never turns a
lexical match into a verified legal fact on its own.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Protocol, Sequence

from app.services.document_properties.model import (
    EXTRACTION_DETERMINISTIC,
    POLARITY_NEGATIVE,
    POLARITY_POSITIVE,
    POLARITY_UNCLEAR,
    DocumentProperty,
)
from app.services.document_properties.taxonomy import (
    TAXONOMY,
    TAXONOMY_VERSION,
    PropertyClass,
)


class TextUnitLike(Protocol):
    id: str
    text: str
    document_id: str
    document_version_id: str


def extract_document_properties(
    units: Sequence[TextUnitLike],
    taxonomy: dict[str, PropertyClass] | None = None,
) -> list[DocumentProperty]:
    classes = taxonomy or TAXONOMY
    by_version: dict[str, list[TextUnitLike]] = defaultdict(list)
    for unit in units:
        by_version[unit.document_version_id].append(unit)

    output: list[DocumentProperty] = []
    for local in by_version.values():
        document_id = local[0].document_id
        document_version_id = local[0].document_version_id
        proposed = _propose(document_id, document_version_id, local, classes)
        output.extend(_apply_composites(proposed, classes))
    return output


def _propose(
    document_id: str,
    document_version_id: str,
    local: list[TextUnitLike],
    taxonomy: dict[str, PropertyClass],
) -> list[DocumentProperty]:
    proposed: list[DocumentProperty] = []
    for class_id, spec in taxonomy.items():
        body, negative = _match_units(local, spec)
        if body:
            proposed.append(
                _property(
                    document_id, document_version_id, spec, polarity=POLARITY_POSITIVE, matched=body
                )
            )
        elif negative:
            proposed.append(
                _property(
                    document_id, document_version_id, spec, polarity=POLARITY_NEGATIVE, matched=negative
                )
            )
    return proposed


def _match_units(
    local: list[TextUnitLike],
    spec: PropertyClass,
) -> tuple[list[TextUnitLike], list[TextUnitLike]]:
    body: list[TextUnitLike] = []
    negative: list[TextUnitLike] = []
    for unit in local:
        if _matches(unit.text, spec.negative_markers):
            negative.append(unit)
        elif _matches(unit.text, spec.positive_markers):
            body.append(unit)
    return body, negative


def _property(
    document_id: str,
    document_version_id: str,
    spec: PropertyClass,
    *,
    polarity: str,
    matched: list[TextUnitLike],
) -> DocumentProperty:
    return DocumentProperty(
        class_id=spec.class_id,
        document_id=document_id,
        document_version_id=document_version_id,
        value=_value(spec, polarity, matched),
        polarity=polarity,
        taxonomy_version=TAXONOMY_VERSION,
        source_unit_keys=tuple(unit.id for unit in matched),
        extraction_origin=EXTRACTION_DETERMINISTIC,
    )


def _value(spec: PropertyClass, polarity: str, matched: list[TextUnitLike]) -> object:
    if spec.value_type == "jurisdiction":
        return "Sweden" if any("svensk" in unit.text.casefold() for unit in matched) else "Other"
    if spec.value_type == "boolean":
        return polarity == POLARITY_POSITIVE
    return ""


def _apply_composites(
    properties: list[DocumentProperty],
    taxonomy: dict[str, PropertyClass],
) -> list[DocumentProperty]:
    supported = {item.class_id for item in properties if item.polarity == POLARITY_POSITIVE}
    output: list[DocumentProperty] = []
    for item in properties:
        spec = taxonomy.get(item.class_id)
        if (
            spec is not None
            and spec.composite_requires
            and item.polarity == POLARITY_POSITIVE
            and not set(spec.composite_requires).issubset(supported)
        ):
            item = replace(item, polarity=POLARITY_UNCLEAR, source_unit_keys=())
        output.append(item)
    return output


def _matches(text: str, markers: tuple[str, ...]) -> bool:
    folded = _normalize(text)
    return any(marker.casefold() in folded for marker in markers)


def _normalize(text: str) -> str:
    return " ".join(text.split()).casefold()
