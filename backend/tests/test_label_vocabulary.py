"""Tests for global SSR label vocabulary API."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_label_vocabularies_seeded(client: AsyncClient):
    res = await client.get("/label-vocabularies")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 4
    by_key = {(r["kind"], r["locale"]): r for r in rows}
    tone_sv = by_key[("tone", "sv")]
    assert [e["key"] for e in tone_sv["entries"]] == [
        "strongly_negative",
        "somewhat_negative",
        "neutral",
        "somewhat_positive",
        "strongly_positive",
    ]
    assert tone_sv["entries"][0]["label"] == "Starkt negativ"
    style_en = by_key[("style", "en")]
    assert style_en["entries"][0]["label"] == "Sarkastisk + konkret kritik"
    assert len(style_en["entries"]) == 6


@pytest.mark.asyncio
async def test_get_label_vocabulary(client: AsyncClient):
    res = await client.get("/label-vocabularies/tone/en")
    assert res.status_code == 200
    body = res.json()
    assert body["kind"] == "tone"
    assert body["locale"] == "en"
    assert body["entries"][4]["label"] == "Strongly positive"


@pytest.mark.asyncio
async def test_rename_propagates_to_anchor_set(client: AsyncClient):
    sets = (await client.get("/anchor-sets", params={"kind": "tone", "locale": "sv"})).json()
    tone_sv = next(s for s in sets if s["status"] == "published")
    assert "Starkt negativ" in tone_sv["labels"]
    old_revision = tone_sv["pool_revision"]

    patch = await client.patch(
        "/label-vocabularies/tone/sv",
        json={"rename": [{"key": "strongly_negative", "new_label": "Mycket negativ"}]},
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["entries"][0]["label"] == "Mycket negativ"

    refreshed = (await client.get(f"/anchor-sets/{tone_sv['id']}")).json()
    assert "Mycket negativ" in refreshed["labels"]
    assert "Starkt negativ" not in refreshed["labels"]
    assert refreshed["pool_revision"] == old_revision + 1


@pytest.mark.asyncio
async def test_add_and_remove_label(client: AsyncClient):
    add = await client.patch(
        "/label-vocabularies/tone/sv",
        json={"add": [{"label": "Ambivalent"}]},
    )
    assert add.status_code == 200, add.text
    keys = [e["key"] for e in add.json()["entries"]]
    assert "ambivalent" in keys

    remove = await client.patch(
        "/label-vocabularies/tone/sv",
        json={"remove": [{"key": "ambivalent"}]},
    )
    assert remove.status_code == 200, remove.text
    assert "ambivalent" not in [e["key"] for e in remove.json()["entries"]]


@pytest.mark.asyncio
async def test_remove_default_label_blocked_when_published(client: AsyncClient):
    res = await client.patch(
        "/label-vocabularies/tone/sv",
        json={"remove": [{"key": "neutral"}]},
    )
    assert res.status_code == 409
    assert "published" in res.json()["detail"].lower()
