"""Search-index change records appended atomically by Owner mutations.

The Owner is the only writer. Every changed TextUnit or Fact is recorded as an
explicit upsert/delete in the same native transaction as the data mutation, and
one durable generation counter is bumped. The Tantivy indexer consumes this
ledger independently; no second writer/change system exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.overgraph.labels import ENTITY, FACT, TEXT_UNIT

GENERATION_LABEL = "SearchIndexGeneration"
CHANGE_LABEL = "SearchIndexChange"
GENERATION_KEY = "search-index:generation"


@dataclass(frozen=True)
class SearchChange:
    kind: str
    op: str
    key: str
    scope_key: str = ""
    document_version_id: str = ""
    ordinal: int = 0


def change_for_node(
    labels: Any, key: str, props: dict[str, Any], *, deleted: bool = False,
) -> SearchChange | None:
    label_set = {str(label) for label in labels or ()}
    if TEXT_UNIT in label_set:
        return SearchChange(
            kind="text_unit", op="delete" if deleted else "upsert", key=key,
            scope_key=str(props.get("scope_key") or ""),
            document_version_id=str(props.get("document_version_id") or ""),
        )
    if FACT in label_set:
        active = not deleted and str(props.get("status") or "") == "active"
        return SearchChange(
            kind="fact", op="upsert" if active else "delete", key=key,
            scope_key=str(props.get("scope_key") or ""),
        )
    return None


def collect_change(
    target: list[SearchChange], labels: Any, key: str, props: dict[str, Any],
    *, deleted: bool = False,
) -> None:
    change = change_for_node(labels, key, props, deleted=deleted)
    if change is not None:
        target.append(change)


def append_in_txn(txn: Any, changes: list[SearchChange]) -> int | None:
    """Bump the durable generation and append change records in the same txn."""
    if not changes:
        return None
    node = txn.get_node_by_key(ENTITY, GENERATION_KEY)
    current = int((node or {}).get("props", {}).get("generation") or 0)
    generation = current + 1
    txn.upsert_node(
        [ENTITY, GENERATION_LABEL], GENERATION_KEY,
        props={"generation": generation},
    )
    for index, change in enumerate(changes):
        txn.upsert_node(
            [ENTITY, CHANGE_LABEL], f"search-index:change:{generation}:{index}",
            props={
                "generation": generation,
                "op": change.op,
                "kind": change.kind,
                "key": change.key,
                "scope_key": change.scope_key,
                "document_version_id": change.document_version_id,
                "ordinal": index,
            },
        )
    return generation
