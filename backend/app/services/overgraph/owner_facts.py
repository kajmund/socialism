"""Write facts, provenance and research answer publications through the owner.

The owner is the only writer. This module builds the same node/edge payload the
direct writers in :mod:`app.services.overgraph.write` build, but sends it as one
idempotent mutation so a fact, its endpoints and its provenance can never be
half-written.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.services.graph_v2.errors import PermanentGraphError
from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.answers import (
    ANSWER_PREDICATE,
    ANSWER_TYPE,
    QUESTION_NS,
    QUESTION_TYPE,
)
from app.services.overgraph.isolation import can_reference
from app.services.overgraph.labels import (
    CONTRADICTS,
    CONTEXT,
    DEPENDS_ON,
    ENTITY,
    FACT,
    OBJECT,
    SUBJECT,
    SUPPORTS,
    TEXT_UNIT,
    scope_label,
)
from app.services.overgraph.model import GraphRecord
from app.services.overgraph.owner import OwnerClient, OwnerProtocolError
from app.services.overgraph.write import (
    _merged_fact_props,
    _ms,
    _now_ms,
    entity_key,
    entity_nodes,
    fact_key_from_anchor,
)

if TYPE_CHECKING:
    from app.services.overgraph.publish import AnswerPublish

CONFLICT_ATTEMPTS = 3
SOURCE_UNIT_SOURCE = "text_unit"


def _unit_refs(proposed: FactInput) -> list[str]:
    return sorted({ref.ref for ref in proposed.sources if ref.kind == SOURCE_UNIT_SOURCE})


def _recorded_sources(
    existing_props: dict[str, Any] | None, sources: Sequence[SourceRef],
) -> list[dict[str, str]]:
    raw = (existing_props or {}).get("source_refs_json") or "[]"
    recorded = [dict(item) for item in json.loads(str(raw))]
    seen = {(item["kind"], item["ref"]) for item in recorded}
    for source in sources:
        if (source.kind, source.ref) not in seen:
            recorded.append({"kind": source.kind, "ref": source.ref})
            seen.add((source.kind, source.ref))
    return recorded


def _fact_props(
    existing_props: dict[str, Any] | None, proposed: FactInput,
) -> dict[str, Any]:
    existing = (
        None if existing_props is None
        else GraphRecord(key="", labels=(FACT,), props=dict(existing_props))
    )
    props = _merged_fact_props(existing, proposed)
    props["source_refs_json"] = json.dumps(
        _recorded_sources(existing_props, proposed.sources), ensure_ascii=False,
    )
    return props


def _fact_node(key: str, proposed: FactInput, props: dict[str, Any]) -> dict[str, Any]:
    return {
        "labels": [FACT, scope_label(proposed.scope.scope_key)],
        "key": key,
        "props": props,
        "dense_vector": list(proposed.embedding) if proposed.embedding else None,
    }


def _provenance(
    key: str, proposed: FactInput,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Episode nodes plus one SUPPORTS edge per source, matching direct attach_sources."""
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_episodes: set[str] = set()
    recorded_at = _now_ms()
    for source in proposed.sources:
        if source.kind == SOURCE_UNIT_SOURCE:
            origin_label, origin_key = TEXT_UNIT, source.ref
        elif source.kind == "episode":
            origin_label, origin_key = ENTITY, f"episode:{source.ref}"
            if origin_key not in seen_episodes:
                seen_episodes.add(origin_key)
                nodes.append({
                    "labels": [ENTITY, scope_label(proposed.scope.scope_key)],
                    "key": origin_key,
                    "props": {
                        "scope_key": proposed.scope.scope_key,
                        "node_type": "research.episode",
                        "name": source.ref,
                    },
                })
        else:
            raise PermanentGraphError("unsupported provenance kind")
        edges.append({
            "from": {"label": origin_label, "key": origin_key},
            "to": {"label": FACT, "key": key},
            "label": SUPPORTS,
            "props": {
                "source_kind": source.kind,
                "source_ref": source.ref,
                "recorded_at": recorded_at,
            },
        })
    return nodes, edges


def _fact_edges(
    key: str,
    proposed: FactInput,
    *,
    contradiction_key: str | None,
    contradiction_exists: bool,
) -> list[dict[str, Any]]:
    valid_from = _ms(proposed.valid_at)
    edges = [
        {
            "from": {"label": FACT, "key": key},
            "to": {"label": ENTITY, "key": proposed.source_id},
            "label": SUBJECT,
            "valid_from": valid_from,
        },
        {
            "from": {"label": FACT, "key": key},
            "to": {"label": ENTITY, "key": proposed.target_id},
            "label": OBJECT,
            "valid_from": valid_from,
        },
    ]
    if proposed.context_id:
        edges.append({
            "from": {"label": FACT, "key": key},
            "to": {"label": ENTITY, "key": proposed.context_id},
            "label": CONTEXT,
            "valid_from": valid_from,
        })
    if contradiction_exists and contradiction_key is not None:
        left, right = sorted((key, contradiction_key))
        edges.append({
            "from": {"label": FACT, "key": left},
            "to": {"label": FACT, "key": right},
            "label": CONTRADICTS,
        })
    return edges


def _expected_fact(
    key: str,
    existing_props: dict[str, Any] | None,
    *,
    unit: tuple[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    if existing_props is None:
        expected: dict[str, Any] = {"expected_absent": [{"label": FACT, "key": key}]}
    else:
        expected = {"expected_nodes": [{
            "label": FACT,
            "key": key,
            "props": {
                "source_refs_json": existing_props.get("source_refs_json", "[]"),
                "status": existing_props.get("status"),
            },
        }]}
    if unit is not None:
        unit_key, unit_props = unit
        expected.setdefault("expected_nodes", []).append({
            "label": TEXT_UNIT,
            "key": unit_key,
            "props": {"document_version_id": unit_props.get("document_version_id")},
        })
    return expected


def _mutation_id(prefix: str, patch: dict[str, Any]) -> str:
    canonical = json.dumps(patch, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}:" + hashlib.sha256(canonical.encode()).hexdigest()


def _require_ok(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("ok") is True:
        return result
    error = result.get("error")
    if error == "idempotency_conflict":
        raise OwnerProtocolError(
            f"mutation id was reused with a different payload: {result.get('mutation_id')}"
        )
    raise OwnerProtocolError(f"owner mutation failed: {error}")


def _read_values(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("ok") is not True:
        raise OwnerProtocolError(f"owner read failed: {response.get('error')}")
    return dict(response.get("values") or {})


async def _read_units(client: OwnerClient, unit_refs: Sequence[str]) -> dict[str, Any]:
    if not unit_refs:
        return {}
    response = await client.read([{"label": TEXT_UNIT, "key": ref} for ref in unit_refs])
    return _read_values(response)


def _resolve_anchor(
    values: dict[str, Any], unit_refs: Sequence[str], scope: KnowledgeTenantScope,
) -> tuple[tuple[str | None, str] | None, tuple[str, dict[str, Any]] | None]:
    props = _source_units(values, unit_refs, scope)
    if not props:
        return None, None
    unit_key = unit_refs[0]
    version = str(props[0].get("document_version_id") or "") or None
    return (version, unit_key), (unit_key, dict(props[0]))


def _source_units(
    values: dict[str, Any], unit_refs: Sequence[str], scope: KnowledgeTenantScope,
) -> list[dict[str, Any]]:
    """Validate every provenance unit before the batch, as the direct path does."""
    units: list[dict[str, Any]] = []
    for unit_key in unit_refs:
        props = values.get(f"{TEXT_UNIT}:{unit_key}")
        if props is None or not can_reference(scope, str(props.get("scope_key") or "")):
            raise PermanentGraphError("TextUnit provenance is missing or outside tenant scope")
        units.append(dict(props))
    return units


@dataclass(frozen=True)
class _PreparedFact:
    key: str
    unit: tuple[str, dict[str, Any]] | None
    endpoint_keys: tuple[str, ...]
    entity_payload: tuple[dict[str, Any], ...]
    entity_keys: frozenset[str]


def _endpoint_keys(proposed: FactInput) -> tuple[str, ...]:
    keys = [proposed.source_id, proposed.target_id]
    if proposed.context_id:
        keys.append(proposed.context_id)
    return tuple(keys)


async def _prepare_fact(
    client: OwnerClient, proposed: FactInput, entities: Sequence[NodeInput],
) -> _PreparedFact:
    unit_refs = _unit_refs(proposed)
    unit_values = await _read_units(client, unit_refs)
    anchor, unit = _resolve_anchor(unit_values, unit_refs, proposed.scope)
    key = fact_key_from_anchor(proposed, anchor)
    payload: list[dict[str, Any]] = []
    entity_keys: set[str] = set()
    for entity in entities:
        entity_key_value, entity_payload = entity_nodes(entity)
        entity_keys.add(entity_key_value)
        payload.extend(entity_payload)
    return _PreparedFact(
        key=key,
        unit=unit,
        endpoint_keys=_endpoint_keys(proposed),
        entity_payload=tuple(payload),
        entity_keys=frozenset(entity_keys),
    )


def _validate_endpoints(
    values: dict[str, Any],
    endpoint_keys: Iterable[str],
    scope: KnowledgeTenantScope,
    *,
    new_endpoints: frozenset[str],
) -> None:
    for endpoint in endpoint_keys:
        if endpoint in new_endpoints:
            continue
        props = values.get(f"{ENTITY}:{endpoint}")
        if props is None or not can_reference(scope, str(props.get("scope_key") or "")):
            raise PermanentGraphError("fact endpoint is missing or outside tenant scope")


async def _read_fact_values(
    client: OwnerClient,
    key: str,
    endpoint_keys: Sequence[str],
    *,
    contradiction_key: str | None,
    dependency_ids: Sequence[str],
) -> dict[str, Any]:
    reads = [{"label": ENTITY, "key": endpoint} for endpoint in endpoint_keys]
    reads.append({"label": FACT, "key": key})
    if contradiction_key is not None:
        reads.append({"label": FACT, "key": contradiction_key})
    reads.extend({"label": FACT, "key": ref} for ref in dependency_ids)
    return _read_values(await client.read(reads))


def _fact_patch(
    prepared: _PreparedFact,
    proposed: FactInput,
    *,
    existing: dict[str, Any] | None,
    contradiction_key: str | None,
    contradiction_exists: bool,
    dependency_ids: Sequence[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    props = _fact_props(existing, proposed)
    provenance_nodes, provenance_edges = _provenance(prepared.key, proposed)
    nodes = [
        *prepared.entity_payload,
        _fact_node(prepared.key, proposed, props),
        *provenance_nodes,
    ]
    if any(source.kind == "text_unit" for source in proposed.sources):
        # Marker in the same atomic mutation; deterministic for a fact payload,
        # so a receipted retry does not apply another marker change.
        from app.services.overgraph.research import scope_index_node

        nodes.append(scope_index_node(proposed.scope.scope_key))
    edges = [
        *provenance_edges,
        *_fact_edges(
            prepared.key,
            proposed,
            contradiction_key=contradiction_key,
            contradiction_exists=contradiction_exists,
        ),
    ]
    edges.extend({
        "from": {"label": ENTITY, "key": proposed.source_id},
        "to": {"label": FACT, "key": ref},
        "label": DEPENDS_ON,
    } for ref in dependency_ids)
    patch = {
        **_expected_fact(prepared.key, existing, unit=prepared.unit),
        "upsert_nodes": nodes,
        "upsert_edges": edges,
    }
    return patch, props


async def write_fact_via_owner(
    client: OwnerClient,
    proposed: FactInput,
    *,
    contradiction_key: str | None = None,
    mutation_id: str | None = None,
    on_conflict: Callable[[], None] | None = None,
    entities: Sequence[NodeInput] = (),
    dependency_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Upsert one fact and its provenance in a single owner batch.

    ``entities`` are written in the same atomic mutation (a research answer's
    question/answer nodes), and ``dependency_ids`` become DEPENDS_ON edges from
    the fact's source entity to existing facts. A dependency id equal to the
    fact being written is allowed and links the source entity to that new fact
    (question decomposition). Preconditions make the
    read-modify-write merge safe: a concurrent provenance merge, or a TextUnit
    that moved to a newer document version, fails the batch and is re-read
    instead of overwriting the newer state.
    """
    dependencies = tuple(dict.fromkeys(dependency_ids))
    for _attempt in range(CONFLICT_ATTEMPTS):
        # Re-read the anchor every attempt: a concurrent re-ingest moves the
        # TextUnit to a new document version and therefore to a new fact key.
        prepared = await _prepare_fact(client, proposed, entities)
        values = await _read_fact_values(
            client, prepared.key, prepared.endpoint_keys,
            contradiction_key=contradiction_key, dependency_ids=dependencies,
        )
        _validate_endpoints(
            values, prepared.endpoint_keys, proposed.scope,
            new_endpoints=prepared.entity_keys,
        )
        existing = values.get(f"{FACT}:{prepared.key}")
        contradiction_exists = (
            contradiction_key is not None
            and values.get(f"{FACT}:{contradiction_key}") is not None
        )
        available_dependencies = [
            ref for ref in dependencies
            if ref == prepared.key or values.get(f"{FACT}:{ref}") is not None
        ]
        patch, props = _fact_patch(
            prepared,
            proposed,
            existing=existing,
            contradiction_key=contradiction_key,
            contradiction_exists=contradiction_exists,
            dependency_ids=available_dependencies,
        )
        result = await client.mutate_with_retry(
            mutation_id or _mutation_id("fact", patch), patch, kind="batch",
        )
        if result.get("error") == "precondition_failed":
            if on_conflict is not None:
                on_conflict()
            continue
        _require_ok(result)
        return {"key": prepared.key, "props": props, "result": result}
    raise RuntimeError("fact mutation precondition conflict")


def _answer_entities(published: AnswerPublish) -> tuple[NodeInput, NodeInput]:
    source = NodeInput(
        node_type=QUESTION_TYPE,
        name=published.question_text,
        scope=published.scope,
        identifier_namespace=QUESTION_NS,
        identifier=published.question_id,
        attributes={"canonical_question_id": published.question_id},
    )
    target = NodeInput(
        node_type=ANSWER_TYPE,
        name=published.question_text,
        scope=published.scope,
        identifier_namespace="research.answer_id",
        identifier=published.identity,
        attributes={
            "basis": published.basis,
            "assessment": published.assessment,
            "evidence_set_id": published.evidence_set_id,
        },
    )
    return source, target


def _answer_fact(published: AnswerPublish, source_key: str, target_key: str) -> FactInput:
    return FactInput(
        source_id=source_key,
        target_id=target_key,
        scope=published.scope,
        predicate=ANSWER_PREDICATE,
        fact_text=published.question_text,
        sources=(SourceRef("episode", published.evidence_set_id),),
        occurrence_key=published.identity,
        attributes=published.attributes,
    )


def answer_fact_key(published: AnswerPublish) -> str:
    """Content-addressed answer fact key, computed from the shared identity builders."""
    source, target = _answer_entities(published)
    proposed = _answer_fact(published, entity_key(source), entity_key(target))
    return fact_key_from_anchor(proposed, None)


async def publish_answer_via_owner(
    client: OwnerClient,
    published: AnswerPublish,
) -> str:
    """Publish a frozen research answer through the common owner fact writer.

    The question node, answer node, answer fact, provenance edge and dependency
    edges commit together; there is no split direct write and no fallback.
    """
    source, target = _answer_entities(published)
    proposed = _answer_fact(
        published, entity_key(source), entity_key(target),
    )
    result = await write_fact_via_owner(
        client,
        proposed,
        entities=(source, target),
        dependency_ids=tuple(dict.fromkeys(published.dependency_ids)),
    )
    return str(result["key"])
