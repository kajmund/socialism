"""Tests for SSR anchor library API and configuration wiring."""

from __future__ import annotations

import pytest

from app.services.anchor_calibration import MIN_CALIBRATION_ITEMS
from app.services.ssr import set_embedder


@pytest.fixture
def mock_embedder():
    async def _mock(texts: list[str]) -> list[list[float]]:
        return [[float((hash(t) + i) % 7) for i in range(8)] for t in texts]

    set_embedder(_mock)
    yield
    set_embedder(None)


@pytest.fixture
def calibration_embedder():
    """Map seedN texts to unit vectors so calibration hits the matching label index."""

    async def _mock(texts: list[str]) -> list[list[float]]:
        dim = 5
        out: list[list[float]] = []
        for t in texts:
            if t.startswith("seed"):
                idx = int(t[4:])
                vec = [0.0] * dim
                vec[idx % dim] = 1.0
                out.append(vec)
            else:
                vec = [0.0] * dim
                vec[0] = 1.0
                out.append(vec)
        return out

    set_embedder(_mock)
    yield
    set_embedder(None)


async def _seed_calibration(client, anchor_id: int, labels: list[str]) -> None:
    for i in range(MIN_CALIBRATION_ITEMS):
        label = labels[i % len(labels)]
        res = await client.post(
            f"/anchor-sets/{anchor_id}/calibration",
            json={"text": f"seed{i % len(labels)}", "human_label": label},
        )
        assert res.status_code == 201, res.text


async def test_list_anchor_sets_seeded(client):
    res = await client.get("/anchor-sets")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) >= 4
    assert any(r["kind"] == "tone" and r["locale"] == "sv" for r in rows)
    seeded = next(r for r in rows if r["kind"] == "tone" and r["locale"] == "sv")
    assert seeded["validation_status"] == "untested"


async def test_create_publish_and_test_anchor_set(client, calibration_embedder):
    labels = [
        "Starkt negativ",
        "Något negativ",
        "Neutral",
        "Något positiv",
        "Starkt positiv",
    ]
    create = await client.post(
        "/anchor-sets",
        json={
            "name": "test_tone_sv",
            "kind": "tone",
            "locale": "sv",
            "version": "test",
            "labels": labels,
            "statements": [f"seed{i}" for i in range(5)],
            "status": "draft",
        },
    )
    assert create.status_code == 201
    anchor_id = create.json()["id"]

    await _seed_calibration(client, anchor_id, labels)

    pub = await client.post(f"/anchor-sets/{anchor_id}/publish", json={})
    assert pub.status_code == 200, pub.text
    body = pub.json()
    assert body["status"] == "published"
    assert body["validation_status"] == "ok"
    assert body["calibration_accuracy"] is not None
    assert body["calibration_accuracy"] >= 0.55

    test = await client.post(
        f"/anchor-sets/{anchor_id}/test",
        json={"texts": ["Det här är bra", "Uselt"], "temperature": 0.1},
    )
    assert test.status_code == 200
    body = test.json()
    assert body["labels"]
    assert len(body["per_text"]) == 2


async def test_publish_blocked_without_enough_calibration(client, mock_embedder):
    create = await client.post(
        "/anchor-sets",
        json={
            "name": "too_few_cal",
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
    pub = await client.post(f"/anchor-sets/{anchor_id}/publish", json={})
    assert pub.status_code == 400
    detail = pub.json()["detail"]
    assert detail["code"] == "calibration_too_few"


async def test_publish_requires_acknowledgement_for_low_accuracy(client, monkeypatch):
    create = await client.post(
        "/anchor-sets",
        json={
            "name": "low_acc",
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
    labels = create.json()["labels"]
    await _seed_calibration(client, anchor_id, labels)

    async def _fake_run(session, row, *, temperature, persist=True):
        return {
            "macro_accuracy": 0.45,
            "missing_labels": [],
            "calibration_count": MIN_CALIBRATION_ITEMS,
        }

    monkeypatch.setattr(
        "app.services.anchor_calibration.run_calibration_test",
        _fake_run,
    )

    blocked = await client.post(f"/anchor-sets/{anchor_id}/publish", json={})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "acknowledgement_required"

    ok = await client.post(
        f"/anchor-sets/{anchor_id}/publish",
        json={"acknowledge_warnings": True},
    )
    assert ok.status_code == 200
    assert ok.json()["calibration_publish_override"] is True


async def test_publish_blocks_accuracy_below_40_even_with_acknowledge(client, monkeypatch):
    create = await client.post(
        "/anchor-sets",
        json={
            "name": "very_low_acc",
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
    labels = create.json()["labels"]
    await _seed_calibration(client, anchor_id, labels)

    async def _fake_run(session, row, *, temperature, persist=True):
        return {
            "macro_accuracy": 0.10,
            "missing_labels": [],
            "calibration_count": MIN_CALIBRATION_ITEMS,
        }

    monkeypatch.setattr(
        "app.services.anchor_calibration.run_calibration_test",
        _fake_run,
    )

    blocked = await client.post(f"/anchor-sets/{anchor_id}/publish", json={})
    assert blocked.status_code == 400
    assert blocked.json()["detail"]["code"] == "accuracy_too_low"
    assert blocked.json()["detail"]["requires_acknowledgement"] is False

    still_blocked = await client.post(
        f"/anchor-sets/{anchor_id}/publish",
        json={"acknowledge_warnings": True},
    )
    assert still_blocked.status_code == 400
    assert still_blocked.json()["detail"]["code"] == "accuracy_too_low"


async def test_calibration_and_test_with_human_labels(client, calibration_embedder):
    labels = [
        "Starkt negativ",
        "Något negativ",
        "Neutral",
        "Något positiv",
        "Starkt positiv",
    ]
    create = await client.post(
        "/anchor-sets",
        json={
            "name": "cal_tone",
            "kind": "tone",
            "locale": "sv",
            "labels": labels,
            "statements": [f"seed{i}" for i in range(5)],
        },
    )
    anchor_id = create.json()["id"]
    item = await client.post(
        f"/anchor-sets/{anchor_id}/calibration",
        json={"text": "seed4", "human_label": "Starkt positiv"},
    )
    assert item.status_code == 201

    rated = await client.post(
        f"/anchor-sets/{anchor_id}/test",
        json={"texts": ["ignored"], "use_calibration": True, "temperature": 0.1},
    )
    assert rated.status_code == 200
    body = rated.json()
    assert body.get("human_labels") == ["Starkt positiv"]
    assert body.get("macro_accuracy") == 1.0


async def test_configuration_includes_anchor_sets(client):
    listed = await client.get("/configurations")
    assert listed.status_code == 200
    row = listed.json()[0]
    assert "anchor_sets" in row
    assert row["anchor_sets"]["sv"]["tone"] > 0
    assert row["anchor_sets"]["sv"]["style"] > 0


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

