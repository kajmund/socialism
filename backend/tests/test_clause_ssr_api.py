"""Admin HTTP surface for the isolated clause SSR library."""

from __future__ import annotations

from app.services.knowledge.scope import shared_scope
from tests.clause_ssr_fakes import seed_units, unit_vector


def _seed_clause(research_overgraph):
    seed_units(research_overgraph, shared_scope(), [
        ("tu-a", "Avtalet kan sägas upp med tre månaders varsel.", unit_vector(0), "doc-1", 0),
        ("tu-b", "Årsavgiften är 8 000 kronor.", unit_vector(4), "doc-1", 1),
    ])


async def test_admin_queue_yes_no_undo_resume(client, research_overgraph):
    _seed_clause(research_overgraph)
    created = await client.post(
        "/clause-ssr/classifications",
        json={
            "slug": "termination",
            "question": "Är det här en uppsägningsklausul?",
            "category": "termination",
        },
    )
    assert created.status_code == 200
    classification_id = created.json()["id"]

    first = await client.get(
        "/clause-ssr/queue",
        params={"classification_id": classification_id, "limit": 2},
    )
    assert first.status_code == 200
    cards = first.json()["cards"]
    assert cards[0]["unit_id"] == "tu-a"
    assert cards[0]["classification"]["question"].startswith("Är det här")

    saved = await client.post(
        "/clause-ssr/decisions",
        json={
            "classification_id": classification_id,
            "unit_id": "tu-a",
            "answer": "yes",
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["verification"]["answer"] == "yes"
    assert body["verification"]["is_label"] is True
    assert body["session"]["decided_yes"] == 1

    again = await client.post(
        "/clause-ssr/decisions",
        json={
            "classification_id": classification_id,
            "unit_id": "tu-a",
            "answer": "yes",
        },
    )
    assert again.json()["verification"]["revision"] == 1

    nxt = await client.get(
        "/clause-ssr/queue",
        params={"classification_id": classification_id},
    )
    assert nxt.json()["cards"][0]["unit_id"] == "tu-b"

    undone = await client.post(
        "/clause-ssr/decisions/undo",
        json={"classification_id": classification_id},
    )
    assert undone.status_code == 200
    assert undone.json()["unit_id"] == "tu-a"
    resumed = await client.get(
        "/clause-ssr/queue",
        params={"classification_id": classification_id},
    )
    assert resumed.json()["cards"][0]["unit_id"] == "tu-a"


async def test_user_is_forbidden(user_client, research_overgraph):
    response = await user_client.get("/clause-ssr/classifications")
    assert response.status_code == 403


async def test_match_endpoint_is_opt_in(client, research_overgraph):
    _seed_clause(research_overgraph)
    created = await client.post(
        "/clause-ssr/classifications",
        json={
            "slug": "termination",
            "question": "Är det här en uppsägningsklausul?",
            "category": "termination",
        },
    )
    classification_id = created.json()["id"]
    decision = await client.post(
        "/clause-ssr/decisions",
        json={
            "classification_id": classification_id,
            "unit_id": "tu-a",
            "answer": "yes",
        },
    )
    promoted = await client.post(
        "/clause-ssr/anchors/promote",
        json={"verification_id": decision.json()["verification"]["id"]},
    )
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "draft"
    built = await client.post(
        "/clause-ssr/anchor-sets",
        json={"category": "termination"},
    )
    assert built.status_code == 200
    matched = await client.post(
        "/clause-ssr/match",
        json={"text_unit_id": "tu-a", "k": 3},
    )
    assert matched.status_code == 200
    payload = matched.json()
    assert payload["not_a_probability"] is True
    assert payload["score_kind"] == "cosine_similarity"
    assert payload["top_k"][0]["category"] == "termination"
