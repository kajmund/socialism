"""OverGraph-backed SWE run store: durable runs, invocation results, run events.

One catalog directory per customer and top-level feature
(``<root>/workflows/customer_<id>/<feature>``). The catalog opens with
``wal_sync_mode="immediate"``: a committed transition is fsynced before the
driver continues.

Every transition is one OverGraph write transaction. The run snapshot
(status, output, error, timestamps), the new append-only events and the handler
result commit together, so a crash never leaves a half-applied transition
behind.

Recovery replays the deterministic machine under the same run id, input and
start time. Invocations whose result is already persisted are completed from
the graph instead of calling the handler again; the remaining handlers run
again. Handler side effects are therefore at-least-once: exactly-once requires
idempotent handlers.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from overgraph import OverGraph

from app.services.swe_host import WorkflowHostContext, workflow_catalog_dir
from app.swe.run_store import InvocationRecord, RunRecord
from app.services.overgraph.model import GraphRecord

RUN_LABEL = "WorkflowRun"
INVOCATION_LABEL = "WorkflowInvocation"
EVENT_LABEL = "WorkflowRunEvent"

# This catalog stores no vectors; OverGraph still fixes a dimension at open.
WORKFLOW_VECTOR_DIMENSION = 1


def _record(view: object) -> GraphRecord:
    labels = getattr(view, "labels", None) or ()
    if isinstance(labels, str):
        labels = (labels,)
    props = getattr(view, "props", None)
    return GraphRecord(
        key=str(getattr(view, "key", "")),
        labels=tuple(labels),
        props=dict(props or {}),
    )


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(raw: object) -> Any:
    if raw is None or raw == "":
        return None
    return json.loads(str(raw))


def _text(raw: object) -> str:
    return str(raw) if raw is not None else ""


def _nullable(raw: object) -> str | None:
    return None if raw is None or raw == "" else str(raw)


def _scope_label(context: WorkflowHostContext) -> str:
    return f"workflow.customer.{context.customer_id}.{context.feature_id}"


class WorkflowCatalog:
    """Locked wrapper around one workflow OverGraph directory."""

    def __init__(self, db: Any, *, path: Path) -> None:
        self._db = db
        self.path = path
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def sync(self) -> None:
        with self._lock:
            self._db.sync()

    def write(self, nodes: Sequence[Mapping[str, Any]]) -> None:
        """Commit every node in one write transaction, or nothing at all."""
        with self._lock:
            txn = self._db.begin_write_txn()
            committed = False
            try:
                for node in nodes:
                    txn.upsert_node(
                        list(node["labels"]),
                        str(node["key"]),
                        props=dict(node["props"]),
                    )
                txn.commit()
                committed = True
            finally:
                if not committed:
                    txn.rollback()

    def get_by_key(self, label: str, key: str) -> GraphRecord | None:
        with self._lock:
            view = self._db.get_node_by_key(label, key)
        return None if view is None else _record(view)

    def find_records(self, label: str, prop_key: str, prop_value: Any) -> list[GraphRecord]:
        with self._lock:
            ids = self._db.find_nodes(label, prop_key, prop_value).to_list()
            views = self._db.get_nodes(ids)
        return [_record(view) for view in views if view is not None]

    def count_nodes(self, labels: Sequence[str]) -> int:
        with self._lock:
            return int(self._db.count_nodes_by_labels(list(labels)))


def _run_node(run: RunRecord, scope: str) -> dict[str, Any]:
    return {
        "labels": [RUN_LABEL, scope],
        "key": run.run_id,
        "props": {
            "run_id": run.run_id,
            "definition_sha256": run.definition_sha256,
            "status": run.status,
            "input_json": _dump(dict(run.input)),
            "output_json": "" if run.output is None else _dump(run.output),
            "error_json": "" if run.error is None else _dump(dict(run.error)),
            "started_at_ms": run.started_at_ms,
            "updated_at_ms": run.updated_at_ms,
            "finished_at_ms": run.finished_at_ms or 0,
            "last_seq": run.last_seq,
        },
    }


def _event_node(event: Mapping[str, Any], run_id: str, scope: str) -> dict[str, Any]:
    seq = int(event["seq"])
    lineage = event.get("lineage")
    return {
        "labels": [EVENT_LABEL, scope],
        "key": f"{run_id}:{seq}",
        "props": {
            "run_id": run_id,
            "seq": seq,
            "type": str(event["type"]),
            "node_instance_id": _text(event.get("node_instance_id")),
            "node_id": _text(event.get("node_id")),
            "result_ref": _text(event.get("result_ref")),
            "lineage_json": "" if lineage is None else _dump(lineage),
            "payload_json": _dump(event.get("payload")),
        },
    }


def _invocation_node(
    invocation: InvocationRecord, run_id: str, now_ms: int, scope: str,
) -> dict[str, Any]:
    return {
        "labels": [INVOCATION_LABEL, scope],
        "key": invocation.invocation_id,
        "props": {
            "run_id": run_id,
            "invocation_id": invocation.invocation_id,
            "node_id": invocation.node_id,
            "ok": 1 if invocation.ok else 0,
            "value_json": _dump(invocation.value) if invocation.ok else "",
            "error": _text(invocation.error),
            "completed_at_ms": now_ms,
        },
    }


def _parse_run(record: GraphRecord) -> RunRecord:
    props = record.props
    finished_at_ms = int(props.get("finished_at_ms") or 0)
    return RunRecord(
        run_id=str(props.get("run_id") or record.key),
        definition_sha256=str(props.get("definition_sha256") or ""),
        status=str(props.get("status") or "running"),
        input=_loads(props.get("input_json")) or {},
        output=_loads(props.get("output_json")),
        error=_loads(props.get("error_json")),
        started_at_ms=int(props.get("started_at_ms") or 0),
        updated_at_ms=int(props.get("updated_at_ms") or 0),
        finished_at_ms=finished_at_ms or None,
        last_seq=int(props.get("last_seq") or 0),
    )


def _parse_invocation(record: GraphRecord) -> InvocationRecord:
    props = record.props
    ok = bool(int(props.get("ok") or 0))
    return InvocationRecord(
        invocation_id=str(props.get("invocation_id") or record.key),
        node_id=str(props.get("node_id") or ""),
        ok=ok,
        value=_loads(props.get("value_json")) if ok else None,
        error=_nullable(props.get("error")),
    )


def _event_dicts(records: Sequence[GraphRecord], run: RunRecord) -> list[dict[str, Any]]:
    events = [
        {
            "type": str(record.props.get("type") or ""),
            "run_id": run.run_id,
            "seq": int(record.props.get("seq") or 0),
            "definition_sha256": run.definition_sha256,
            "node_instance_id": _nullable(record.props.get("node_instance_id")),
            "node_id": _nullable(record.props.get("node_id")),
            "result_ref": _nullable(record.props.get("result_ref")),
            "payload": _loads(record.props.get("payload_json")),
            "lineage": _loads(record.props.get("lineage_json")),
        }
        for record in records
    ]
    events.sort(key=lambda event: event["seq"])
    return events


def _open_catalog(path: Path) -> WorkflowCatalog:
    path.mkdir(parents=True, exist_ok=True)
    db = OverGraph.open(
        str(path),
        create_if_missing=True,
        dense_vector_dimension=WORKFLOW_VECTOR_DIMENSION,
        dense_vector_metric="cosine",
        wal_sync_mode="immediate",
        edge_uniqueness=True,
    )
    return WorkflowCatalog(db, path=path)


@dataclass(frozen=True)
class WorkflowRunStore:
    """Durable SWE run sink for one customer and feature catalog."""

    catalog: WorkflowCatalog
    context: WorkflowHostContext
    scope: str

    @classmethod
    def open(cls, root: Path, context: WorkflowHostContext) -> WorkflowRunStore:
        path = workflow_catalog_dir(Path(root), context)
        return cls(_open_catalog(path), context, _scope_label(context))

    def close(self) -> None:
        self.catalog.close()

    def sync(self) -> None:
        self.catalog.sync()

    async def record(
        self,
        run: RunRecord,
        *,
        events: Sequence[Mapping[str, Any]] = (),
        invocation: InvocationRecord | None = None,
    ) -> None:
        nodes: list[dict[str, Any]] = [_run_node(run, self.scope)]
        nodes.extend(_event_node(event, run.run_id, self.scope) for event in events)
        if invocation is not None:
            nodes.append(_invocation_node(invocation, run.run_id, run.updated_at_ms, self.scope))
        await asyncio.to_thread(self.catalog.write, nodes)

    async def load_run(self, run_id: str) -> RunRecord | None:
        record = await asyncio.to_thread(self.catalog.get_by_key, RUN_LABEL, run_id)
        return None if record is None else _parse_run(record)

    async def replay_results(self, run_id: str) -> Mapping[str, InvocationRecord]:
        records = await asyncio.to_thread(
            self.catalog.find_records, INVOCATION_LABEL, "run_id", run_id,
        )
        results = [_parse_invocation(record) for record in records]
        return {result.invocation_id: result for result in results}

    async def events(self, run_id: str) -> list[dict[str, Any]]:
        run = await self.load_run(run_id)
        if run is None:
            return []
        records = await asyncio.to_thread(self.catalog.find_records, EVENT_LABEL, "run_id", run_id)
        return _event_dicts(records, run)
