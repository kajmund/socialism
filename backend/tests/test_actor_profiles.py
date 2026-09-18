import io
import json
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app.services.actor_profiles import ActorProfileTools
from tests.conftest import (
    ADMIN_USER_ID,
    BOLAG_USER_ID,
    TEST_CUSTOMER_ID,
    USER_USER_ID,
    mint_access_token,
)


async def proposal(factory, *, user_id=USER_USER_ID, target="current_user", changes=None):
    async with factory() as session:
        tools = ActorProfileTools(
            session,
            user_id=user_id,
            customer_id=TEST_CUSTOMER_ID,
            conversation="expert:test:interview",
        )
        return json.loads(
            await tools(
                "propose_actor_context_update",
                {"target": target, "changes": changes or {"job_title": "Jurist"}},
            )
        )


async def test_profile_patch_clearing_and_privileges(user_client):
    res = await user_client.patch(
        "/me", json={"first_name": "  Anna ", "last_name": "Andersson", "job_title": "Jurist"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["first_name"] == "Anna"
    assert (await user_client.patch("/me", json={"role": "admin"})).status_code == 422
    assert (await user_client.patch("/me", json={"kund_id": 2})).status_code == 422
    res = await user_client.patch("/me", json={"job_title": None})
    assert res.json()["job_title"] is None
    assert res.json()["last_name"] == "Andersson"
    assert (await user_client.get("/me")).json()["first_name"] == "Anna"


async def test_customer_fields_and_scope(client):
    user_client = ScopedClient(client, USER_USER_ID)
    bolag_client = ScopedClient(client, BOLAG_USER_ID)
    res = await client.patch(
        "/kunder/1",
        json={
            "organization_name": "Test AB",
            "organization_number": "012345-6789",
            "city": "Stockholm",
            "country_code": "se",
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["organization_number"] == "012345-6789"
    assert res.json()["country_code"] == "SE"
    assert (await user_client.patch("/kunder/1", json={"city": "X"})).status_code == 403
    assert (await bolag_client.get("/kunder/1")).status_code == 403
    assert (await client.patch("/kunder/1", json={"city": None})).json()[
        "organization_name"
    ] == "Test AB"


async def test_proposal_requires_real_approval(client_db, user_client):
    _, factory = client_db
    item = await proposal(factory)
    assert item["saved"] is False
    assert (await user_client.get("/me")).json()["job_title"] is None
    assert (
        await user_client.post(
            f"/me/profile-proposals/{item['id']}/decision",
            json={"conversation": item["conversation"], "decision": "approve", "consent": True},
        )
    ).status_code == 422
    res = await user_client.post(
        f"/me/profile-proposals/{item['id']}/decision",
        json={"conversation": item["conversation"], "decision": "approve"},
    )
    assert res.status_code == 200, res.text
    assert (await user_client.get("/me")).json()["job_title"] == "Jurist"
    revision = (await user_client.get("/me")).json()["profile_revision"]
    assert (
        await user_client.post(
            f"/me/profile-proposals/{item['id']}/decision",
            json={"conversation": item["conversation"], "decision": "approve"},
        )
    ).status_code == 200
    assert (await user_client.get("/me")).json()["profile_revision"] == revision


async def test_reject_other_user_conversation_conflict(client_db, client):
    user_client = ScopedClient(client, USER_USER_ID)
    _, factory = client_db
    item = await proposal(factory)
    path = f"/me/profile-proposals/{item['id']}/decision"
    assert (
        await client.post(path, json={"conversation": item["conversation"], "decision": "approve"})
    ).status_code == 404
    assert (
        await user_client.post(path, json={"conversation": "other", "decision": "approve"})
    ).status_code == 404
    await user_client.patch("/me", json={"job_title": "VD"})
    assert (
        await user_client.post(
            path, json={"conversation": item["conversation"], "decision": "approve"}
        )
    ).status_code == 409
    assert (await user_client.get("/me")).json()["job_title"] == "VD"
    assert (
        await user_client.post(
            path, json={"conversation": item["conversation"], "decision": "reject"}
        )
    ).status_code == 200


async def test_tools_reject_privilege_and_resolve_selected_customer(client_db):
    _, factory = client_db
    async with factory() as session:
        tools = ActorProfileTools(
            session,
            user_id=ADMIN_USER_ID,
            customer_id=TEST_CUSTOMER_ID,
            conversation="review:1",
            requested_by_id=USER_USER_ID,
        )
        result = json.loads(await tools("get_actor_context", {}))
        assert result["customer"]["id"] == TEST_CUSTOMER_ID, mint_access_token
        assert result["current_user"]["id"] == ADMIN_USER_ID
        assert result["requested_by"]["id"] == USER_USER_ID
        with pytest.raises(ValueError):
            await tools("get_actor_context", {"user_id": BOLAG_USER_ID})
        with pytest.raises(ValueError):
            await tools(
                "propose_actor_context_update",
                {"target": "current_user", "changes": {"role": "admin"}},
            )
    assert (await proposal(factory, target="customer", changes={"city": "Oslo"}))[
        "error"
    ] == "customer_edit_requires_admin"


async def test_avatar_validated_scoped_and_replaced(client):
    user_client = ScopedClient(client, USER_USER_ID)
    bolag_client = ScopedClient(client, BOLAG_USER_ID)
    data = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(data, "PNG")
    path = f"/profiles/{USER_USER_ID}/avatar"
    res = await user_client.post(path, files={"file": ("avatar.png", data.getvalue(), "image/png")})
    assert res.status_code == 200, res.text
    assert (await user_client.get(path)).headers["content-type"] == "image/jpeg"
    before = (await user_client.get(path)).content
    assert (await bolag_client.get(path)).status_code == 403
    assert (await bolag_client.delete(path)).status_code == 403
    assert (
        await user_client.post(path, files={"file": ("bad.png", b"<svg/>", "image/png")})
    ).status_code == 422
    assert (await user_client.get(path)).content == before
    assert (await user_client.delete(path)).status_code == 200
    assert (await user_client.get(path)).status_code == 404
    assert (
        await client.post(
            f"/profiles/{ADMIN_USER_ID}/avatar",
            files={"file": ("a.png", data.getvalue(), "image/png")},
        )
    ).status_code == 200


async def test_context_only_read_when_model_calls_tool(client_db, monkeypatch):
    from types import SimpleNamespace

    from app.services.dd import company_mcp

    _, factory = client_db
    async with factory() as session:
        handler = ActorProfileTools(
            session, user_id=USER_USER_ID, customer_id=1, conversation="expert:x"
        )
        tracked = AsyncMock(side_effect=handler.__call__)
        reply = SimpleNamespace(content="Hej!", tool_calls=None, role="assistant")
        monkeypatch.setattr(company_mcp, "complete_with_tools", AsyncMock(return_value=reply))
        await company_mcp.run_company_tool_loop(
            [], allowed_tools=frozenset({"get_actor_context"}), actor_tool_handler=tracked
        )
        tracked.assert_not_called()
        tool = SimpleNamespace(
            id="call_1", function=SimpleNamespace(name="get_actor_context", arguments="{}")
        )
        monkeypatch.setattr(
            company_mcp,
            "complete_with_tools",
            AsyncMock(
                side_effect=[
                    SimpleNamespace(content=None, tool_calls=[tool], role="assistant"),
                    reply,
                ]
            ),
        )
        working, _ = await company_mcp.run_company_tool_loop(
            [], allowed_tools=frozenset({"get_actor_context"}), actor_tool_handler=tracked
        )
        tracked.assert_awaited_once_with("get_actor_context", {})
        assert json.loads(working[1]["content"])["current_user"]["id"] == USER_USER_ID


class ScopedClient:
    def __init__(self, client, user_id):
        self.client = client
        self.headers = {
            "Authorization": f"Bearer {mint_access_token(sub=user_id, email='test@test.local')}"
        }

    def __getattr__(self, name):
        async def call(*args, **kwargs):
            return await getattr(self.client, name)(*args, headers=self.headers, **kwargs)

        return call


async def test_word_profile_lookup_only_when_requested(monkeypatch):
    from app.services.expertgranskning import actor_context as actors

    # Use catalog defaults as in production, not a hand-written test prompt.
    from app.services.prompt_catalog import PROMPT_FIELDS

    prompts = {field["key"]: field["defaults"]["sv"] for field in PROMPT_FIELDS}

    class Limiter:
        timings = type("Timings", (), {"record_actor_context_resolved": lambda *_: None})()

        async def run(self, _name, callback):
            return await callback()

    handler = AsyncMock(
        return_value=json.dumps(
            {"current_user": {"job_title": "Jurist"}, "customer": None, "requested_by": None}
        )
    )
    complete = AsyncMock(
        return_value=actors.ActorContext(user_role="köpare", perspective_known=True)
    )
    monkeypatch.setattr(actors, "complete_word_structured", complete)
    await actors.resolve_actor_context(
        prompts=prompts,
        interview=None,
        answers=[],
        review_intent="Granska för köparen",
        limiter=Limiter(),
        actor_profile_handler=handler,
    )
    handler.assert_not_called()
    complete.side_effect = [
        actors.ActorContext(needs_actor_profile=True),
        actors.ActorContext(user_role="köpare", perspective_known=True),
    ]
    result = await actors.resolve_actor_context(
        prompts=prompts,
        interview=None,
        answers=[],
        review_intent="Granska för köparen",
        limiter=Limiter(),
        actor_profile_handler=handler,
    )
    handler.assert_awaited_once_with("get_actor_context", {})
    assert result.user_role == "köpare"
