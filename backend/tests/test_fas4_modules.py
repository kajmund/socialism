"""Fas 4 — kund modules, GET /modules, panel catalog CRUD, campaign module gate."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.dd.expert_keys import expert_role_key


@pytest.mark.asyncio
async def test_modules_api_lists_registry(client: AsyncClient):
    listed = await client.get("/modules")
    assert listed.status_code == 200
    body = listed.json()
    by_id = {row["id"]: row for row in body}
    assert set(by_id) == {"dd", "politik"}
    assert "campaigns" in by_id["dd"]["components"]
    assert "panel_engine" in by_id["dd"]["components"]
    assert by_id["dd"]["has_sub_questions"] is True
    assert by_id["dd"]["has_prompt_defaults"] is True
    assert by_id["politik"]["has_prompt_defaults"] is True
    assert by_id["dd"]["report_modes"] == ["dd"]
    assert "campaigns" not in by_id["politik"]["components"]
    assert set(by_id["politik"]["report_modes"]) == {"quick", "full"}
    assert by_id["politik"]["supports_interview"] is True


@pytest.mark.asyncio
async def test_patch_kund_available_modules(client: AsyncClient):
    listed = await client.get("/kunder")
    assert listed.status_code == 200
    bolag = next(row for row in listed.json() if row["slug"] == "bolag-demo")
    assert bolag["available_modules"] == ["dd"]

    both = await client.patch(
        f"/kunder/{bolag['id']}",
        json={"available_modules": ["dd", "politik", "dd"]},
    )
    assert both.status_code == 200
    assert both.json()["available_modules"] == ["dd", "politik"]

    unknown = await client.patch(
        f"/kunder/{bolag['id']}",
        json={"available_modules": ["dd", "upphandling"]},
    )
    assert unknown.status_code == 400

    empty_id = await client.patch(
        f"/kunder/{bolag['id']}",
        json={"available_modules": ["dd", ""]},
    )
    assert empty_id.status_code == 400

    missing = await client.patch(f"/kunder/{bolag['id']}", json={})
    assert missing.status_code == 400

    gone = await client.patch("/kunder/99999", json={"available_modules": ["dd"]})
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_campaign_create_rejects_module_without_campaigns(client: AsyncClient):
    ok = await client.post("/dd/campaigns", json={"title": "DD ok", "module": "dd"})
    assert ok.status_code == 201
    assert ok.json()["module"] == "dd"

    politik = await client.post("/dd/campaigns", json={"title": "Nope", "module": "politik"})
    assert politik.status_code == 400

    unknown = await client.post("/dd/campaigns", json={"title": "Nope", "module": "upphandling"})
    assert unknown.status_code == 400


@pytest.mark.asyncio
async def test_panel_sub_question_crud_api(client: AsyncClient):
    listed = await client.get("/panel/sub-questions", params={"module": "dd"})
    assert listed.status_code == 200
    keys = {row["key"] for row in listed.json()}
    assert "legal_risk" in keys

    created = await client.post(
        "/panel/sub-questions",
        json={"module": "dd", "key": "kultur_fit", "label": "Kulturfit"},
    )
    assert created.status_code == 201
    row_id = created.json()["id"]
    assert created.json()["key"] == "kultur_fit"
    assert created.json()["active"] is True

    dup = await client.post(
        "/panel/sub-questions",
        json={"module": "dd", "key": "kultur_fit", "label": "Again"},
    )
    assert dup.status_code == 409

    bad_key = await client.post(
        "/panel/sub-questions",
        json={"module": "dd", "key": "Kultur Fit", "label": "Bad"},
    )
    assert bad_key.status_code == 422

    unknown_mod = await client.post(
        "/panel/sub-questions",
        json={"module": "nope", "key": "x", "label": "X"},
    )
    assert unknown_mod.status_code == 400

    patched = await client.patch(
        f"/panel/sub-questions/{row_id}",
        json={"label": "Kulturell passform", "active": False},
    )
    assert patched.status_code == 200
    assert patched.json()["label"] == "Kulturell passform"
    assert patched.json()["active"] is False

    active_only = await client.get("/panel/sub-questions", params={"module": "dd"})
    assert all(row["key"] != "kultur_fit" for row in active_only.json())

    with_inactive = await client.get(
        "/panel/sub-questions",
        params={"module": "dd", "include_inactive": True},
    )
    assert any(row["key"] == "kultur_fit" for row in with_inactive.json())

    missing = await client.patch("/panel/sub-questions/99999", json={"label": "x"})
    assert missing.status_code == 404

    # Hard-delete unused question (kultur_fit was only soft-deactivated above — recreate)
    recreate = await client.post(
        "/panel/sub-questions",
        json={"module": "dd", "key": "temp_delete_me", "label": "Temp"},
    )
    assert recreate.status_code == 201
    temp_id = recreate.json()["id"]
    deleted = await client.delete(f"/panel/sub-questions/{temp_id}")
    assert deleted.status_code == 204
    gone = await client.get(
        "/panel/sub-questions", params={"module": "dd", "include_inactive": True}
    )
    assert all(row["key"] != "temp_delete_me" for row in gone.json())

    missing_del = await client.delete("/panel/sub-questions/99999")
    assert missing_del.status_code == 404


@pytest.mark.asyncio
async def test_panel_catalog_rejects_duplicate_sort_order(client: AsyncClient):
    listed = await client.get(
        "/panel/sub-questions", params={"module": "dd", "include_inactive": True}
    )
    assert listed.status_code == 200
    taken = listed.json()[0]["sort_order"]

    clash = await client.post(
        "/panel/sub-questions",
        json={"module": "dd", "key": "dup_sort", "label": "Dup", "sort_order": taken},
    )
    assert clash.status_code == 409
    assert "Sort order" in clash.json()["detail"]

    created = await client.post(
        "/panel/sub-questions",
        json={"module": "dd", "key": "dup_sort", "label": "Dup"},
    )
    assert created.status_code == 201
    row_id = created.json()["id"]
    own = created.json()["sort_order"]

    patch_clash = await client.patch(
        f"/panel/sub-questions/{row_id}", json={"sort_order": taken}
    )
    assert patch_clash.status_code == 409

    keep = await client.patch(
        f"/panel/sub-questions/{row_id}", json={"sort_order": own}
    )
    assert keep.status_code == 200

    experts = await client.get(
        "/panel/expert-profiles", params={"module": "dd", "include_inactive": True}
    )
    assert experts.status_code == 200
    scoring = next(row for row in experts.json() if row["key"] != "spinndoctor")
    assert scoring["module"] == "dd"
    assert scoring["modules"] == ["dd"]
    expert_key = scoring["key"]
    expert_clash = await client.post(
        "/panel/expert-profiles",
        json={"module": "politik", "key": expert_key, "name": "Dup-nyckel"},
    )
    assert expert_clash.status_code == 409


@pytest.mark.asyncio
async def test_panel_expert_profile_crud_api(client: AsyncClient):
    listed = await client.get("/panel/expert-profiles", params={"module": "dd"})
    assert listed.status_code == 200
    spin = next(row for row in listed.json() if row["key"] == "spinndoctor")
    assert set(spin["modules"]) == {"dd", "politik"}
    scoring = [row for row in listed.json() if row["key"] != "spinndoctor"]
    assert len(scoring) == 4
    assert all(row["module"] == "dd" and row["modules"] == ["dd"] for row in scoring)

    created = await client.post(
        "/panel/expert-profiles",
        json={
            "module": "dd",
            "name": "IT-revisor",
            "description": "Granskar system och access.",
            "kompetensomrade": "IT-revision",
        },
    )
    assert created.status_code == 201
    assert created.json()["key"] == expert_role_key("IT-revisor")
    assert created.json()["module"] == "dd"
    assert created.json()["modules"] == ["dd"]
    row_id = created.json()["id"]

    patched = await client.patch(
        f"/panel/expert-profiles/{row_id}",
        json={"radgivningsstil": "Metodisk", "active": False},
    )
    assert patched.status_code == 200
    assert patched.json()["radgivningsstil"] == "Metodisk"
    assert patched.json()["active"] is False

    active_only = await client.get("/panel/expert-profiles", params={"module": "dd"})
    assert all(row["id"] != row_id for row in active_only.json())
