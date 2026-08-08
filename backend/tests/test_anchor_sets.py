"""Tests for SSR anchor library API and configuration wiring."""

from __future__ import annotations

import pytest

from app.services.ssr import set_embedder


@pytest.fixture
def mock_embedder():
    async def _mock(texts: list[str]) -> list[list[float]]:
        return [[float((hash(t) + i) % 7) for i in range(8)] for t in texts]

    set_embedder(_mock)
    yield
    set_embedder(None)


async def test_list_anchor_sets_seeded(client):
    res = await client.get("/anchor-sets")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) >= 6
    assert any(r["kind"] == "tone" and r["locale"] == "sv" for r in rows)
    assert any(r["kind"] == "tone" and r["locale"] == "nb" for r in rows)
    assert any(r["kind"] == "style" and r["locale"] == "nb" for r in rows)


async def test_create_publish_and_test_anchor_set(client, mock_embedder):
    create = await client.post(
        "/anchor-sets",
        json={
            "name": "test_tone_sv",
            "kind": "tone",
            "locale": "sv",
            "version": "test",
            "labels": [
                "Starkt negativ",
                "Något negativ",
                "Neutral",
                "Något positiv",
                "Starkt positiv",
            ],
            "statements": [
                "Negativ ett",
                "Negativ två",
                "Neutral",
                "Positiv ett",
                "Positiv två",
            ],
            "status": "draft",
        },
    )
    assert create.status_code == 201
    anchor_id = create.json()["id"]

    pub = await client.post(f"/anchor-sets/{anchor_id}/publish")
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"

    test = await client.post(
        f"/anchor-sets/{anchor_id}/test",
        json={"texts": ["Det här är bra", "Uselt"], "temperature": 0.1},
    )
    assert test.status_code == 200
    body = test.json()
    assert body["labels"]
    assert len(body["per_text"]) == 2


async def test_calibration_and_test_with_human_labels(client, mock_embedder):
    create = await client.post(
        "/anchor-sets",
        json={
            "name": "cal_tone",
            "kind": "tone",
            "locale": "sv",
            "labels": [
                "Starkt negativ",
                "Något negativ",
                "Neutral",
                "Något positiv",
                "Starkt positiv",
            ],
            "statements": ["a", "b", "c", "d", "e"],
        },
    )
    anchor_id = create.json()["id"]
    item = await client.post(
        f"/anchor-sets/{anchor_id}/calibration",
        json={"text": "Bra idé", "human_label": "Starkt positiv"},
    )
    assert item.status_code == 201

    rated = await client.post(
        f"/anchor-sets/{anchor_id}/test",
        json={"texts": ["ignored"], "use_calibration": True, "temperature": 0.1},
    )
    assert rated.status_code == 200
    assert rated.json().get("human_labels") == ["Starkt positiv"]


async def test_configuration_includes_anchor_sets(client):
    listed = await client.get("/configurations")
    assert listed.status_code == 200
    row = listed.json()[0]
    assert "anchor_sets" in row
    assert row["anchor_sets"]["sv"]["tone"] > 0
    assert row["anchor_sets"]["sv"]["style"] > 0
    assert row["anchor_sets"]["nb"]["tone"] > 0
    assert row["anchor_sets"]["nb"]["style"] > 0


async def test_patch_configuration_anchor_sets(client):
    listed = await client.get("/configurations")
    config = listed.json()[0]
    config_id = config["id"]
    refs = config["anchor_sets"]

    patched = await client.patch(
        f"/configurations/{config_id}",
        json={"anchor_sets": refs},
    )
    assert patched.status_code == 200
    assert patched.json()["anchor_sets"] == refs


async def test_published_anchor_set_is_immutable(client):
    listed = await client.get("/anchor-sets?status=published&kind=tone&locale=sv")
    anchor_id = listed.json()[0]["id"]
    res = await client.patch(f"/anchor-sets/{anchor_id}", json={"name": "changed"})
    assert res.status_code == 409
