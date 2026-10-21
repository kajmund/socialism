"""Graph identity is independent of source documents and display wording."""

import hashlib

from app.services.graph_v2.errors import PermanentGraphError


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def namespaced(value: str) -> str:
    if "." not in value or value.startswith(".") or value.endswith(".") or value.strip() != value:
        raise PermanentGraphError(f"expected a namespaced graph label: {value!r}")
    return value


def normalized(text: str) -> str:
    # Imported lazily: the knowledge package __init__ pulls in the graph stores.
    from app.services.knowledge.identity import normalize_assertion_text

    result = normalize_assertion_text(text)
    if not result:
        raise PermanentGraphError("graph text must not be empty")
    return result


def weak_node_identity(context_key: str, normalized_name: str) -> str:
    """Keep free text out of storage identities while preserving exact identity."""
    context_hash = stable_id("weak-context", context_key)
    content_hash = stable_id("weak-name", normalized_name)
    return f"weak:{context_hash}:{content_hash}"


def fact_identity(
    *, scope_key: str, source_id: str, target_id: str, predicate: str,
    fact_text: str, context_id: str | None, occurrence_key: str,
) -> str:
    return stable_id(
        scope_key, source_id, target_id, namespaced(predicate),
        context_id or "", occurrence_key, normalized(fact_text),
    )


SOURCE_FACT_IDENTITY_VERSION = "source-fact-v1"


def canonical_encode(payload: dict[str, object]) -> str:
    """Versioned canonical JSON: identity must never depend on key order or formatting."""
    import json

    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def source_fact_identity(
    *,
    scope_key: str,
    source_identity: str,
    document_version_id: str | None,
    source_unit_key: str,
    fact_occurrence_key: str,
) -> str:
    """Deterministic, source-anchored fact identity (see spec: source-fact-v1).

    Two different source occurrences never collide, even when their wording is identical:
    the document version and the source unit are part of the identity.
    """
    payload: dict[str, object] = {
        "identity_version": SOURCE_FACT_IDENTITY_VERSION,
        "scope": scope_key,
        "source_identity": source_identity,
        "source_unit_key": source_unit_key,
        "fact_occurrence_key": fact_occurrence_key,
    }
    if document_version_id is not None:
        payload["document_version_id"] = document_version_id
    return hashlib.sha256(canonical_encode(payload).encode("utf-8")).hexdigest()


def fact_occurrence_selector(*, predicate: str, context_id: str | None, fact_text: str) -> str:
    """Local occurrence selector inside one source unit.

    Precedence belongs to an extractor-provided stable span/occurrence key; this selector is
    the deterministic fallback and is only ever combined with the source unit and version.
    """
    return stable_id(
        "fact-occurrence", namespaced(predicate), context_id or "", normalized(fact_text),
    )
