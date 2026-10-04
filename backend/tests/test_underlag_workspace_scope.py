"""The personal underlag routes cannot bypass a selected client workspace."""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.underlag import delete_underlag, get_underlag_file
from app.database.base import Base
from app.database.models import Kund, StoredObject, UserAccount
from app.services import jobs as jobs_service
from app.services.workspaces import ensure_company_workspace
from tests.conftest import USER_USER_ID


@pytest.fixture(autouse=True)
def hold_ingest(monkeypatch):
    monkeypatch.setattr(jobs_service, "enqueue_job", lambda _job_id: None)


async def test_personal_api_lists_only_selected_workspace_and_guards_every_object_route(
    client, user_token
):
    client.headers["Authorization"] = f"Bearer {user_token}"
    a = (await client.post("/workspaces", json={"name": "A"})).json()["id"]
    b = (await client.post("/workspaces", json={"name": "B"})).json()["id"]
    files = []
    for workspace in (None, a, b):
        params = {"module": "expertgranskning"}
        if workspace is not None:
            params["workspace_id"] = workspace
        uploaded = await client.post(
            "/underlag",
            params=params,
            files={"file": ("contract.txt", b"Confidential agreement", "text/plain")},
        )
        assert uploaded.status_code == 201, uploaded.text
        files.append(uploaded.json())
    common, client_a, client_b = files
    assert (await client.get("/underlag")).json()["files"] == [common | {"extracted_text": None}]
    for workspace, document in ((a, client_a), (b, client_b)):
        listing = await client.get("/underlag", params={"workspace_id": workspace})
        assert [row["id"] for row in listing.json()["files"]] == [document["id"]]
        assert listing.json()["folders"] == []
    url = f"/underlag/{client_a['id']}"
    item = {
        "kind": "note",
        "title": "N",
        "content": "Text",
        "anchors": [{"locator": "line:1", "exact_text": "Confidential"}],
    }
    rejected = [
        await client.get(url),
        await client.get(url, params={"workspace_id": b}),
        await client.get(f"{url}/file", params={"workspace_id": b}),
        await client.get(f"{url}/knowledge", params={"workspace_id": b}),
        await client.post(f"{url}/knowledge", params={"workspace_id": b}, json=item),
        await client.put(f"{url}/knowledge/missing", params={"workspace_id": b}, json=item),
        await client.delete(f"{url}/knowledge/missing", params={"workspace_id": b}),
        await client.patch(url, params={"workspace_id": b}, json={"folder_id": None}),
        await client.delete(url, params={"workspace_id": b}),
    ]
    assert [response.status_code for response in rejected] == [404] * len(rejected)
    allowed = await client.get(url, params={"workspace_id": a})
    assert allowed.status_code == 200 and allowed.json()["workspace_id"] == a


async def test_client_cannot_use_personal_company_folders(client, user_token):
    client.headers["Authorization"] = f"Bearer {user_token}"
    workspace = (await client.post("/workspaces", json={"name": "A"})).json()["id"]
    folder = (
        await client.post(
            "/underlag/folders", json={"name": "Company", "module": "expertgranskning"}
        )
    ).json()["id"]
    params = {"workspace_id": workspace, "module": "expertgranskning"}
    assert (await client.get("/underlag/folders", params=params)).status_code == 400
    assert (
        await client.post(
            "/underlag/folders",
            params=params,
            json={"name": "Client", "module": "expertgranskning"},
        )
    ).status_code == 400
    assert (await client.get("/underlag", params=params | {"folder_id": folder})).status_code == 400
    upload = await client.post(
        "/underlag",
        params=params | {"folder_id": folder},
        files={"file": ("contract.txt", b"Private", "text/plain")},
    )
    assert upload.status_code == 400


@pytest.mark.parametrize("operation", ["read", "delete"])
async def test_personal_file_storage_calls_release_one_connection_pool(
    tmp_path, monkeypatch, operation
):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'single-pool.db'}",
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.1,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory.begin() as session:
        session.add(Kund(id=1, name="Firm", slug="firm", available_modules=[]))
        session.add(UserAccount(id=USER_USER_ID, email="user@test.local", role="user", kund_id=1))
        await session.flush()
        common = await ensure_company_workspace(session, customer_id=1)
        session.add(
            StoredObject(
                id="object",
                customer_id=1,
                workspace_id=common.id,
                owner_user_id=USER_USER_ID,
                module="expertgranskning",
                kind="underlag",
                bucket="firm",
                object_key="contract.txt",
                filename="contract.txt",
                content_type="text/plain",
                size_bytes=5,
            )
        )
    calls = []

    async def storage_call(*_args):
        assert engine.pool.checkedout() == 0
        async with factory() as probe:
            assert (await probe.get(Kund, 1)).name == "Firm"
        calls.append(operation)
        return b"Text", "text/plain"

    monkeypatch.setattr("app.api.underlag.read_stored_bytes", storage_call)
    monkeypatch.setattr("app.services.stored_objects.delete_object", storage_call)
    try:
        async with factory() as session:
            user = await session.get(UserAccount, USER_USER_ID)
            handler = get_underlag_file if operation == "read" else delete_underlag
            result = await handler("object", workspace_id=None, session=session, user=user)
            assert result.status_code == (200 if operation == "read" else 204)
        assert calls == [operation]
        async with factory() as session:
            assert (await session.get(StoredObject, "object") is None) == (operation == "delete")
    finally:
        await engine.dispose()
