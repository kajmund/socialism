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
from pathlib import Path
from app.services.overgraph.labels import ENTITY, FACT, TEXT_UNIT
from app.services.overgraph.model import GraphRecord
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.search_ledger import (
    CHANGE_LABEL,
    GENERATION_KEY,
    SearchChange,
)
from app.services.tantivy_documents import FactDoc, TextUnitDoc, _fact, _unit
from app.services.tantivy_index import TextUnitIndex, build_from_overgraph


class SearchIndexLagError(RuntimeError):
    """The derived index is behind the durable Owner generation."""


class SearchIndexRebuildRequired(RuntimeError):
    """The checkpoint is beyond the ledger (or records are missing)."""


async def read_generation(client: OwnerClient) -> int:
    response = await client.read([{"label": ENTITY, "key": GENERATION_KEY}])
    props = response["values"].get(f"{ENTITY}:{GENERATION_KEY}")
    if props is None:
        return 0
    return int(props.get("generation") or 0)


async def list_changes(
    client: OwnerClient, generation: int, *, page_size: int = 200,
) -> list[SearchChange]:
    """Read all change records for a generation via bounded stable pages."""
    rows: list[dict] = []
    after: int | None = None
    while True:
        page = await client.query_nodes(
            CHANGE_LABEL, props={"generation": generation},
            limit=page_size, after=after,
        )
        rows.extend(page["nodes"])
        cursor = page.get("next_cursor")
        if cursor is None:
            break
        if cursor == after:
            raise SearchIndexRebuildRequired(
                f"change pagination for generation {generation} did not advance"
            )
        after = int(cursor)
    changes = []
    for row in rows:
        props = dict(row.get("props") or {})
        changes.append(SearchChange(
            kind=str(props.get("kind") or ""),
            op=str(props.get("op") or ""),
            key=str(props.get("key") or ""),
            scope_key=str(props.get("scope_key") or ""),
            document_version_id=str(props.get("document_version_id") or ""),
            ordinal=int(props.get("ordinal") or 0),
        ))
    changes.sort(key=lambda change: (change.ordinal, change.key))
    return changes


async def validate_candidates(
    client: OwnerClient,
    *,
    text_unit_keys: list[str],
    fact_keys: list[str],
    now_ms: int | None = None,
) -> set[str]:
    """Validate stale-index candidates against the authoritative Owner state."""
    import time

    now = now_ms if now_ms is not None else int(time.time() * 1000)
    valid: set[str] = set()
    for label, keys in ((TEXT_UNIT, text_unit_keys), (FACT, fact_keys)):
        unique = list(dict.fromkeys(keys))
        for start in range(0, len(unique), 500):
            batch = unique[start:start + 500]
            response = await client.read([{"label": label, "key": key} for key in batch])
            for key in batch:
                props = response["values"].get(f"{label}:{key}")
                if props is None:
                    continue
                if label == FACT:
                    if str(props.get("status") or "") != "active":
                        continue
                    valid_at = int(props.get("valid_at_ms") or 0)
                    invalid_at = int(props.get("invalid_at_ms") or 0)
                    if valid_at and valid_at > now:
                        continue
                    if invalid_at and now >= invalid_at:
                        continue
                valid.add(key)
    return valid


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

    def __init__(
        self, index: TextUnitIndex, checkpoint: Path, *, page_size: int = 200,
    ) -> None:
        self.index = index
        self.checkpoint = Path(checkpoint)
        self.page_size = page_size

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

    async def ensure_current(self, client: OwnerClient) -> int:
        """Catch up first, then fail if the index is still behind."""
        await self.apply_pending(client)
        await self.assert_current(client)
        return self.generation()

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
        changes = await list_changes(client, generation, page_size=self.page_size)
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

    async def apply_pending(
        self, client: OwnerClient, *, max_generations: int | None = None,
    ) -> int:
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
            if max_generations is not None and applied >= max_generations:
                break
        return self.generation()

    def rebuild_from(self, catalog, index_dir: Path, *, generation: int) -> TextUnitIndex:
        """Deterministically rebuild from the current authoritative graph."""
        index = build_from_overgraph(catalog, Path(index_dir))
        write_checkpoint(self.checkpoint, generation)
        return index
