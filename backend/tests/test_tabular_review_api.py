"""HTTP + persistence tests for opt-in SSR Tabular Review."""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select

from app.database.models import CanonicalDocumentRecord, Kund, SsrAnchorSet
from app.database.tabular_review import TabularReviewVerificationLabel
from app.services.knowledge.units import hash_text
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.write import upsert_text_unit
from app.services.ssr import set_embedder
from app.services.clause_ssr.anchors import promote_anchor
from app.services.clause_ssr.classifications import upsert_classification
from app.services.clause_ssr.select import build_anchor_set
from app.services.clause_ssr.types import EmbeddingSpec
from app.services.clause_ssr.verifications import record_decision, revoke_verification
from app.services.knowledge.scope import customer_scope
from tests.conftest import RESEARCH_TEST_DIM, TEST_CUSTOMER_ID
from tests.text_unit_fakes import text_unit_view, text_unit_write


def _vec(*head: float) -> tuple[float, ...]:
    values = list(head) + [0.0] * RESEARCH_TEST_DIM
    return tuple(values[:RESEARCH_TEST_DIM])


def _scope(customer_id=TEST_CUSTOMER_ID):
    return {
        "scope_type": "customer",
        "scope_key": f"customer:{customer_id}",
        "customer_id": customer_id,
    }


async def _enable_module(factory) -> None:
    async with factory() as session:
        kund = await session.get(Kund, TEST_CUSTOMER_ID)
        assert kund is not None
        modules = [item for item in kund.available_modules if isinstance(item, str)]
        if "tabular_review" not in modules:
            kund.available_modules = [*modules, "tabular_review"]
        await session.commit()


async def _clause_set(
    factory, *, label="uppsagning", customer_id: int = TEST_CUSTOMER_ID
) -> str:
    catalog = require_knowledge()
    scope = customer_scope(customer_id)
    classification = upsert_classification(
        catalog,
        scope=scope,
        slug=label,
        question=f"Är det här en {label}-klausul?",
        category=label,
    )
    verification = record_decision(
        catalog,
        scope=scope,
        classification_id=classification.id,
        unit_id="unit-hit-doc",
        reviewer_id="admin-1",
        answer="yes",
    )
    embedding = EmbeddingSpec(model="test", revision="v1", dimension=RESEARCH_TEST_DIM)
    promote_anchor(catalog, verification.id, scope=scope, embedding=embedding)
    return build_anchor_set(catalog, scope=scope, category=label, embedding=embedding).id


async def _document(factory, *, doc_id="doc-1", title="Hyresavtal", text="Avtalet kan sägas upp med tre månaders uppsägningstid.", vector=_vec(1.0)):
    version_id = f"ver-{doc_id}"
    unit_id = f"unit-{doc_id}"
    async with factory() as session:
        session.add(
            CanonicalDocumentRecord(
                id=doc_id,
                **_scope(),
                source_type="upload",
                canonical_uri=f"doc://{doc_id}",
                title=title,
                extra={},
            )
        )
        from app.database.models import DocumentVersionRecord

        session.add(
            DocumentVersionRecord(
                id=version_id,
                **_scope(),
                document_id=doc_id,
                content_hash=hash_text(text),
                mime_type="application/pdf",
                extra={},
            )
        )
        await session.commit()
    view = text_unit_view(
        text=text,
        id=unit_id,
        document_id=doc_id,
        document_version_id=version_id,
        customer_id=TEST_CUSTOMER_ID,
        locator="§12",
        page_start=3,
        page_end=3,
    )
    upsert_text_unit(require_knowledge(), replace(text_unit_write(view), embedding=tuple(vector)))
    return doc_id


@pytest.fixture
def review_embedder():
    async def _mock(texts: list[str]) -> list[list[float]]:
        return [list(_vec(1.0)) for _ in texts]

    set_embedder(_mock)
    yield
    set_embedder(None)


async def test_module_is_opt_in(client_db):
    client, factory = client_db
    denied = await client.get("/tabular-reviews")
    assert denied.status_code == 403
    await _enable_module(factory)
    allowed = await client.get("/tabular-reviews")
    assert allowed.status_code == 200
    assert allowed.json() == []


async def test_create_run_lock_approve_and_missed_hit(client_db, review_embedder):
    client, factory = client_db
    await _enable_module(factory)
    await _document(factory, doc_id="hit-doc", title="Avtal A")
    await _document(
        factory,
        doc_id="miss-doc",
        title="Avtal B",
        text="Detta avtal handlar om samråd och leverans.",
        vector=_vec(0.0, 1.0),
    )
    anchor_id = await _clause_set(factory)

    created = await client.post(
        "/tabular-reviews",
        json={
            "name": "Klausulöversikt",
            "document_ids": ["hit-doc", "miss-doc"],
            "columns": [
                {
                    "title": "Uppsägningstid",
                    "anchor_set_id": anchor_id,
                    "label": "uppsagning",
                }
            ],
            "score_threshold": 0.35,
        },
    )
    assert created.status_code == 201, created.text
    review_id = created.json()["id"]

    ran = await client.post(f"/tabular-reviews/{review_id}/run")
    assert ran.status_code == 200, ran.text
    payload = ran.json()
    assert len(payload["rows"]) == 2
    by_title = {row["title"]: row for row in payload["rows"]}
    hit = by_title["Avtal A"]["cells"][0]
    miss = by_title["Avtal B"]["cells"][0]
    assert hit["status"] == "hit"
    assert hit["exact_text"].startswith("Avtalet kan sägas upp")
    assert hit["similarity"] == 1.0
    assert hit["source"]["page_start"] == 3
    assert miss["status"] == "no_hit"
    assert miss["no_hit_reason"] == "below_threshold"
    assert miss["exact_text"] is None

    locked = await client.post(f"/tabular-reviews/{review_id}/cells/{hit['id']}/lock")
    assert locked.status_code == 200
    assert locked.json()["locked"] is True

    approved = await client.post(f"/tabular-reviews/{review_id}/cells/{hit['id']}/approve")
    assert approved.status_code == 200
    label = approved.json()["verification_label"]
    assert label["verdict"] == "match"
    assert label["activated_as_ssr_anchor"] is False
    assert label["text_unit_id"] == hit["text_unit_id"]

    async with factory() as session:
        labels = list((await session.execute(select(TabularReviewVerificationLabel))).scalars().all())
        assert len(labels) == 1

    note = await client.post(
        f"/tabular-reviews/{review_id}/cells/{hit['id']}/note",
        json={"note": "Kontrollerad mot originalet"},
    )
    assert note.status_code == 200
    history = await client.get(f"/tabular-reviews/{review_id}/cells/{hit['id']}/history")
    assert history.status_code == 200
    actions = {item["action"] for item in history.json()}
    assert "locked" in actions
    assert "verification_label" in actions

    rerun = await client.post(f"/tabular-reviews/{review_id}/run")
    assert rerun.status_code == 200
    locked_cell = next(cell for row in rerun.json()["rows"] for cell in row["cells"] if cell["id"] == hit["id"])
    assert locked_cell["locked"] is True
    assert locked_cell["review_state"] == "approved"
    assert locked_cell["exact_text"] == hit["exact_text"]


async def test_user_without_module_is_denied(user_client):
    res = await user_client.get("/tabular-reviews")
    assert res.status_code == 403


async def test_foreign_anchor_set_is_rejected(client_db, user_token):
    client, factory = client_db
    await _enable_module(factory)
    await _document(factory, doc_id="doc-1", title="Avtal")
    async with factory() as session:
        if await session.get(Kund, 2) is None:
            session.add(Kund(id=2, name="Other", slug="other", available_modules=[]))
            await session.commit()
    catalog = require_knowledge()
    other_scope = customer_scope(2)
    view = text_unit_view(
        text="Uppsägning enligt avtal.",
        id="unit-doc-c2",
        document_id="doc-c2",
        document_version_id="ver-doc-c2",
        customer_id=2,
        locator="§1",
        page_start=1,
        page_end=1,
    )
    upsert_text_unit(
        catalog,
        replace(text_unit_write(view), embedding=tuple(_vec(1.0))),
    )
    classification = upsert_classification(
        catalog,
        scope=other_scope,
        slug="uppsagning",
        question="Är det här en uppsägningsklausul?",
        category="uppsagning",
    )
    verification = record_decision(
        catalog,
        scope=other_scope,
        classification_id=classification.id,
        unit_id="unit-doc-c2",
        reviewer_id="admin-2",
        answer="yes",
    )
    embedding = EmbeddingSpec(model="test", revision="v1", dimension=RESEARCH_TEST_DIM)
    promote_anchor(catalog, verification.id, scope=other_scope, embedding=embedding)
    foreign_set_id = build_anchor_set(
        catalog, scope=other_scope, category="uppsagning", embedding=embedding
    ).id
    client.headers["Authorization"] = f"Bearer {user_token}"
    created = await client.post(
        "/tabular-reviews",
        json={
            "name": "Foreign anchors",
            "document_ids": ["doc-1"],
            "columns": [
                {
                    "title": "Uppsägning",
                    "anchor_set_id": foreign_set_id,
                    "label": "uppsagning",
                }
            ],
        },
    )
    assert created.status_code == 404, created.text
    assert created.json()["detail"] == "anchor_set_not_found"


async def test_module_user_lists_clause_anchors_without_admin_api(client_db, user_token):
    client, factory = client_db
    await _enable_module(factory)
    await _document(factory, doc_id="hit-doc", title="Avtal A")
    await _clause_set(factory)
    client.headers["Authorization"] = f"Bearer {user_token}"
    admin_only = await client.get("/anchor-sets")
    assert admin_only.status_code == 403
    listed = await client.get("/tabular-reviews/clause-anchors")
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["labels"] == ["uppsagning"]




async def test_revoked_anchor_preserves_locked_history_and_blocks_new_match(
    client_db, review_embedder
):
    client, factory = client_db
    await _enable_module(factory)
    await _document(factory, doc_id="doc-a", title="Avtal A")
    await _document(factory, doc_id="doc-b", title="Avtal B")
    catalog = require_knowledge()
    scope = customer_scope(TEST_CUSTOMER_ID)
    classification = upsert_classification(
        catalog,
        scope=scope,
        slug="uppsagning",
        question="Är det här en uppsägningsklausul?",
        category="uppsagning",
    )
    verification = record_decision(
        catalog,
        scope=scope,
        classification_id=classification.id,
        unit_id="unit-doc-a",
        reviewer_id="admin-1",
        answer="yes",
    )
    embedding = EmbeddingSpec(model="test", revision="v1", dimension=RESEARCH_TEST_DIM)
    promote_anchor(catalog, verification.id, scope=scope, embedding=embedding)
    set_id = build_anchor_set(
        catalog, scope=scope, category="uppsagning", embedding=embedding
    ).id

    created = await client.post(
        "/tabular-reviews",
        json={
            "name": "Revocation",
            "document_ids": ["doc-a", "doc-b"],
            "columns": [
                {"title": "Uppsägning", "anchor_set_id": set_id, "label": "uppsagning"}
            ],
        },
    )
    assert created.status_code == 201, created.text
    review_id = created.json()["id"]
    ran = await client.post(f"/tabular-reviews/{review_id}/run")
    assert ran.status_code == 200, ran.text
    cells = [cell for row in ran.json()["rows"] for cell in row["cells"]]
    assert len(cells) == 2
    hit = next(cell for cell in cells if cell["status"] == "hit")
    await client.post(f"/tabular-reviews/{review_id}/cells/{hit['id']}/lock")
    await client.post(f"/tabular-reviews/{review_id}/cells/{hit['id']}/approve")

    revoke_verification(catalog, verification.id, scope=scope)
    rerun = await client.post(f"/tabular-reviews/{review_id}/run")
    assert rerun.status_code == 200, rerun.text
    rerun_cells = [cell for row in rerun.json()["rows"] for cell in row["cells"]]
    locked = next(cell for cell in rerun_cells if cell["id"] == hit["id"])
    assert locked["locked"] is True
    assert locked["review_state"] == "approved"
    assert locked["exact_text"] == hit["exact_text"]
    unlocked = [cell for cell in rerun_cells if cell["id"] != hit["id"]]
    assert all(cell["status"] == "no_hit" for cell in unlocked)
    assert all(cell["no_hit_reason"] == "no_active_anchors" for cell in unlocked)

    async with factory() as session:
        clause_rows = list(
            (
                await session.execute(select(SsrAnchorSet).where(SsrAnchorSet.kind == "clause"))
            ).scalars().all()
        )
        assert clause_rows == []
