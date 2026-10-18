"""Created document/relations artifacts read back through workspace references."""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceArtifact
from app.services.workspace.service import create_workspace
from app.services.workspace.sources import citation, read_reference

_ANCHOR = {
    "anchor_type": "text",
    "page_number": None,
    "locator": "document",
    "exact_text": "hyra",
    "rects": [],
}


@pytest.fixture
async def artifact_workspace(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/workspace.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=1, name="Customer", slug="artifact-test", available_modules=["dd"]))
        user = UserAccount(id="user-one", email="user@example.test", role="user", kund_id=1)
        session.add(user)
        await session.flush()
        workspace = await create_workspace(session, user, title="Avtal", module="dd")
        ids = user.id, workspace.id
        await session.commit()
    yield factory, ids
    await engine.dispose()


async def _artifact_reference(factory, ids, *, kind: str, revision: int):
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        artifact = WorkspaceArtifact(
            id=f"artifact-{kind}",
            workspace_id=workspace.id,
            kind=kind,
            title="Sammanfattning",
            status="ready",
            revision=revision,
            content={"blocks": [{"text": "Hyran höjs med tre procent."}]},
        )
        session.add(artifact)
        await session.flush()
        ref = await citation(
            session,
            workspace,
            kind=kind,
            source_id=artifact.id,
            version=str(revision),
            anchor=_ANCHOR,
            snapshot={"title": artifact.title, "excerpt": "Hyran höjs.", "kind": "exact_text"},
        )
        await session.commit()
        return ref.id


@pytest.mark.asyncio
async def test_document_artifact_reference_reads_back(artifact_workspace):
    factory, ids = artifact_workspace
    reference_id = await _artifact_reference(factory, ids, kind="document", revision=2)
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        result = await read_reference(session, workspace, reference_id)
        assert result["source_kind"] == "document"
        assert result["stale"] is False


@pytest.mark.asyncio
async def test_relations_artifact_reference_reads_back(artifact_workspace):
    factory, ids = artifact_workspace
    reference_id = await _artifact_reference(factory, ids, kind="relations", revision=1)
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        result = await read_reference(session, workspace, reference_id)
        assert result["source_kind"] == "relations"
        assert result["stale"] is False


@pytest.mark.asyncio
async def test_artifact_reference_turns_stale_after_revision(artifact_workspace):
    factory, ids = artifact_workspace
    reference_id = await _artifact_reference(factory, ids, kind="document", revision=2)
    async with factory() as session:
        artifact = await session.get(WorkspaceArtifact, "artifact-document")
        artifact.revision = 3
        await session.commit()
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        result = await read_reference(session, workspace, reference_id)
        assert result["stale"] is True


@pytest.mark.asyncio
async def test_artifact_reference_rejects_kind_mismatch(artifact_workspace):
    factory, ids = artifact_workspace
    reference_id = await _artifact_reference(factory, ids, kind="document", revision=2)
    async with factory() as session:
        artifact = await session.get(WorkspaceArtifact, "artifact-document")
        artifact.kind = "relations"
        await session.commit()
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        with pytest.raises(HTTPException) as error:
            await read_reference(session, workspace, reference_id)
        assert error.value.status_code == 404
        assert error.value.detail == "workspace_reference_not_found"


@pytest.mark.asyncio
async def test_artifact_reference_rejects_missing_artifact(artifact_workspace):
    factory, ids = artifact_workspace
    reference_id = await _artifact_reference(factory, ids, kind="document", revision=2)
    async with factory() as session:
        artifact = await session.get(WorkspaceArtifact, "artifact-document")
        await session.delete(artifact)
        await session.commit()
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids[1])
        with pytest.raises(HTTPException) as error:
            await read_reference(session, workspace, reference_id)
        assert error.value.status_code == 404
        assert error.value.detail == "workspace_artifact_not_found"
