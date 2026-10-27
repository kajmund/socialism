"""Synchronous conditional-mutation worker for the single-writer owner."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from overgraph import OverGraphError

from app.services.overgraph.owner_client import MutationRequest, RECEIPT_LABEL, _record_sample
from app.services.overgraph.search_ledger import SearchChange, append_in_txn, collect_change

if TYPE_CHECKING:
    from app.services.overgraph.owner import OvergraphOwner


def apply_conditional(owner: "OvergraphOwner", request: MutationRequest, payload_hash: str) -> dict[str, Any]:
    read = dict(request.patch["read"])
    expected = dict(request.patch.get("expected") or {})
    increments = list(request.patch.get("increments") or [])
    nodes = list(request.patch.get("upsert_nodes", ()))
    search_changes: list[SearchChange] = []
    for attempt in range(3):
        txn = owner.catalog.begin_write_txn()
        committed = False
        txn_closed = False
        try:
            current = txn.get_node_by_key(str(read["label"]), str(read["key"]))
            if current is None:
                return {"ok": False, "error": "read_not_found", "mutation_id": request.mutation_id}
            props = dict(current.get("props") or {})
            if expected and any(props.get(name) != value for name, value in expected.items()):
                return {"ok": False, "error": "precondition_failed", "mutation_id": request.mutation_id}
            response_props = {name: props.get(name) for name in request.patch.get("result_props", ())}
            for increment in increments:
                name = str(increment["prop"])
                props[name] = int(props.get(name) or 0) + int(increment.get("by", 1))
            for node in nodes:
                txn.upsert_node(
                    list(node["labels"]), str(node["key"]),
                    props=dict(node.get("props") or {}),
                    dense_vector=node.get("dense_vector"),
                )
                collect_change(
                    search_changes, node.get("labels"), str(node["key"]),
                    dict(node.get("props") or {}),
                )
            if nodes and owner._txn_barrier is not None:
                owner._txn_barrier("conditional")
            if increments:
                txn.upsert_node(
                    list(read.get("labels") or [read["label"]]),
                    str(read["key"]),
                    props=props,
                )
            append_in_txn(txn, search_changes)
            txn.upsert_node(
                [RECEIPT_LABEL, "overgraph-owner"], request.mutation_id,
                props={"mutation_id": request.mutation_id, "payload_hash": payload_hash},
            )
            started = time.perf_counter()
            txn.commit()
            _record_sample(owner.metrics.commit_seconds, started)
            committed = True
            owner.metrics.applied += 1
            return {
                "ok": True, "duplicate": False, "mutation_id": request.mutation_id,
                "props": response_props,
            }
        except OverGraphError as exc:
            # Failed commit already closed the txn; do not mask it.
            txn_closed = True
            if "conflict" not in str(exc).lower():
                raise
            owner.metrics.conflicts += 1
            if attempt == 2:
                raise
        finally:
            if not committed and not txn_closed:
                txn.rollback()
    raise RuntimeError("unreachable")

