from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.services.clause_ssr.keys import anchor_key, verification_key
from app.services.clause_ssr.labels import ANCHOR, CLASSIFICATION, VERIFICATION
from app.services.clause_ssr.repository import ClauseRepository
from app.services.knowledge.scope import customer_scope
from app.services.overgraph.labels import scope_label
from app.services.overgraph.owner import OwnerClient, OvergraphOwner


@pytest.fixture
async def repo():
    root = Path(tempfile.mkdtemp(prefix="ogo-"))
    owner = OvergraphOwner(root / "catalog", dimension=4, socket_path=root / "owner.sock")
    await owner.start()
    client = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    scope = customer_scope(1)
    seed = {
        "upsert_nodes": [
            {"labels": [CLASSIFICATION, scope_label(scope.scope_key)], "key": "cls-1", "props": {"slug": "uppsagning", "version": 1, "question": "Uppsägning?", "category": "uppsagning", "level": "clause", "active": True, "scope_key": scope.scope_key}},
            {"labels": ["TextUnit", scope_label(scope.scope_key)], "key": "unit-1", "props": {"document_id": "doc-1", "content_hash": "h1", "text": "text", "scope_key": scope.scope_key}},
        ]
    }
    await client.mutate("seed", seed, kind="batch")
    try:
        yield owner, ClauseRepository(client), scope
    finally:
        await owner.close()


async def test_record_yes_then_no_revokes_anchor(repo):
    owner, repository, scope = repo
    first = await repository.record_decision(
        scope=scope, classification_id="cls-1", unit_id="unit-1", reviewer_id="admin-1", answer="yes",
    )
    assert first["result"]["ok"] is True
    key = verification_key(scope.scope_key, "cls-1", "unit-1", "admin-1")
    verification = owner.catalog.get_by_key(VERIFICATION, key)
    assert verification is not None and verification.props["answer"] == "yes"
    anchor = anchor_key(scope.scope_key, key)
    await repository.client.mutate("anchor", {"upsert_nodes": [{"labels": [ANCHOR, scope_label(scope.scope_key)], "key": anchor, "props": {"verification_id": key, "status": "active", "source_unit_id": "unit-1"}}]}, kind="batch")
    second = await repository.record_decision(
        scope=scope, classification_id="cls-1", unit_id="unit-1", reviewer_id="admin-1", answer="no",
    )
    assert second["result"]["ok"] is True
    current = owner.catalog.get_by_key(VERIFICATION, key)
    assert current is not None and current.props["answer"] == "no" and current.props["revision"] == 2
    assert owner.catalog.get_by_key(ANCHOR, anchor).props["status"] == "revoked"


async def test_concurrent_decisions_do_not_lose_revision(repo):
    owner, repository, scope = repo
    await repository.record_decision(scope=scope, classification_id="cls-1", unit_id="unit-1", reviewer_id="admin-1", answer="yes")
    key = verification_key(scope.scope_key, "cls-1", "unit-1", "admin-1")
    await repository.client.mutate("anchor", {"upsert_nodes": [{"labels": [ANCHOR, scope_label(scope.scope_key)], "key": anchor_key(scope.scope_key, key), "props": {"verification_id": key, "status": "active"}}]}, kind="batch")
    import asyncio
    await asyncio.gather(
        repository.record_decision(scope=scope, classification_id="cls-1", unit_id="unit-1", reviewer_id="admin-1", answer="no"),
        repository.record_decision(scope=scope, classification_id="cls-1", unit_id="unit-1", reviewer_id="admin-1", answer="yes"),
        return_exceptions=True,
    )
    current = owner.catalog.get_by_key(VERIFICATION, key)
    assert current is not None
    assert int(current.props["revision"]) >= 2
    assert owner.catalog.get_by_key(ANCHOR, anchor_key(scope.scope_key, key)).props["status"] == "revoked"


async def test_explicit_revoke_removes_anchor(repo):
    owner, repository, scope = repo
    await repository.record_decision(scope=scope, classification_id="cls-1", unit_id="unit-1", reviewer_id="admin-1", answer="yes")
    key = verification_key(scope.scope_key, "cls-1", "unit-1", "admin-1")
    await repository.client.mutate("anchor", {"upsert_nodes": [{"labels": [ANCHOR, scope_label(scope.scope_key)], "key": anchor_key(scope.scope_key, key), "props": {"verification_id": key, "status": "active"}}]}, kind="batch")
    revoked = await repository.revoke_verification(scope=scope, verification_id=key)
    assert revoked["result"]["ok"] is True
    assert owner.catalog.get_by_key(VERIFICATION, key).props["status"] == "revoked"
    assert owner.catalog.get_by_key(ANCHOR, anchor_key(scope.scope_key, key)).props["status"] == "revoked"


async def test_repository_accepts_existing_session_without_session_version(repo):
    owner, repository, scope = repo
    from app.services.clause_ssr.keys import session_key
    from app.services.clause_ssr.labels import REVIEW_SESSION
    from app.services.overgraph.labels import scope_label

    key = session_key(scope.scope_key, "admin-1", "cls-1", None)
    await repository.client.mutate("legacy-session", {"upsert_nodes": [{
        "labels": [REVIEW_SESSION, scope_label(scope.scope_key)], "key": key,
        "props": {"reviewer_id": "admin-1", "classification_id": "cls-1", "document_id": ""},
    }]}, kind="batch")
    result = await repository.record_decision(
        scope=scope, classification_id="cls-1", unit_id="unit-1",
        reviewer_id="admin-1", answer="yes",
    )
    assert result["result"]["ok"] is True
    assert int(result["session"]["decided_yes"]) == 1


async def test_concurrent_session_get_or_create_is_single(repo):
    import asyncio
    owner, repository, scope = repo
    results = await asyncio.gather(*(
        repository.get_or_create_session(
            scope=scope, reviewer_id="admin-1", classification_id="cls-1",
        )
        for _ in range(6)
    ))
    ids = {result["id"] for result in results}
    assert len(ids) == 1
    key = next(iter(ids))
    assert owner.catalog.get_by_key("SsrReviewSession", key) is not None


async def test_concurrent_promotion_and_revoke_never_leaves_active_anchor(repo):
    import asyncio
    from app.services.clause_ssr.types import EmbeddingSpec
    owner, repository, scope = repo
    await repository.record_decision(scope=scope, classification_id="cls-1", unit_id="unit-1", reviewer_id="admin-1", answer="yes")
    key = verification_key(scope.scope_key, "cls-1", "unit-1", "admin-1")
    embedding = EmbeddingSpec(model="test", revision="v1", dimension=4)
    results = await asyncio.gather(
        repository.promote_anchor(scope=scope, verification_id=key, embedding=embedding),
        repository.record_decision(scope=scope, classification_id="cls-1", unit_id="unit-1", reviewer_id="admin-1", answer="no"),
        return_exceptions=True,
    )
    assert any(isinstance(item, dict) and item.get("result", {}).get("ok") for item in results)
    anchor = owner.catalog.get_by_key("SsrClauseAnchor", anchor_key(scope.scope_key, key))
    if anchor is not None:
        assert anchor.props["status"] != "active"
    verification = owner.catalog.get_by_key("SsrVerification", key)
    assert verification.props["answer"] == "no"


async def test_stale_embedding_marks_anchor_and_bumps_pool(repo):
    from app.services.clause_ssr.types import EmbeddingSpec
    from app.services.overgraph.labels import scope_label
    owner, repository, scope = repo
    await repository.client.mutate("stale-seed", {"upsert_nodes": [{
        "labels": ["SsrClauseAnchor", scope_label(scope.scope_key)], "key": "stale-a",
        "props": {"scope_key": scope.scope_key, "category": "termination", "status": "active",
                  "embedding_model": "old", "embedding_revision": "v1", "embedding_dimension": 4},
    }]}, kind="batch")
    changed = await repository.mark_stale_embeddings(
        scope=scope, expected=EmbeddingSpec(model="new", revision="v2", dimension=4),
    )
    assert changed == 1
    assert owner.catalog.get_by_key("SsrClauseAnchor", "stale-a").props["status"] == "stale_embedding"
    pool = owner.catalog.get_by_key("SsrAnchorPool", repository._pool_key(scope, "termination"))
    assert int(pool.props["revision"]) == 1
    assert await repository.mark_stale_embeddings(
        scope=scope, expected=EmbeddingSpec(model="new", revision="v2", dimension=4),
    ) == 0
