"""Durable generation/tombstone ledger for the derived Tantivy index.

The ledger is stored in the same OverGraph catalog as the authoritative data and
is mutated through the existing Owner batch protocol, including its native
generation counter. No new owner protocol or separate change system is added.

A generation is bumped atomically with the explicit upsert/delete change
records. The Tantivy checkpoint advances only after the index writes have been
committed, so replay after a crash is idempotent.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.services.overgraph.labels import ENTITY, FACT, TEXT_UNIT
from app.services.overgraph.model import GraphRecord
from app.services.overgraph.owner import OwnerClient
from app.services.tantivy_documents import FactDoc, TextUnitDoc, _fact, _unit
from app.services.tantivy_index import TextUnitIndex, build_from_overgraph

GENERATION_LABEL = "SearchIndexGeneration"
CHANGE_LABEL = "SearchIndexChange"
GENERATION_KEY = "search-index:generation"
CHECKPOINT_FILE = "generation.json"
CHANGE_KIND = Literal["text_unit", "fact"]
CHANGE_OP = Literal["upsert", "delete"]


class SearchIndexLagError(RuntimeError):
    """The derived index is behind the durable Owner generation."""


class SearchIndexRebuildRequired(RuntimeError):
    """The checkpoint is beyond the ledger (or records are missing)."""


@dataclass(frozen=True)
class SearchChange:
    kind: CHANGE_KIND
    op: CHANGE_OP
    key: str
    scope_key: str = ""
    document_version_id: str = ""


def _generation_node() -> dict[str, Any]:
    return {
        "labels": [ENTITY, GENERATION_LABEL],
        "key": GENERATION_KEY,
        "props": {"generation": 0},
    }


async def ensure_generation(client: OwnerClient) -> int:
    """Create the generation node at 0 if the catalog has none."""
    response = await client.read([{"label": ENTITY, "key": GENERATION_KEY}])
    props = response["values"].get(f"{ENTITY}:{GENERATION_KEY}")
    if props is not None:
        return int(props.get("generation") or 0)
    await client.mutate(
        "search-index-generation-init",
        {"upsert_nodes": [_generation_node()]},
        kind="batch",
    )
    return 0


async def read_generation(client: OwnerClient) -> int:
    response = await client.read([{"label": ENTITY, "key": GENERATION_KEY}])
    props = response["values"].get(f"{ENTITY}:{GENERATION_KEY}")
    if props is None:
        return 0
    return int(props.get("generation") or 0)


async def append_changes(
    client: OwnerClient,
    changes: list[SearchChange],
    *,
    mutation_id: str,
) -> int:
    """Bump the generation and write explicit change records atomically.

    The Owner batch carries the generation update and all change nodes in one
    transaction. A no-op change list does not bump anything. A concurrent
    writer causes a precondition retry, never a skipped generation.
    """
    if not changes:
        return await read_generation(client)
    await ensure_generation(client)
    for _attempt in range(5):
        current = await read_generation(client)
        generation = current + 1
        nodes = [{
            "labels": [ENTITY, CHANGE_LABEL],
            "key": f"search-index:change:{generation}:{index}",
            "props": {
                "generation": generation,
                "op": change.op,
                "kind": change.kind,
                "key": change.key,
                "scope_key": change.scope_key,
                "document_version_id": change.document_version_id,
            },
        } for index, change in enumerate(changes)]
        result = await client.mutate(
            mutation_id,
            {
                "generation": {
                    "label": ENTITY, "labels": [ENTITY, GENERATION_LABEL],
                    "key": GENERATION_KEY, "prop": "generation",
                },
                "expected": {"generation": current},
                "upsert_nodes": nodes,
            },
            kind="batch",
        )
        if result.get("error") == "precondition_failed":
            continue
        if result.get("ok") is not True:
            raise RuntimeError(f"search ledger mutation failed: {result}")
        return int(result.get("generation") or generation)
    raise RuntimeError("search generation precondition conflict")


async def list_changes(client: OwnerClient, generation: int) -> list[SearchChange]:
    rows = await client.list_nodes(
        CHANGE_LABEL, props={"generation": generation}, limit=1000,
    )
    if len(rows) >= 1000:
        raise RuntimeError(
            f"generation {generation} exceeds 1000 change records; rebuild required"
        )
    changes = []
    for row in rows:
        props = dict(row.get("props") or {})
        changes.append(SearchChange(
            kind=str(props.get("kind") or ""),  # type: ignore[arg-type]
            op=str(props.get("op") or ""),  # type: ignore[arg-type]
            key=str(props.get("key") or ""),
            scope_key=str(props.get("scope_key") or ""),
            document_version_id=str(props.get("document_version_id") or ""),
        ))
    return changes


def read_checkpoint(path: Path) -> int:
    try:
        return int(json.loads(Path(path).read_text()).get("generation", 0))
    except (FileNotFoundError, ValueError, TypeError, OSError):
        return 0


def write_checkpoint(path: Path, generation: int) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="generation-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"generation": int(generation)}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
        directory_fd = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


class SearchIndexer:
    """Apply durable ledger generations to a derived Tantivy index."""

    def __init__(self, index: TextUnitIndex, checkpoint: Path) -> None:
        self.index = index
        self.checkpoint = Path(checkpoint)

    def generation(self) -> int:
        return read_checkpoint(self.checkpoint)

    async def lag(self, client: OwnerClient) -> int:
        return max(0, await read_generation(client) - self.generation())

    async def assert_current(self, client: OwnerClient) -> None:
        pending = await self.lag(client)
        if pending:
            raise SearchIndexLagError(
                f"Tantivy index is {pending} generation(s) behind the Owner"
            )

    async def _upsert(self, client: OwnerClient, changes: list[SearchChange]) -> None:
        units: list[TextUnitDoc] = []
        facts: list[FactDoc] = []
        for change in changes:
            label = TEXT_UNIT if change.kind == "text_unit" else FACT
            response = await client.read([{"label": label, "key": change.key}])
            props = response["values"].get(f"{label}:{change.key}")
            if props is None:
                # Deleted before the indexer caught up: the corresponding delete
                # record (or the next rebuild) wins; do not index a phantom.
                continue
            record = GraphRecord(
                key=change.key, labels=(label,), props=dict(props),
                engine_id=response["ids"].get(f"{label}:{change.key}"),
            )
            if label == TEXT_UNIT:
                units.append(_unit(record))
            else:
                facts.append(_fact(record))
        if units:
            self.index.upsert_units(units)
        if facts:
            self.index.upsert_facts(facts)

    async def _apply_generation(self, client: OwnerClient, generation: int) -> None:
        changes = await list_changes(client, generation)
        if not changes:
            raise SearchIndexRebuildRequired(
                f"generation {generation} has no retained change records; rebuild required"
            )
        deletes = [change.key for change in changes if change.op == "delete"]
        if deletes:
            self.index.delete_keys(tuple(dict.fromkeys(deletes)))
        upserts = [change for change in changes if change.op == "upsert"]
        if upserts:
            await self._upsert(client, upserts)

    async def apply_pending(self, client: OwnerClient, *, max_generations: int = 1000) -> int:
        """Apply generations after the checkpoint; idempotent and restart-safe."""
        current = await read_generation(client)
        checkpoint = self.generation()
        if current < checkpoint:
            raise SearchIndexRebuildRequired(
                f"checkpoint {checkpoint} is ahead of Owner generation {current}"
            )
        applied = 0
        for generation in range(checkpoint + 1, current + 1):
            await self._apply_generation(client, generation)
            write_checkpoint(self.checkpoint, generation)
            applied += 1
            if applied >= max_generations:
                break
        return self.generation()

    def rebuild_from(self, catalog, index_dir: Path, *, generation: int) -> TextUnitIndex:
        """Deterministically rebuild from the current authoritative graph."""
        index = build_from_overgraph(catalog, Path(index_dir))
        write_checkpoint(self.checkpoint, generation)
        return index
