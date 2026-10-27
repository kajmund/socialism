"""Owner-backed legal claim/evidence operations.

Reads and writes go through the existing Owner protocol; no direct Catalog access.
Claim + evidence + support edges are published in one batch.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.labels import (
    ANSWERED_BY, CLAIM, KNOWLEDGE_QUESTION, TEXT_UNIT, scope_label, visible_scope_keys,
)
from app.services.overgraph.legal_claims import (
    EVIDENCE, HAS_EVIDENCE, SUPPORTED_BY, VERIFIED,
    evidence_key, legal_claim_key,
)
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.claim_answers import ClaimAnswerSource, scope_node_key


class OwnerClaimError(RuntimeError):
    pass


def _ms(value: datetime | None) -> int:
    return int(value.timestamp() * 1000) if value is not None else 0


def _props(response: dict[str, Any], label: str, key: str) -> dict[str, Any] | None:
    return response["values"].get(f"{label}:{key}")


async def _read(client: OwnerClient, label: str, keys: list[str]) -> dict[str, dict[str, Any]]:
    unique = list(dict.fromkeys(keys))
    if not unique:
        return {}
    response = await client.read([{"label": label, "key": key} for key in unique])
    return {
        key: props for key in unique
        if (props := _props(response, label, key)) is not None
    }


def _mutation_id(prefix: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]
    return f"{prefix}:{digest}"


async def _apply(client: OwnerClient, *, mutation_id: str, nodes: list[dict], edges: list[dict]) -> None:
    result = await client.mutate(
        mutation_id, {"upsert_nodes": nodes, "upsert_edges": edges}, kind="batch",
    )
    if result.get("ok") is not True:
        raise OwnerClaimError(f"owner claim mutation failed: {result}")


def _evidence_node(
    *, claim_key: str, version_id: str, unit_ids: list[str],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    previous_units = json.loads(str((previous or {}).get("text_unit_ids_json") or "[]"))
    return {
        "labels": [EVIDENCE],
        "key": evidence_key(claim_key, version_id),
        "props": {
            "claim_key": claim_key,
            "document_version_id": version_id,
            "text_unit_ids_json": json.dumps(sorted(set(previous_units) | set(unit_ids))),
            "provenance_json": "[]",
            "status": "active",
            "valid_from_ms": 0,
            "valid_to_ms": 0,
        },
    }


def _support_edge(*, claim_key: str, version_id: str, unit_id: str, source_ref: str) -> dict[str, Any]:
    return {
        "from": {"label": EVIDENCE, "key": evidence_key(claim_key, version_id)},
        "to": {"label": TEXT_UNIT, "key": unit_id},
        "label": SUPPORTED_BY,
        "props": {
            "provenance_json": json.dumps(
                [{"kind": "text_unit", "ref": unit_id}], ensure_ascii=False, sort_keys=True,
            ),
            "decision": "",
            "verification_version": "",
            "source_ref": source_ref,
        },
    }


async def persist_claim(
    client: OwnerClient, *, scope: KnowledgeTenantScope, predicate: str,
    value: object, unit_ids: tuple[str, ...], key: str | None = None,
) -> str:
    """Atomically publish a logical claim, evidence links and supports."""
    claim_key = key or legal_claim_key(scope, predicate, value)
    if not unit_ids:
        raise OwnerClaimError(f"claim {claim_key} has no supporting TextUnits")
    existing = (await _read(client, CLAIM, [claim_key])).get(claim_key)
    units = await _read(client, TEXT_UNIT, list(unit_ids))
    by_version: dict[str, list[str]] = {}
    for unit_id in unit_ids:
        unit = units.get(unit_id)
        if unit is None:
            continue
        version = str(unit.get("document_version_id") or "")
        if not version:
            raise OwnerClaimError(f"TextUnit {unit_id} has no document version")
        by_version.setdefault(version, []).append(unit_id)
    if not by_version:
        raise OwnerClaimError(f"claim {claim_key} has no readable supporting TextUnits")
    evidence = await _read(client, EVIDENCE, [
        evidence_key(claim_key, version) for version in by_version
    ])
    created_at_ms = int((existing or {}).get("created_at_ms") or 0) or _ms(datetime.now(UTC))
    nodes = [{
        "labels": [CLAIM, scope_label(scope.scope_key)],
        "key": claim_key,
        "props": {
            "scope_key": scope.scope_key,
            "predicate": predicate,
            "value_json": json.dumps(value, ensure_ascii=False, sort_keys=True),
            "status": "active",
            "created_at_ms": created_at_ms,
        },
    }]
    edges = []
    for version, version_units in by_version.items():
        link_key = evidence_key(claim_key, version)
        nodes.append(_evidence_node(
            claim_key=claim_key, version_id=version, unit_ids=version_units,
            previous=evidence.get(link_key),
        ))
        edges.append({
            "from": {"label": CLAIM, "key": claim_key},
            "to": {"label": EVIDENCE, "key": link_key},
            "label": HAS_EVIDENCE,
        })
        for unit_id in version_units:
            edges.append(_support_edge(
                claim_key=claim_key, version_id=version, unit_id=unit_id, source_ref=unit_id,
            ))
    await _apply(
        client, mutation_id=_mutation_id("claim-persist", {"claim": claim_key, "nodes": nodes, "edges": edges}),
        nodes=nodes, edges=edges,
    )
    return claim_key


async def attach_supports(
    client: OwnerClient, *, claim_key: str, unit_ids: tuple[str, ...],
) -> None:
    if not unit_ids:
        return
    units = await _read(client, TEXT_UNIT, list(unit_ids))
    by_version: dict[str, list[str]] = {}
    for unit_id in unit_ids:
        unit = units.get(unit_id)
        if unit is None:
            continue
        by_version.setdefault(str(unit.get("document_version_id") or ""), []).append(unit_id)
    evidence = await _read(client, EVIDENCE, [
        evidence_key(claim_key, version) for version in by_version
    ])
    nodes = []
    edges = []
    for version, version_units in by_version.items():
        nodes.append(_evidence_node(
            claim_key=claim_key, version_id=version, unit_ids=version_units,
            previous=evidence.get(evidence_key(claim_key, version)),
        ))
        for unit_id in version_units:
            edges.append({
                "from": {"label": EVIDENCE, "key": evidence_key(claim_key, version)},
                "to": {"label": TEXT_UNIT, "key": unit_id},
                "label": SUPPORTED_BY,
                "props": {
                    "provenance_json": json.dumps(
                        [{"kind": "text_unit", "ref": unit_id}],
                        ensure_ascii=False, sort_keys=True,
                    ),
                    "decision": "", "verification_version": "", "source_ref": unit_id,
                },
            })
    if nodes:
        await _apply(
            client, mutation_id=_mutation_id("claim-support", {"claim": claim_key, "nodes": nodes, "edges": edges}),
            nodes=nodes, edges=edges,
        )


async def claim_record(client: OwnerClient, *, scope_key: str, identity: str) -> dict[str, Any] | None:
    claim = (await _read(client, CLAIM, [identity])).get(identity)
    if claim is None or str(claim.get("scope_key") or "") != scope_key:
        return None
    return claim


async def find_claim_key(
    client: OwnerClient, *, scope_key: str, identity_value: object, predicate: str,
) -> str | None:
    after = None
    while True:
        page = await client.query_nodes(
            CLAIM, props={"scope_key": scope_key, "predicate": predicate},
            limit=200, after=after,
        )
        for row in page["nodes"]:
            props = dict(row.get("props") or {})
            try:
                value = json.loads(str(props.get("value_json") or ""))
            except (TypeError, ValueError):
                continue
            if value == identity_value:
                return str(row["key"])
        if page.get("next_cursor") is None:
            return None
        after = int(page["next_cursor"])


async def is_superseded(client: OwnerClient, claim_key: str) -> bool:
    claim = (await _read(client, CLAIM, [claim_key])).get(claim_key)
    return claim is not None and str(claim.get("status") or "") == "superseded"


async def evidence_links(client: OwnerClient, claim_key: str) -> list[dict[str, Any]]:
    response = await client.read([{"label": CLAIM, "key": claim_key}])
    claim_id = response["ids"].get(f"{CLAIM}:{claim_key}")
    if claim_id is None:
        return []
    rows = await client.neighbors(claim_id, labels=[HAS_EVIDENCE], limit=200)
    return sorted(
        rows, key=lambda row: str((row.get("props") or {}).get("document_version_id") or ""),
        reverse=True,
    )


async def supporting_text_units(client: OwnerClient, claim_key: str) -> list[str]:
    units: set[str] = set()
    for link in await evidence_links(client, claim_key):
        link_props = dict(link.get("props") or {})
        link_id = link.get("node_id")
        if link_id is None:
            continue
        supported = {
            str(row["key"])
            for row in await client.neighbors(int(link_id), labels=[SUPPORTED_BY], limit=200)
        }
        for unit_id in json.loads(str(link_props.get("text_unit_ids_json") or "[]")):
            if str(unit_id) in supported:
                units.add(str(unit_id))
    return sorted(units)


async def claim_is_verified(client: OwnerClient, claim_key: str, *, now: datetime) -> bool:
    moment = _ms(now)
    for link in await evidence_links(client, claim_key):
        props = dict(link.get("props") or {})
        if str(props.get("status") or "") != "active":
            continue
        if int(props.get("valid_from_ms") or 0) > moment:
            continue
        valid_to = int(props.get("valid_to_ms") or 0)
        if valid_to and moment >= valid_to:
            continue
        link_id = link.get("node_id")
        if link_id is None:
            continue
        supports = {
            str(row["key"]): row
            for row in await client.neighbors(int(link_id), labels=[SUPPORTED_BY], limit=200)
        }
        for unit_id in json.loads(str(props.get("text_unit_ids_json") or "[]")):
            row = supports.get(str(unit_id))
            if row is None:
                continue
            edge_props = dict(row.get("edge_props") or {})
            if str(edge_props.get("decision") or "") != VERIFIED:
                continue
            valid_from = int(row.get("valid_from") or 0)
            valid_to_edge = int(row.get("valid_to") or 0)
            if valid_from > moment:
                continue
            if valid_to_edge and moment >= valid_to_edge:
                continue
            return True
    return False


async def mark_superseded(
    client: OwnerClient, claim_key: str, *, superseded_at: datetime, valid_to: datetime,
    successor_id: str | None,
) -> None:
    claim = (await _read(client, CLAIM, [claim_key])).get(claim_key)
    if claim is None:
        raise OwnerClaimError(f"cannot supersede missing claim {claim_key}")
    props = dict(claim)
    props.update({
        "status": "superseded",
        "superseded_at_ms": _ms(superseded_at),
        "valid_to_ms": _ms(valid_to),
        "successor_key": successor_id or "",
    })
    await _apply(
        client, mutation_id=_mutation_id("claim-supersede", {"claim": claim_key, "props": props}),
        nodes=[{"labels": [CLAIM, scope_label(str(props.get("scope_key") or ""))], "key": claim_key, "props": props}],
        edges=[],
    )


async def unlink_document_versions(client: OwnerClient, document_version_ids: list[str]) -> int:
    removed = 0
    for version in document_version_ids:
        after = None
        while True:
            page = await client.query_nodes(EVIDENCE, props={"document_version_id": version}, limit=200, after=after)
            if page["nodes"]:
                await client.mutate(
                    f"claim-unlink:{version}:{page['nodes'][0]['key']}",
                    {"delete_nodes": [{"label": EVIDENCE, "key": row["key"]} for row in page["nodes"]]},
                    kind="batch",
                )
                removed += len(page["nodes"])
            if page.get("next_cursor") is None:
                break
            after = int(page["next_cursor"])
    return removed

# Claim answer links -------------------------------------------------------



async def link_answer(
    client: OwnerClient, *, claim_key: str, scope: KnowledgeTenantScope,
    question_key: str, research_need_id: str, source: ClaimAnswerSource,
) -> None:
    claim = (await _read(client, CLAIM, [claim_key])).get(claim_key)
    if claim is None:
        raise OwnerClaimError(f"cannot link answer to missing claim {claim_key}")
    question = scope_node_key(scope.scope_key, question_key)
    nodes = [{
        "labels": [KNOWLEDGE_QUESTION, scope_label(scope.scope_key)],
        "key": question,
        "props": {"scope_key": scope.scope_key, "question_key": question_key},
    }]
    edges = [{
        "from": {"label": CLAIM, "key": claim_key},
        "to": {"label": KNOWLEDGE_QUESTION, "key": question},
        "label": ANSWERED_BY,
        "props": {
            "research_need_id": research_need_id,
            "source_type": source.source_type or "",
            "knowledge_question_id": source.knowledge_question_id or "",
            "relation": source.relation,
            "question_key": question_key,
            "created_at_ms": source.created_at_ms,
        },
    }]
    await _apply(
        client,
        mutation_id=_mutation_id("claim-answer", {"claim": claim_key, "need": research_need_id, "question": question}),
        nodes=nodes, edges=edges,
    )


async def answered_claim_ids(
    client: OwnerClient, *, research_need_id: str, claim_ids: tuple[str, ...],
) -> list[str]:
    found = []
    for claim_key in claim_ids:
        response = await client.read([{"label": CLAIM, "key": claim_key}])
        claim_id = response["ids"].get(f"{CLAIM}:{claim_key}")
        if claim_id is None:
            continue
        for row in await client.neighbors(int(claim_id), labels=[ANSWERED_BY], limit=200):
            if str((row.get("edge_props") or {}).get("research_need_id") or "") == research_need_id:
                found.append(claim_key)
                break
    return sorted(found)


async def claim_answer_edges(
    client: OwnerClient, *, customer_id: int, question_key: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    visible = set(visible_scope_keys(customer_id))
    found: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for scope in visible:
        question = scope_node_key(scope, question_key)
        response = await client.read([{"label": KNOWLEDGE_QUESTION, "key": question}])
        question_id = response["ids"].get(f"{KNOWLEDGE_QUESTION}:{question}")
        if question_id is None:
            continue
        for row in await client.neighbors(int(question_id), direction="incoming", labels=[ANSWERED_BY], limit=200):
            props = dict(row.get("props") or {})
            claim_scope = str(props.get("scope_key") or "")
            if claim_scope not in visible:
                continue
            if str(props.get("status") or "active") != "active":
                continue
            found[str(row["key"])] = (row, dict(row.get("edge_props") or {}))
    return [found[key] for key in sorted(found)]
