"""Architecture guard: no new direct Overgraph writers outside the allowlist."""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
PATTERN = re.compile(r"catalog\.(?:upsert_node|upsert_edge|delete_node|graph_patch|batch_upsert_nodes|begin_write_txn)\(")
OPEN_PATTERN = re.compile(r"\b(?:open_catalog|open_runtime)\(")

# Files still pending migration. Remove entries as they move behind the owner.
ALLOWLIST = {
    "services/overgraph/mem0_store.py",
    "services/overgraph/legal_claims.py",
    "services/overgraph/write.py",
    "services/overgraph/research.py",
    "services/overgraph/claim_answers.py",
    "services/overgraph/claims.py",
    "services/overgraph/text_units.py",
    "services/document_qa/store.py",
    "services/document_qa/catalog_write.py",
    "services/document_qa/review.py",
    "services/document_qa/lifecycle.py",
    "services/knowledge/backfill_text_units.py",
    "services/overgraph/owner.py",  # the owner itself
    "services/overgraph/owner_mutations.py",  # owner conditional transaction worker
    "services/kund_dokument.py",
    "services/document_qa/process_probe.py",
    "services/knowledge/graph_relationship_mirror.py",
    "services/knowledge/migrate_fact_identity.py",
    "services/clause_ssr/graph.py",
    "services/clause_ssr/anchors.py",
    "services/document_find/fixture.py",
    "services/document_find/category_index.py",
}


# Files allowed to open a catalog while the owner migration is in progress.
# Ordinary backend modules must read an owner-owned catalog through the owner.
OPEN_ALLOWLIST = {
    "main.py",  # owner mode opens only the memory catalog; owner-mode test below
    "services/overgraph/catalogs.py",  # the definition itself
    "services/overgraph/owner.py",  # the owner implementation
    "services/overgraph/workflows.py",  # SWE run store, separate catalog
    "services/overgraph/jev_cache.py",  # Jev cache store, separate catalog
    "services/document_qa/tenants.py",  # per-tenant catalog routing, Phase D
    "services/knowledge/backfill_text_units.py",  # offline maintenance
    "services/knowledge/parity_gate.py",  # offline parity gate
}


def test_no_new_direct_overgraph_writer() -> None:
    offenders = []
    for path in APP.rglob("*.py"):
        relative = str(path.relative_to(APP))
        if relative in ALLOWLIST:
            continue
        if PATTERN.search(path.read_text(encoding="utf-8")):
            offenders.append(relative)
    assert offenders == [], f"direct Overgraph writers outside owner: {offenders}"


def test_no_new_direct_catalog_opener_outside_allowlist() -> None:
    offenders = []
    for path in APP.rglob("*.py"):
        relative = str(path.relative_to(APP))
        if relative in OPEN_ALLOWLIST:
            continue
        if OPEN_PATTERN.search(path.read_text(encoding="utf-8")):
            offenders.append(relative)
    assert offenders == [], f"direct Overgraph catalog openers outside allowlist: {offenders}"
