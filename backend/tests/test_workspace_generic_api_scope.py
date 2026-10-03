"""Generic job/execution endpoints must not bypass workspace membership."""

import pytest

from sqlalchemy import delete

from app.database.models import Job, StoredObject
from app.database.workspaces import WorkspaceMembership
from app.database.workspace_ids import company_workspace_id
from tests.conftest import USER_USER_ID


async def _workspace(client, user_token):
    client.headers["Authorization"] = f"Bearer {user_token}"
    return (await client.post("/workspaces", json={"name": "Private client"})).json()["id"]


async def test_jobs_hide_revoke_and_archive_only_readable_workspaces(client_db, user_token):
    client, factory = client_db
    workspace = await _workspace(client, user_token)
    async with factory.begin() as session:
        session.add_all(
            [
                Job(
                    id="private-job",
                    customer_id=1,
                    kind="report_generate",
                    status="failed",
                    request={"workspace_id": workspace, "owner_user_id": USER_USER_ID},
                ),
                Job(
                    id="unscoped-job",
                    customer_id=1,
                    kind="report_generate",
                    status="succeeded",
                    request={},
                ),
            ]
        )
    assert (await client.get("/jobs/private-job")).status_code == 200
    async with factory.begin() as session:
        await session.execute(
            delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace)
        )
    assert {row["id"] for row in (await client.get("/jobs")).json()} == {"unscoped-job"}
    denied = [
        await client.get("/jobs/private-job"),
        await client.post("/jobs/private-job/resume"),
        await client.post("/jobs/private-job/rerun"),
        await client.patch("/jobs/private-job", json={"archived": True}),
    ]
    assert [response.status_code for response in denied] == [404] * 4
    archived = await client.post("/jobs/archive-finished")
    assert [row["id"] for row in archived.json()] == ["unscoped-job"]
    async with factory() as session:
        assert (await session.get(Job, "private-job")).archived_at is None


async def test_document_ingest_job_cannot_omit_workspace_to_bypass_revoked_membership(
    client_db, user_token
):
    client, factory = client_db
    workspace = await _workspace(client, user_token)
    async with factory.begin() as session:
        session.add(
            StoredObject(
                id="private-object",
                customer_id=1,
                workspace_id=workspace,
                owner_user_id=USER_USER_ID,
                module="dd",
                kind="underlag",
                bucket="firm",
                object_key="x",
                filename="x.txt",
                content_type="text/plain",
                size_bytes=1,
            )
        )
        await session.execute(
            delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace)
        )
    denied = await client.post(
        "/jobs",
        json={
            "kind": "document_ingest",
            "request": {"object_id": "private-object", "owner_user_id": USER_USER_ID},
        },
    )
    assert denied.status_code == 404


async def test_every_execution_read_and_action_requires_current_workspace_membership(
    client_db, user_token
):
    client, factory = client_db
    workspace = await _workspace(client, user_token)
    created = await client.post(
        "/execution/runs",
        json={
            "customer_id": 1,
            "module": "dd",
            "title": "Private",
            "context": {"workspace_id": workspace},
        },
    )
    assert created.status_code == 201
    run = created.json()["id"]
    attempt = (
        await client.post(f"/execution/runs/{run}/attempts", json={"attempt_type": "test"})
    ).json()["id"]
    async with factory.begin() as session:
        await session.execute(
            delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace)
        )
    reads = [
        f"/execution/runs/{run}",
        f"/execution/runs/{run}/attempts",
        f"/execution/attempts/{attempt}",
        f"/execution/attempts/{attempt}/evidence",
        f"/execution/attempts/{attempt}/result",
        f"/execution/attempts/{attempt}/progress-events",
        f"/execution/attempts/{attempt}/research-overview",
    ]
    for path in reads:
        response = await client.get(path)
        assert response.status_code == 404, (path, response.text)
    for action in ("clone", "research", "execute"):
        response = await client.post(f"/execution/attempts/{attempt}/{action}", json={})
        assert response.status_code == 404, (action, response.text)
    assert (
        await client.post(f"/execution/runs/{run}/attempts", json={"attempt_type": "test"})
    ).status_code == 404
    assert (
        await client.post(
            "/execution/runs",
            json={
                "customer_id": 1,
                "module": "dd",
                "title": "Private",
                "context": {"workspace_id": workspace},
            },
        )
    ).status_code == 404


async def test_execution_cannot_override_run_workspace_with_research_context(client, user_token):
    first = await _workspace(client, user_token)
    second = (await client.post("/workspaces", json={"name": "Other client"})).json()["id"]
    run = (
        await client.post(
            "/execution/runs",
            json={
                "customer_id": 1,
                "module": "dd",
                "title": "A",
                "context": {"workspace_id": first},
            },
        )
    ).json()["id"]
    response = await client.post(
        f"/execution/runs/{run}/attempts",
        json={
            "attempt_type": "test",
            "research_objective": "Question",
            "research_context": {"workspace_id": second},
        },
    )
    assert response.status_code == 409
    attempt = (
        await client.post(f"/execution/runs/{run}/attempts", json={"attempt_type": "test"})
    ).json()["id"]
    response = await client.post(
        f"/execution/attempts/{attempt}/research",
        json={
            "research_objective": "Question",
            "research_context": {"workspace_id": second},
        },
    )
    assert response.status_code == 409


@pytest.mark.parametrize("injected_field", ["readable_workspace_ids", "document_manifest"])
async def test_active_workspace_cannot_extend_scope_to_a_sibling_client(
    client, user_token, injected_field
):
    active = await _workspace(client, user_token)
    sibling = (await client.post("/workspaces", json={"name": "Sibling"})).json()["id"]
    context = {
        "workspace_id": active,
        "readable_workspace_ids": [company_workspace_id(1), active],
        "document_manifest": [],
    }
    if injected_field == "readable_workspace_ids":
        context[injected_field].append(sibling)
    else:
        context[injected_field].append(
            {
                "workspace_id": sibling,
                "source_object_id": "sibling-object",
                "document_version_id": "sibling-version",
            }
        )
    run = await client.post(
        "/execution/runs",
        json={
            "customer_id": 1,
            "module": "dd",
            "title": "Injected scope",
            "context": context,
        },
    )
    assert run.status_code == 404
    job = await client.post(
        "/jobs",
        json={
            "kind": "report_generate",
            "request": {**context, "owner_user_id": USER_USER_ID, "report_id": "report"},
        },
    )
    assert job.status_code == 404


@pytest.mark.parametrize(
    "fields",
    [
        {"document_manifest": []},
        {"readable_workspace_ids": []},
        {"document_manifest": [], "readable_workspace_ids": []},
    ],
)
async def test_generic_producers_reject_selection_without_a_workspace(client, user_token, fields):
    client.headers["Authorization"] = f"Bearer {user_token}"
    run = await client.post(
        "/execution/runs",
        json={
            "customer_id": 1,
            "module": "dd",
            "title": "Ambiguous selection",
            "context": fields,
        },
    )
    job = await client.post(
        "/jobs",
        json={
            "kind": "report_generate",
            "request": {"report_id": "report", **fields},
        },
    )
    for response in (run, job):
        assert response.status_code == 422
        assert response.json()["detail"] == "workspace_required_for_document_selection"


async def test_generic_context_without_selection_fields_keeps_company_default(client, user_token):
    client.headers["Authorization"] = f"Bearer {user_token}"
    response = await client.post(
        "/execution/runs",
        json={
            "customer_id": 1,
            "module": "dd",
            "title": "Company research",
            "context": {"case_id": "company-case"},
        },
    )
    assert response.status_code == 201
    assert response.json()["context"] == {"case_id": "company-case"}


async def test_ambiguous_stored_job_is_hidden_from_lists_and_events(client_db, user_token):
    from app.services.workspace_ws_scope import workspace_event_authorizer

    client, factory = client_db
    client.headers["Authorization"] = f"Bearer {user_token}"
    async with factory.begin() as session:
        session.add(
            Job(
                id="ambiguous-selection",
                customer_id=1,
                kind="report_generate",
                status="succeeded",
                request={"document_manifest": [], "owner_user_id": USER_USER_ID},
            )
        )
    response = await client.get("/jobs")
    assert response.status_code == 200
    assert response.json() == []
    assert not await workspace_event_authorizer(factory, USER_USER_ID)(
        {"job": {"id": "ambiguous-selection"}}
    )
    assert (await client.post("/jobs/archive-finished")).json() == []
    async with factory() as session:
        assert (await session.get(Job, "ambiguous-selection")).archived_at is None
