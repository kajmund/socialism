"""Prove document-find strategies on a real tenant OverGraph before product wiring.

Opt-in heavy scales:

    RUN_DOCUMENT_FIND_SCALE=1 uv run pytest \\
      tests/integration/test_document_find_overgraph.py -k scale
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from app.services.document_find import (
    classify_and_index,
    extend_set,
    filter_to_set,
    find_by_category,
    find_by_hybrid,
    find_by_shared_party,
    find_category_then_hybrid,
)
from app.services.document_find.category_index import documents_for_type
from app.services.document_find.fixture import (
    DIM,
    add_document,
    assert_has_version,
    count_text_units,
    link_same_party,
    seed_classified_documents,
    seed_text_units_bulk,
    vector,
)
from app.services.document_find.taxonomy import EMPLOYMENT, LEASE
from tests.tenant_catalogs import DirectTenantCatalogs as TenantCatalogs

pytestmark = pytest.mark.integration

BASELINE_DIR = Path(__file__).resolve().parent / "baselines"
CUSTOMER = 1
EXTENSION_QUERY = vector(0.9, 0.1)  # auto-renewal-ish
NOISE_QUERY = vector(1.0, 0.0)  # closer to noisy corpus than gold leases
LEASE_FILLER = vector(0.1, 0.9)
EMPLOYMENT_FILLER = vector(0.2, 0.8)


def _scale_opted_in() -> bool:
    return os.environ.get("RUN_DOCUMENT_FIND_SCALE") == "1"


@pytest.fixture
def tenants(tmp_path):
    registry = TenantCatalogs(tmp_path, dimension=DIM)
    try:
        yield registry
    finally:
        registry.close()


@pytest.fixture
def catalog(tenants):
    return tenants.open_for(CUSTOMER)


async def _seed_core(catalog) -> dict[str, list[str]]:
    """Documents without pre-set effective_type; classification runs in the chain."""
    leases: list[str] = []
    jobs: list[str] = []
    for index in range(3):
        doc_id = f"lease-{index}"
        await add_document(
            catalog,
            document_id=doc_id,
            title=f"Hyresavtal lokal {index}",
            opening="Detta hyresavtal reglerar uthyrning av lokal.",
            passages=[
                ("Hyresavtal för lokal. Hyran betalas månadsvis.", LEASE_FILLER),
                (
                    "Avtalet förlängs automatiskt med tolv månader om det inte sägs upp."
                    if index < 2
                    else "Avtalet löper ut utan automatisk förlängning.",
                    EXTENSION_QUERY if index < 2 else LEASE_FILLER,
                ),
            ],
            classify=False,
        )
        classify_and_index(
            catalog,
            document_id=doc_id,
            title=f"Hyresavtal lokal {index}",
            opening="Detta hyresavtal reglerar uthyrning av lokal.",
        )
        leases.append(doc_id)
    for index in range(2):
        doc_id = f"job-{index}"
        await add_document(
            catalog,
            document_id=doc_id,
            title=f"Anställningsavtal {index}",
            opening="Detta anställningsavtal gäller tillsvidareanställning.",
            passages=[
                ("Anställningsavtal. Lön utgår månadsvis.", EMPLOYMENT_FILLER),
                ("Semester enligt lag.", EMPLOYMENT_FILLER),
            ],
            classify=False,
        )
        classify_and_index(
            catalog,
            document_id=doc_id,
            title=f"Anställningsavtal {index}",
            opening="Detta anställningsavtal gäller tillsvidareanställning.",
        )
        jobs.append(doc_id)
    link_same_party(catalog, ["lease-0", "lease-1"])
    for doc_id in [*leases, *jobs]:
        assert_has_version(catalog, doc_id)
    return {"lease": leases, "employment": jobs}


@pytest.mark.asyncio
async def test_classify_index_search_chain(catalog):
    """Document → categorize → index → search → all matching IDs."""
    await add_document(
        catalog,
        document_id="raw-lease",
        title="Hyresavtal kontor",
        opening="Hyresavtal för kontorslokal.",
        passages=[("Lokal hyrs ut.", LEASE_FILLER)],
        classify=False,
    )
    assert documents_for_type(catalog, LEASE) == []
    classified = classify_and_index(
        catalog,
        document_id="raw-lease",
        title="Hyresavtal kontor",
        opening="Hyresavtal för kontorslokal.",
    )
    assert classified == LEASE
    result = find_by_category(catalog, user_phrase="Visa alla hyresavtal.")
    assert result.document_ids == ("raw-lease",)
    assert result.completeness == "complete"
    assert result.strategy == "category"


@pytest.mark.asyncio
async def test_category_search_has_zero_expensive_ops(catalog):
    await _seed_core(catalog)
    result = find_by_category(catalog, user_phrase="Visa alla hyresavtal.")
    assert set(result.document_ids) == {"lease-0", "lease-1", "lease-2"}
    assert result.counters.embedding_calls == 0
    assert result.counters.jev_calls == 0
    assert result.counters.llm_calls == 0
    assert result.counters.text_unit_reads == 0
    assert result.counters.vector_searches == 0
    assert result.counters.category_lookups == 1


@pytest.mark.asyncio
async def test_employment_category_without_content_traversal(catalog):
    await _seed_core(catalog)
    result = find_by_category(catalog, document_type=EMPLOYMENT)
    assert set(result.document_ids) == {"job-0", "job-1"}
    assert result.counters.text_unit_reads == 0
    assert result.counters.vector_searches == 0


@pytest.mark.asyncio
async def test_hybrid_groups_units_to_one_document(catalog):
    await add_document(
        catalog,
        document_id="multi-unit",
        title="Hyresavtal multi",
        passages=[
            ("Automatisk förlängning gäller.", EXTENSION_QUERY),
            ("Ytterligare klausul om förlängning.", EXTENSION_QUERY),
            ("Lokaladress Storgatan 1.", LEASE_FILLER),
        ],
    )
    result = find_by_hybrid(
        catalog, customer_id=CUSTOMER, dense_query=EXTENSION_QUERY, limit=10,
    )
    assert "multi-unit" in result.document_ids
    assert result.document_ids.count("multi-unit") == 1
    assert result.completeness == "partial"


def _mode_row(result, *, gold_set: set[str], note: str | None = None) -> dict:
    row = {
        "ids": list(result.document_ids),
        "recall_at_limit": len(gold_set & set(result.document_ids)) / len(gold_set),
        "vector_searches": result.counters.vector_searches,
        "db_ms": result.db_ms,
        "total_ms": result.total_ms,
        "text_unit_reads": result.counters.text_unit_reads,
    }
    if note:
        row["note"] = note
    return row


async def _seed_scoped_corpus(
    catalog, *, lease_count: int, gold_count: int, noise_count: int, units_per_doc: int = 2,
) -> list[str]:
    gold: list[str] = []
    for index in range(lease_count):
        doc_id = f"lease-ext-{index}"
        is_gold = index < gold_count
        body = [
            ("Hyresavtal.", LEASE_FILLER),
            (
                "Avtalet förlängs automatiskt." if is_gold else "Ingen förlängning.",
                EXTENSION_QUERY if is_gold else LEASE_FILLER,
            ),
        ]
        while len(body) < units_per_doc:
            body.append((f"Utfyllnad {len(body)}.", LEASE_FILLER))
        await add_document(
            catalog,
            document_id=doc_id,
            title=f"Hyresavtal {index}",
            opening="Hyresavtal för lager.",
            passages=body,
        )
        if is_gold:
            gold.append(doc_id)
    for index in range(noise_count):
        passages = [
            ("Anställningsavtal med automatisk förlängning av uppdrag.", NOISE_QUERY),
            ("Ytterligare förlängningsklausul.", NOISE_QUERY),
        ]
        while len(passages) < units_per_doc:
            passages.append((f"Noise utfyllnad {len(passages)}.", NOISE_QUERY))
        await add_document(
            catalog,
            document_id=f"noise-{index}",
            title=f"Anställningsavtal noise {index}",
            opening="Anställningsavtal.",
            passages=passages,
        )
    return gold


@pytest.mark.asyncio
async def test_scoped_hybrid_beats_global_post_filter(catalog):
    """Document filter before top-K vs global+post-filter control arm."""
    lease_count, gold_count, noise_count = 8, 5, 40
    gold = await _seed_scoped_corpus(
        catalog, lease_count=lease_count, gold_count=gold_count, noise_count=noise_count,
    )
    limit = 5
    content_query = NOISE_QUERY
    gold_set = set(gold)
    scoped = find_category_then_hybrid(
        catalog, customer_id=CUSTOMER, document_type=LEASE,
        dense_query=content_query, limit=limit, mode="scoped_from_category",
    )
    per_doc = find_category_then_hybrid(
        catalog, customer_id=CUSTOMER, document_type=LEASE,
        dense_query=content_query, limit=limit, mode="scoped_per_document",
    )
    post = find_category_then_hybrid(
        catalog, customer_id=CUSTOMER, document_type=LEASE,
        dense_query=content_query, limit=limit, mode="global_post_filter",
    )
    payload = {
        "chosen_default": "scoped_per_document",
        "corpus": {
            "documents_total": lease_count + noise_count,
            "lease_documents": lease_count,
            "gold_leases": gold_count,
            "noise_documents": noise_count,
            "text_units_total": count_text_units(catalog),
            "limit": limit,
        },
        "scoped_from_category": _mode_row(
            scoped, gold_set=gold_set,
            note="OverGraph scope from Category node returned no usable hits in v1",
        ),
        "scoped_per_document": _mode_row(per_doc, gold_set=gold_set),
        "global_post_filter": _mode_row(post, gold_set=gold_set),
        "gold": gold,
    }
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    (BASELINE_DIR / "document-find-scoped-hybrid-v1.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    assert per_doc.counters.vector_searches == lease_count
    assert payload["scoped_per_document"]["recall_at_limit"] == 1.0
    assert payload["global_post_filter"]["recall_at_limit"] < 1.0


@pytest.mark.asyncio
async def test_scoped_hybrid_scale(tmp_path):
    """Larger corpus: category size + noise + latency for scoped_per_document."""
    if _scale_opted_in():
        lease_count, gold_count, noise_count, units_per = 200, 20, 2000, 5
    else:
        lease_count, gold_count, noise_count, units_per = 30, 8, 120, 3
    registry = TenantCatalogs(tmp_path / "scoped-scale", dimension=DIM)
    try:
        catalog = registry.open_for(CUSTOMER)
        gold = await _seed_scoped_corpus(
            catalog,
            lease_count=lease_count,
            gold_count=gold_count,
            noise_count=noise_count,
            units_per_doc=units_per,
        )
        limit = gold_count
        content_query = NOISE_QUERY
        gold_set = set(gold)
        started = time.perf_counter()
        per_doc = find_category_then_hybrid(
            catalog, customer_id=CUSTOMER, document_type=LEASE,
            dense_query=content_query, limit=limit, mode="scoped_per_document",
        )
        wall_ms = (time.perf_counter() - started) * 1000
        started = time.perf_counter()
        post = find_category_then_hybrid(
            catalog, customer_id=CUSTOMER, document_type=LEASE,
            dense_query=content_query, limit=limit, mode="global_post_filter",
        )
        post_wall_ms = (time.perf_counter() - started) * 1000
        payload = {
            "corpus": {
                "documents_total": lease_count + noise_count,
                "lease_documents": lease_count,
                "gold_leases": gold_count,
                "noise_documents": noise_count,
                "text_units_per_document": units_per,
                "text_units_total": count_text_units(catalog),
                "limit": limit,
            },
            "scoped_per_document": {
                **_mode_row(per_doc, gold_set=gold_set),
                "wall_ms": wall_ms,
            },
            "global_post_filter": {
                **_mode_row(post, gold_set=gold_set),
                "wall_ms": post_wall_ms,
            },
        }
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        (BASELINE_DIR / "document-find-scoped-hybrid-scale-v1.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
        )
        assert payload["scoped_per_document"]["recall_at_limit"] == 1.0
        assert payload["global_post_filter"]["recall_at_limit"] < (
            payload["scoped_per_document"]["recall_at_limit"]
        )
    finally:
        registry.close()


@pytest.mark.asyncio
async def test_relation_same_party(catalog):
    await _seed_core(catalog)
    result = find_by_shared_party(
        catalog,
        seed_document_id="lease-0",
        party_name="Acme AB",
        customer_id=CUSTOMER,
    )
    assert "lease-1" in result.document_ids
    assert "lease-0" not in result.document_ids


@pytest.mark.asyncio
async def test_within_set_and_extend(catalog):
    await _seed_core(catalog)
    current = ["lease-0", "lease-1"]
    category = find_by_category(catalog, document_type=LEASE)
    filtered = filter_to_set(category, current)
    assert set(filtered.document_ids) == {"lease-0", "lease-1"}
    extended = extend_set(current, category.document_ids)
    assert set(extended) == {"lease-0", "lease-1", "lease-2"}


@pytest.mark.asyncio
async def test_category_scale_docs(tmp_path):
    """Fresh catalog per size so timings are not cumulative."""
    sizes = (50, 100)
    if _scale_opted_in():
        sizes = (100, 1000, 10_000)
    rows = []
    for size in sizes:
        registry = TenantCatalogs(tmp_path / f"scale-{size}", dimension=DIM)
        try:
            catalog = registry.open_for(CUSTOMER)
            seed_started = time.perf_counter()
            seed_classified_documents(catalog, count=size, document_type=LEASE)
            seed_ms = (time.perf_counter() - seed_started) * 1000
            started = time.perf_counter()
            result = find_by_category(catalog, document_type=LEASE)
            wall_ms = (time.perf_counter() - started) * 1000
            rows.append({
                "documents": size,
                "returned": len(result.document_ids),
                "seed_ms": seed_ms,
                "db_ms": result.db_ms,
                "wall_ms": wall_ms,
                "embedding_calls": result.counters.embedding_calls,
                "text_unit_reads": result.counters.text_unit_reads,
                "vector_searches": result.counters.vector_searches,
                "text_units_total": count_text_units(catalog),
            })
            assert result.counters.embedding_calls == 0
            assert result.counters.text_unit_reads == 0
            assert len(result.document_ids) == size
            if size <= 100:
                assert result.db_ms < 20.0
            elif size <= 1000:
                assert result.db_ms < 10.0
            else:
                assert result.db_ms < 30.0
        finally:
            registry.close()
    BASELINE_DIR.mkdir(parents=True, exist_ok=True)
    (BASELINE_DIR / "document-find-category-scale-v1.json").write_text(
        json.dumps({"rows": rows}, indent=2) + "\n", encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_category_textunit_scale(tmp_path):
    """Category lookup must not slow with more TextUnits per document."""
    if not _scale_opted_in():
        docs, units_per = 50, 20
    else:
        docs, units_per = 10_000, 100
    registry = TenantCatalogs(tmp_path / "fat-units", dimension=DIM)
    try:
        catalog = registry.open_for(CUSTOMER)
        ids = seed_classified_documents(
            catalog, count=docs, document_type=LEASE, id_prefix="fat",
        )
        seed_started = time.perf_counter()
        written = seed_text_units_bulk(
            catalog, document_ids=ids, units_per_document=units_per, customer_id=CUSTOMER,
        )
        seed_ms = (time.perf_counter() - seed_started) * 1000
        unit_count = count_text_units(catalog)
        assert written == docs * units_per
        assert unit_count >= docs * units_per
        started = time.perf_counter()
        result = find_by_category(catalog, document_type=LEASE)
        wall_ms = (time.perf_counter() - started) * 1000
        assert len(result.document_ids) == docs
        assert result.counters.text_unit_reads == 0
        assert result.counters.vector_searches == 0
        payload = {
            "documents": docs,
            "text_units_per_document": units_per,
            "text_units_total": unit_count,
            "unit_seed_ms": seed_ms,
            "db_ms": result.db_ms,
            "wall_ms": wall_ms,
            "total_ms": result.total_ms,
            "text_unit_reads": result.counters.text_unit_reads,
            "vector_searches": result.counters.vector_searches,
            "embedding_calls": result.counters.embedding_calls,
        }
        BASELINE_DIR.mkdir(parents=True, exist_ok=True)
        (BASELINE_DIR / "document-find-category-textunit-scale-v1.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8",
        )
        # Empty-graph 10k category lookup is ~28 ms; with 1M TextUnits the same
        # neighbor walk is slower (file/cache pressure) but must stay document-indexed
        # (zero TextUnit reads) and under a hard ceiling.
        if docs <= 50:
            assert result.db_ms < 20.0
        else:
            assert result.db_ms < 100.0
    finally:
        registry.close()
