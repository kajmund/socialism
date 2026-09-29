"""Graph identity is independent of source documents and display wording."""

import hashlib

from app.services.knowledge.identity import normalize_assertion_text


def stable_id(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def namespaced(value: str) -> str:
    if "." not in value or value.startswith(".") or value.endswith(".") or value.strip() != value:
        raise ValueError(f"expected a namespaced graph label: {value!r}")
    return value


def normalized(text: str) -> str:
    result = normalize_assertion_text(text)
    if not result:
        raise ValueError("graph text must not be empty")
    return result


def fact_identity(
    *, scope_key: str, source_id: str, target_id: str, predicate: str,
    fact_text: str, context_id: str | None, occurrence_key: str,
) -> str:
    return stable_id(
        scope_key, source_id, target_id, namespaced(predicate),
        context_id or "", occurrence_key, normalized(fact_text),
    )
