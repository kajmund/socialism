"""Owner read facade: bounded queries, pagination, vectors and edges.

These tests exercise the same protocol the backend uses in owner read mode.
The old stale-snapshot implementation had no owner query path at all, so the
vertical two-backend harness and this facade are the regression guard.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import time
from pathlib import Path


from app.services.knowledge.scope import customer_scope
from app.services.knowledge.units import TextUnit, hash_text
from app.services.overgraph.labels import CONTAINS, TEXT_UNIT
from app.services.overgraph.owner import OwnerClient
from app.services.overgraph.owner_writer import build_text_unit_batch, mutation_id_for

BACKEND = Path(__file__).resolve().parents[1]


def _unit(index: int, version: str = "ver-read") -> TextUnit:
    text = f"Klausul {index} om uppsägningstid."
    return TextUnit(
        id=f"read-unit-{index}", document_version_id=version, document_id="doc-read",
        section_id="sec-1", ordinal=index, text=text, content_hash=hash_text(text),
        locator=f"stycke {index + 1}", page_start=1, page_end=1,
    )


async def _start_owner(root: Path) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [
            sys.executable, "-m", "app.services.overgraph.owner",
            str(root / "catalog"), "--socket", str(root / "owner.sock"),
            "--dimension", "4",
        ],
        cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        text=True,
    )
    deadline = time.monotonic() + 20
    from app.services.overgraph.owner import OwnerUnavailable

    while time.monotonic() < deadline:
        try:
            await OwnerClient(root / "owner.sock").health()
            return process
        except (OwnerUnavailable, OSError, ConnectionError):
            await asyncio.sleep(0.05)
    process.kill()
    raise TimeoutError("owner did not become ready")


def _stop(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


async def test_owner_query_pagination_vectors_and_edges():
    root = Path(tempfile.mkdtemp(prefix="ogo-read-"))
    owner = await _start_owner(root)
    try:
        socket_path = root / "owner.sock"
        client = OwnerClient(socket_path)
        units = [_unit(0), _unit(1)]
        batch = build_text_unit_batch(
            units, scope=customer_scope(1),
            embeddings=[[0.1, 0.2, 0.3, 0.4], [0.4, 0.3, 0.2, 0.1]],
        )
        result = await client.mutate(mutation_id_for(batch), batch, kind="batch")
        assert result["ok"] is True

        first = await client.query_nodes(
            TEXT_UNIT, props={"document_version_id": "ver-read"},
            include_vectors=True, limit=1,
        )
        assert len(first["nodes"]) == 1
        assert first["next_cursor"] is not None
        second = await client.query_nodes(
            TEXT_UNIT, props={"document_version_id": "ver-read"},
            include_vectors=True, limit=1, after=first["next_cursor"],
        )
        assert len(second["nodes"]) == 1
        combined = first["nodes"] + second["nodes"]
        assert {node["key"] for node in combined} == {"read-unit-0", "read-unit-1"}
        assert all(len(node["dense_vector"]) == 4 for node in combined)
        assert (await client.count_nodes(TEXT_UNIT)) == 2

        detail = await client.node(int(combined[0]["id"]))
        assert detail is not None
        labels = {edge["label"] for edge in detail["edges"]}
        assert CONTAINS in labels or "NEXT" in labels
        assert any(edge["key"] == "ver-read" for edge in detail["edges"])
    finally:
        _stop(owner)


def test_owner_mode_forbids_direct_knowledge_catalog_open(tmp_path):
    import pytest

    from app.services.overgraph.catalogs import (
        OwnerReadRequiredError,
        open_catalog,
        set_owner_mode,
    )

    set_owner_mode(True)
    try:
        with pytest.raises(OwnerReadRequiredError):
            open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=4)
    finally:
        set_owner_mode(False)


def test_owner_read_mode_opens_only_the_memory_catalog(monkeypatch):
    import app.main as app_main
    import app.services.overgraph.catalogs as catalogs

    opened: list[str] = []
    real = catalogs.open_catalog

    def record(path, *, kind, dimension):
        opened.append(kind)
        return real(path, kind=kind, dimension=dimension)

    monkeypatch.setattr(catalogs, "open_catalog", record)
    runtime = app_main._graph_runtime_for_mode(True)
    try:
        assert runtime.knowledge is None
        assert opened == ["memory"]
    finally:
        runtime.close()
