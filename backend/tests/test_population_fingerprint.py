"""Population fingerprint truth and QA."""

from __future__ import annotations

import pytest

from app.schemas.domain import DistGroup, DistRow, PopulationRecipe
from app.services.population_fingerprint import (
    fingerprint_from_dist,
    infer_age_bucket,
    infer_lean_key_optional,
    MemberSlots,
    fingerprint_from_slot_rows,
)


def _sample_recipe(*, size: int = 5, seed: int = 7) -> PopulationRecipe:
    return PopulationRecipe(
        size=size,
        locale="local",
        seed=seed,
        dist={
            "age": DistGroup(
                label="Ålder",
                rows=[
                    DistRow(k="ung", l="Ung", v=40),
                    DistRow(k="medel", l="Medel", v=40),
                    DistRow(k="aldre", l="Äldre", v=20),
                ],
            ),
            "district": DistGroup(
                label="Ort",
                rows=[
                    DistRow(k="centrum", l="Centrum", v=50),
                    DistRow(k="forort", l="Förort", v=50),
                ],
            ),
            "occupation": DistGroup(
                label="Yrke",
                rows=[DistRow(k="vard", l="Vård", v=100)],
            ),
            "leaning": DistGroup(
                label="Lutning",
                rows=[
                    DistRow(k="vanster", l="Vänster", v=34),
                    DistRow(k="mitt", l="Mitt", v=33),
                    DistRow(k="hoger", l="Höger", v=33),
                ],
            ),
        },
    )


def test_infer_age_bucket_matches_generation_ranges():
    assert infer_age_bucket(25) == "ung"
    assert infer_age_bucket(45) == "medel"
    assert infer_age_bucket(65) == "aldre"


def test_fingerprint_from_dist_is_target_summary():
    recipe = _sample_recipe()
    target = fingerprint_from_dist(recipe.dist)
    assert target[0] == [40, 40, 20]
    assert sum(target[1]) == 100
    assert sum(target[2]) == 100


@pytest.mark.asyncio
async def test_run_generate_returns_target_and_achieved_fingerprints(client):
    generated = await client.post(
        "/populations/generate",
        json={"recipe": _sample_recipe(size=5, seed=7).model_dump(), "mode": "replace"},
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["target_fingerprint"][0] == [40, 40, 20]
    assert len(payload["fingerprint"]) == 3


@pytest.mark.asyncio
async def test_add_member_recomputes_fingerprint(client):
    generated = await client.post(
        "/populations/generate",
        json={"recipe": _sample_recipe(size=4, seed=1).model_dump(), "mode": "replace"},
    )
    payload = generated.json()
    create = await client.post(
        "/populations",
        json={"name": "Fp sync pop", "generation_id": payload["generation_id"]},
    )
    assert create.status_code == 201
    pop = create.json()
    before_fp = list(pop["fp"])

    persona = await client.post(
        "/personas",
        json={
            "id": "fpadd1",
            "name": "Extra Person",
            "age": 22,
            "occ": "Student",
            "district": "Centrum",
            "quote": "Test",
            "origin": "manuell",
        },
    )
    assert persona.status_code == 201

    added = await client.post(
        f"/populations/{pop['id']}/members",
        json={
            "persona_id": "fpadd1",
            "name": "Extra Person",
            "initials": "EP",
            "age": 22,
            "occ": "Student",
            "district": "Centrum",
            "trait": "Test",
        },
    )
    assert added.status_code == 201

    detail = await client.get(f"/populations/{pop['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["size"] == 5
    assert body["fp"] != before_fp
    assert body["target_fp"][0] == [40, 40, 20]


@pytest.mark.asyncio
async def test_inferred_population_skips_leaning_qa_warnings(client):
    """Legacy backfill must not emit false leaning deviation warnings."""
    persona = (
        await client.post(
            "/personas",
            json={
                "id": "infp1",
                "name": "Legacy One",
                "age": 40,
                "occ": "Lärare",
                "district": "Centrum",
                "quote": "Q",
                "origin": "manuell",
            },
        )
    ).json()
    recipe = _sample_recipe(size=1).model_dump()
    create = await client.post(
        "/populations",
        json={
            "name": "Inferred QA pop",
            "fingerprint": [[100, 0, 0], [100, 0, 0], [100, 0, 0]],
            "recipe": {
                "size": 1,
                "locale": "local",
                "dist": recipe["dist"],
            },
            "members": [
                {
                    "persona_id": persona["id"],
                    "name": persona["name"],
                    "initials": "LO",
                    "age": 40,
                    "occ": "Lärare",
                    "district": "Centrum",
                    "trait": "Q",
                }
            ],
        },
    )
    assert create.status_code == 201
    pop_id = create.json()["id"]

    detail = await client.get(f"/populations/{pop_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["fingerprint_inferred"] is True
    assert not any("Lutning" in w for w in body["qa_warnings"])


@pytest.mark.asyncio
async def test_recipe_update_blocked_without_generation(client):
    generated = await client.post(
        "/populations/generate",
        json={"recipe": _sample_recipe(size=3, seed=2).model_dump(), "mode": "replace"},
    )
    payload = generated.json()
    create = await client.post(
        "/populations",
        json={"name": "Readonly recipe pop", "generation_id": payload["generation_id"]},
    )
    pop_id = create.json()["id"]

    blocked = await client.put(
        f"/populations/{pop_id}",
        json={"recipe": {"size": 3, "dist": {}, "locale": "local"}},
    )
    assert blocked.status_code == 400


def test_infer_lean_key_optional_empty_returns_none():
    assert infer_lean_key_optional("", {"rows": [{"k": "mitt", "l": "Mitt", "v": 100}]}) is None


def test_fingerprint_leaning_zeros_without_lean_keys():
    dist = _sample_recipe(size=1).dist
    fp = fingerprint_from_slot_rows(
        [MemberSlots(age_bucket="medel", lean_key=None, district_key="centrum")],
        dist,
    )
    assert fp[1] == [0, 0, 0]
