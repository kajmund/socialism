"""Workspace defaults and membership enforce organisation/client boundaries."""

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.database.models import Kund, UserAccount
from app.database.workspaces import Workspace, WorkspaceMembership
from app.services.workspaces import (
    add_workspace_member,
    create_client_workspace,
    require_workspace_customer,
    resolve_readable_workspace_ids,
    resolve_workspace,
)
from tests.conftest import ADMIN_USER_ID, USER_USER_ID, mint_access_token


async def _users(factory):
    async with factory() as session:
        other = Kund(name="Other organisation", slug="workspace-other", available_modules=[])
        session.add(other)
        await session.flush()
        session.add_all(
            [
                UserAccount(id="colleague", email="colleague@test.local", role="user", kund_id=1),
                UserAccount(
                    id="outsider", email="outsider@test.local", role="user", kund_id=other.id
                ),
            ]
        )
        await session.commit()
        return other.id


async def test_omitted_workspace_is_stable_company_default(client_db, user_token):
    client, factory = client_db
    client.headers["Authorization"] = f"Bearer {user_token}"
    first = await client.get("/workspaces")
    second = await client.get("/workspaces")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(first.json()) == 1
    common = first.json()[0]
    assert common["kind"] == "company" and common["customer_id"] == 1
    async with factory() as session:
        resolved = await resolve_workspace(session, customer_id=1, user_id=USER_USER_ID)
        assert resolved.id == common["id"]
        assert await resolve_readable_workspace_ids(
            session, customer_id=1, user_id=USER_USER_ID
        ) == [common["id"]]
        assert await session.scalar(select(func.count()).select_from(Workspace)) == 1


async def test_client_membership_and_research_scope_exclude_sibling_clients(client_db, user_token):
    client, factory = client_db
    await _users(factory)
    client.headers["Authorization"] = f"Bearer {user_token}"
    first = await client.post("/workspaces", json={"name": "Klient A", "kind": "client"})
    second = await client.post("/workspaces", json={"name": "Klient B"})
    assert first.status_code == second.status_code == 201
    a, b = first.json(), second.json()
    common = next(
        row for row in (await client.get("/workspaces")).json() if row["kind"] == "company"
    )
    async with factory() as session:
        assert await resolve_readable_workspace_ids(
            session, customer_id=1, user_id=USER_USER_ID, workspace_id=a["id"]
        ) == [common["id"], a["id"]]
        assert b["id"] not in await resolve_readable_workspace_ids(
            session, customer_id=1, user_id=USER_USER_ID, workspace_id=a["id"]
        )
        with pytest.raises(HTTPException) as failure:
            await resolve_workspace(
                session, customer_id=1, user_id="colleague", workspace_id=a["id"]
            )
        assert failure.value.status_code == 404
    client.headers["Authorization"] = f"Bearer {mint_access_token(sub='colleague')}"
    assert (await client.get("/workspaces")).json() == [common]


async def test_manager_can_share_only_with_organisation_members(client_db, user_token):
    client, factory = client_db
    await _users(factory)
    client.headers["Authorization"] = f"Bearer {user_token}"
    workspace = (await client.post("/workspaces", json={"name": "Klient A"})).json()
    url = f"/workspaces/{workspace['id']}/members"
    denied = await client.post(url, json={"user_id": "outsider"})
    assert denied.status_code == 404
    shared = await client.post(url, json={"user_id": "colleague"})
    assert shared.status_code == 201
    assert shared.json()["role"] == "member"
    client.headers["Authorization"] = f"Bearer {mint_access_token(sub='colleague')}"
    assert workspace in (await client.get("/workspaces")).json()
    assert (
        await client.post(url, json={"user_id": USER_USER_ID, "role": "manager"})
    ).status_code == 403


async def test_foreign_workspace_is_hidden_even_with_copied_membership(client_db):
    _client, factory = client_db
    foreign_customer = await _users(factory)
    async with factory() as session:
        private = await create_client_workspace(
            session, customer_id=foreign_customer, user_id="outsider", name="Private"
        )
        session.add(
            WorkspaceMembership(workspace_id=private.id, user_id=USER_USER_ID, role="manager")
        )
        await session.commit()
        with pytest.raises(HTTPException) as failure:
            await resolve_workspace(
                session, customer_id=1, user_id=USER_USER_ID, workspace_id=private.id
            )
        assert failure.value.status_code == 404
        with pytest.raises(HTTPException) as failure:
            await resolve_workspace(session, customer_id=foreign_customer, user_id=USER_USER_ID)
        assert failure.value.status_code == 404


async def test_global_admin_must_select_organisation_and_cannot_share_foreign_user(client_db):
    client, factory = client_db
    assert (await client.get("/workspaces")).status_code == 400
    assert (await client.get("/workspaces?customer_id=1")).status_code == 200
    foreign_customer = await _users(factory)
    async with factory() as session:
        admin = await session.get(UserAccount, ADMIN_USER_ID)
        assert (
            await require_workspace_customer(session, admin, foreign_customer) == foreign_customer
        )
        private = await create_client_workspace(
            session, customer_id=1, user_id=USER_USER_ID, name="A"
        )
        with pytest.raises(HTTPException) as failure:
            await add_workspace_member(
                session,
                customer_id=1,
                actor_user_id=ADMIN_USER_ID,
                workspace_id=private.id,
                member_user_id="outsider",
                role="member",
            )
        assert failure.value.status_code == 404


@pytest.mark.parametrize("body", [{"name": "   "}, {"name": "A", "kind": "company"}])
async def test_workspace_creation_rejects_invalid_name_and_duplicate_company(
    client, user_token, body
):
    client.headers["Authorization"] = f"Bearer {user_token}"
    assert (await client.post("/workspaces", json=body)).status_code == 422


async def test_user_cannot_switch_to_another_organisation(client_db, user_token):
    client, factory = client_db
    foreign_customer = await _users(factory)
    client.headers["Authorization"] = f"Bearer {user_token}"
    assert (await client.get(f"/workspaces?customer_id={foreign_customer}")).status_code == 404
    assert (
        await client.post(f"/workspaces?customer_id={foreign_customer}", json={"name": "A"})
    ).status_code == 404
