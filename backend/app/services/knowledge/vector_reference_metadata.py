"""Round-trip canonical source references through scalar-only vector metadata."""

from __future__ import annotations

import json
from collections.abc import Mapping

from app.services.knowledge.provider import KnowledgeVectorStoreError

_REFERENCE_LIST_KEYS = frozenset({
    "text_unit_ids", "supporting_text_unit_ids", "document_ids", "document_version_ids",
})


def encode_reference_lists(source: Mapping[str, object]) -> dict[str, str]:
    """The Storage SDK requires scalar values; identifiers retain their list shape."""
    return {
        key: json.dumps(_string_ids(value, key), separators=(",", ":"))
        for key, value in source.items() if key in _REFERENCE_LIST_KEYS
    }


def decode_reference_lists(metadata: dict[str, object]) -> None:
    for key in _REFERENCE_LIST_KEYS.intersection(metadata):
        value = metadata[key]
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (ValueError, TypeError) as exc:
                raise KnowledgeVectorStoreError(f"Vector {key} is not valid source-reference JSON") from exc
        metadata[key] = _string_ids(value, key)


def _string_ids(value: object, key: str) -> list[str]:
    if not isinstance(value, (list, tuple)) or not all(isinstance(identity, str) for identity in value):
        raise KnowledgeVectorStoreError(f"Vector {key} must contain a list of source-reference identifiers")
    return list(value)
