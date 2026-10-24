"""Write facts and their provenance through the single-writer owner."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.graph_v2.types import FactInput
from app.services.overgraph.labels import (
    CONTRADICTS, CONTEXT, ENTITY, FACT, OBJECT, SUBJECT, SUPPORTS, scope_label,
)
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.write import _merged_fact_props, fact_key_from_anchor


async def write_fact_via_owner(  # noqa: C901, PLR0912
    client: OwnerClient,
    proposed: FactInput,
    *,
    contradiction_key: str | None = None,
    mutation_id: str | None = None,
) -> dict[str, Any]:
    unit_refs = sorted({ref.ref for ref in proposed.sources if ref.kind == "text_unit"})
    unit = await client.read([{"label": "TextUnit", "key": unit_refs[0]}]) if unit_refs else {"values": {}}
    unit_props = unit["values"].get(f"TextUnit:{unit_refs[0]}") if unit_refs else None
    anchor = ((str(unit_props.get("document_version_id") or "") or None), unit_refs[0]) if unit_refs else None
    key = fact_key_from_anchor(proposed, anchor)
    for _attempt in range(3):
        endpoint_keys = [proposed.source_id, proposed.target_id]
        if proposed.context_id:
            endpoint_keys.append(proposed.context_id)
        reads = await client.read([
            {"label": ENTITY, "key": endpoint}
            for endpoint in endpoint_keys
        ] + [{"label": FACT, "key": key}])
        values = reads["values"]
        for endpoint in endpoint_keys:
            if values.get(f"{ENTITY}:{endpoint}") is None:
                raise KeyError(f"fact endpoint {endpoint} is missing")
        existing = values.get(f"{FACT}:{key}")
        merged = _merged_fact_props(
            None if existing is None else _record(key, existing),
            proposed,
        )
        recorded = json.loads(str(existing.get("source_refs_json") or "[]")) if existing else []
        seen = {(item["kind"], item["ref"]) for item in recorded}
        for source in proposed.sources:
            if (source.kind, source.ref) not in seen:
                recorded.append({"kind": source.kind, "ref": source.ref})
                seen.add((source.kind, source.ref))
        merged["source_refs_json"] = json.dumps(recorded, ensure_ascii=False)
        nodes: list[dict[str, Any]] = [{
            "labels": [FACT, scope_label(proposed.scope.scope_key)],
            "key": key, "props": merged,
            "dense_vector": list(proposed.embedding) if proposed.embedding else None,
        }]
        edges: list[dict[str, Any]] = [
            {"from": {"label": FACT, "key": key}, "to": {"label": ENTITY, "key": proposed.source_id}, "label": SUBJECT},
            {"from": {"label": FACT, "key": key}, "to": {"label": ENTITY, "key": proposed.target_id}, "label": OBJECT},
        ]
        if proposed.context_id:
            edges.append({"from": {"label": FACT, "key": key}, "to": {"label": ENTITY, "key": proposed.context_id}, "label": CONTEXT})
        for source in proposed.sources:
            if source.kind == "text_unit":
                origin_key = source.ref
                origin_label = "TextUnit"
            else:
                origin_key = f"episode:{source.ref}"
                origin_label = ENTITY
                nodes.append({"labels": [ENTITY, scope_label(proposed.scope.scope_key)], "key": origin_key, "props": {"scope_key": proposed.scope.scope_key, "node_type": "research.episode", "name": source.ref}})
            edges.append({"from": {"label": origin_label, "key": origin_key}, "to": {"label": FACT, "key": key}, "label": SUPPORTS})
        if contradiction_key:
            edges.append({"from": {"label": FACT, "key": key}, "to": {"label": FACT, "key": contradiction_key}, "label": CONTRADICTS})
        expected: dict[str, Any] = ({"expected_absent": [{"label": FACT, "key": key}]} if existing is None else {"expected_nodes": [{"label": FACT, "key": key, "props": {"source_refs_json": existing.get("source_refs_json", "[]"), "status": existing.get("status")}}]})
        if unit_refs and unit_props is not None:
            expected.setdefault("expected_nodes", []).append({
                "label": "TextUnit", "key": unit_refs[0],
                "props": {"document_version_id": unit_props.get("document_version_id")},
            })
        operation_id = mutation_id or "fact:" + hashlib.sha256(
            json.dumps({"key": key, "refs": recorded}, sort_keys=True).encode()
        ).hexdigest()
        result = await client.mutate(operation_id, {**expected, "upsert_nodes": nodes, "upsert_edges": edges}, kind="batch")
        if result.get("error") == "precondition_failed":
            continue
        return {"key": key, "props": merged, "result": result}
    raise RuntimeError("fact mutation precondition conflict")


def _record(key: str, props: dict[str, Any]):
    from app.services.overgraph.model import GraphRecord
    return GraphRecord(key=key, labels=(FACT,), props=dict(props))
