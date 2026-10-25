"""Owner-backed document find against a real tenant Owner."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.document_find.tool import FindRequest
from app.services.document_qa.owner_document_index import classify_and_index
from app.services.document_qa.owner_find import (
    find_by_category,
    find_by_hybrid,
    find_category_then_hybrid,
    find_within_documents,
    run_find,
)
from app.services.document_qa.owner_ingest import persist_document_units
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.model import TextUnitWrite
from app.services.overgraph.owner import OvergraphOwner, OwnerClient

DIMENSION = 4
EMBEDDING_A = (1.0, 0.0, 0.0, 0.0)
EMBEDDING_B = (0.0, 1.0, 0.0, 0.0)


def _unit(unit_id: str, document_id: str, text: str, embedding: tuple[float, ...]) -> TextUnitWrite:
    return TextUnitWrite(
        unit_id=unit_id,
        scope=customer_scope(1),
        document_id=document_id,
        document_version_id=f"{document_id}-ver",
        text=text,
        content_hash=f"hash-{unit_id}",
        ordinal=0,
        embedding=embedding,
    )


async def _start() -> tuple[OvergraphOwner, OwnerClient, OwnerClient]:
    root = Path(tempfile.mkdtemp(prefix="owner-find-"))
    owner = OvergraphOwner(
        root / "tenant-1", dimension=DIMENSION, socket_path=root / "tenant-1.sock",
    )
    await owner.start()
    first = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    second = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    await persist_document_units(first, document_id="doc-a", units=(
        _unit("a-unit", "doc-a", "sekretessavtal om uppsägning", EMBEDDING_A),
    ))
    await persist_document_units(first, document_id="doc-b", units=(
        _unit("b-unit", "doc-b", "sekretessavtal om anställning", EMBEDDING_B),
    ))
    await persist_document_units(first, document_id="doc-c", units=(
        _unit("c-unit", "doc-c", "personuppgiftsbiträdesavtal", EMBEDDING_A),
    ))
    await classify_and_index(first, document_id="doc-a", document_type="nda")
    await classify_and_index(first, document_id="doc-b", document_type="nda")
    await classify_and_index(first, document_id="doc-c", document_type="dpa")
    return owner, first, second


async def test_category_and_hybrid_reads_go_through_the_owner():
    owner, first, second = await _start()
    try:
        category = await find_by_category(second, document_type="nda")
        assert category.document_ids == ("doc-a", "doc-b")
        hybrid = await find_by_hybrid(
            second, customer_id=1, dense_query=EMBEDDING_A, limit=10,
            allowed_document_ids=["doc-a", "doc-b"],
        )
        assert hybrid.document_ids[0] == "doc-a"
        assert set(hybrid.document_ids) <= {"doc-a", "doc-b"}
        within = await find_within_documents(
            second, customer_id=1, document_ids=["doc-c"], dense_query=EMBEDDING_A,
        )
        assert within.document_ids == ("doc-c",)
    finally:
        await owner.close()


async def test_category_then_hybrid_and_run_find_dispatch():
    owner, first, second = await _start()
    try:
        scoped = await find_category_then_hybrid(
            second, customer_id=1, document_type="nda",
            dense_query=EMBEDDING_A, limit=10,
        )
        assert scoped.document_ids == ("doc-a", "doc-b")
        category = await run_find(
            second,
            FindRequest(customer_id=1, query="visa alla sekretessavtal", mode="replace"),
        )
        assert category.document_ids == ("doc-a", "doc-b")
        content = await run_find(
            second,
            FindRequest(
                customer_id=1, query="sekretessavtal uppsägning",
                mode="replace", dense_query=EMBEDDING_A,
            ),
        )
        assert content.document_ids == ("doc-a", "doc-b")
        extended = await run_find(
            second,
            FindRequest(
                customer_id=1, query="sekretessavtal uppsägning",
                mode="extend", current=("doc-c",), dense_query=EMBEDDING_A,
            ),
        )
        assert extended.document_ids == ("doc-c", "doc-a", "doc-b")
        filtered = await run_find(
            second,
            FindRequest(
                customer_id=1, query="sekretessavtal", mode="filter",
                current=("doc-b",), dense_query=EMBEDDING_B,
            ),
        )
        assert filtered.document_ids == ("doc-b",)
    finally:
        await owner.close()


async def test_owner_find_matches_direct_find_for_the_same_tenant_data():
    from app.services.document_find import run_find as run_direct_find
    from app.services.document_qa.catalog_write import write_document_units
    from app.services.overgraph.catalogs import open_catalog

    owner, _first, second = await _start()
    direct_root = Path(tempfile.mkdtemp(prefix="direct-find-"))
    catalog = open_catalog(direct_root / "tenant-1", kind="knowledge", dimension=DIMENSION)
    try:
        for document_id, text, embedding in (
            ("doc-a", "sekretessavtal om uppsägning", EMBEDDING_A),
            ("doc-b", "sekretessavtal om anställning", EMBEDDING_B),
            ("doc-c", "personuppgiftsbiträdesavtal", EMBEDDING_A),
        ):
            await write_document_units(
                catalog, document_id=document_id,
                units=(_unit(f"{document_id}-unit", document_id, text, embedding),),
            )
        for document_id, document_type in (
            ("doc-a", "nda"), ("doc-b", "nda"), ("doc-c", "dpa"),
        ):
            from app.services.document_find import classify_and_index as direct_classify

            direct_classify(catalog, document_id=document_id, title=document_type)
        cases = (
            ("visa alla sekretessavtal", "replace", None, ()),
            ("sekretessavtal uppsägning", "replace", EMBEDDING_A, ()),
            ("sekretessavtal", "filter", EMBEDDING_B, ("doc-b",)),
            ("sekretessavtal uppsägning", "extend", EMBEDDING_A, ("doc-c",)),
        )
        for query, mode, dense, current in cases:
            direct = run_direct_find(
                catalog,
                FindRequest(
                    customer_id=1, query=query, mode=mode,
                    current=current, dense_query=dense, limit=10,
                ),
            )
            via_owner = await run_find(
                second,
                FindRequest(
                    customer_id=1, query=query, mode=mode,
                    current=current, dense_query=dense, limit=10,
                ),
            )
            assert via_owner.document_ids == direct.document_ids, query
            assert via_owner.strategy == direct.strategy, query
    finally:
        await owner.close()
        catalog.close()
