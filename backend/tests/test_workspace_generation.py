from uuid import uuid4
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from app.database.models import Job, Kund, UserAccount
from app.database.workspaces import Workspace, WorkspaceChat
from app.database.workspace_models import VoiceWorkspace, WorkspaceArtifact, WorkspaceArtifactRevision, WorkspaceOperation
from app.llm import set_structured_completer
from app.services import jobs
from app.services.workspace_export import export_revision_docx
from app.services.workspace_generation import GeneratedDocument, GeneratedRelations, _validate_generated_content, _validate_selected_revision


def document(text="Förvärvsanalys", refs=None):
    return {"blocks": [{"id": "intro", "type": "paragraph", "text": text, "source_refs": refs or []}]}


async def queue_document(client):
    workspace = (await client.post("/voice-workspaces?customer_id=1", json={"title": "Förvärv", "module": "dd", "idempotency_key": str(uuid4())})).json()
    result = await client.post(f"/voice-workspaces/{workspace['id']}/tools/create_document", json={
        "idempotency_key": "draft-one", "arguments": {"title": "Utkast", "instructions": "Skriv ett öppet utkast"},
    })
    assert result.status_code == 200, result.text
    return workspace, result.json()


@pytest.mark.asyncio
async def test_persisted_generation_publishes_revision_and_replays_job(client_db):
    client, factory = client_db
    scheduled = []
    jobs.set_schedule_hook(scheduled.append)
    try:
        workspace, result = await queue_document(client)
        assert result["status"] == "queued"
        async with factory() as session:
            assert (await session.get(WorkspaceArtifact, result["artifact_id"])).revision == 0
        replay = await client.post(f"/voice-workspaces/{workspace['id']}/tools/create_document", json={
            "idempotency_key": "draft-one", "arguments": {"title": "Utkast", "instructions": "Skriv ett öppet utkast"},
        })
        assert replay.json()["job_id"] == result["job_id"]

        async def complete(_messages, model):
            assert model is GeneratedDocument
            return model.model_validate(document())

        set_structured_completer(complete)
        await jobs._run_job(result["job_id"])
        async with factory() as session:
            job = await session.get(Job, result["job_id"])
            artifact = await session.get(WorkspaceArtifact, result["artifact_id"])
            operation = await session.get(WorkspaceOperation, result["operation_id"])
            assert job.status == "succeeded"
            assert artifact.status == "ready" and artifact.revision == 1
            assert operation.status == "completed"
            snapshot = await session.get(WorkspaceArtifactRevision, (artifact.id, 1))
            assert snapshot.content == document()
            assert len(list((await session.execute(select(WorkspaceArtifact))).scalars())) == 1
        exported = await client.get(f"/voice-workspaces/{workspace['id']}/artifacts/{result['artifact_id']}/exports/docx?revision=1")
        assert exported.status_code == 200
        assert exported.headers["X-Artifact-Revision"] == "1"
        assert b"document.xml" in exported.content
    finally:
        jobs.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_invalid_source_reference_fails_job_without_publishing(client_db):
    client, factory = client_db
    jobs.set_schedule_hook(lambda _job_id: None)
    try:
        _, result = await queue_document(client)

        async def complete(_messages, model):
            return model.model_validate(document(refs=["invented-reference"]))

        set_structured_completer(complete)
        await jobs._run_job(result["job_id"])
        async with factory() as session:
            job = await session.get(Job, result["job_id"])
            artifact = await session.get(WorkspaceArtifact, result["artifact_id"])
            assert job.status == "failed"
            assert artifact.status == "failed" and artifact.revision == 0
            assert await session.get(WorkspaceArtifactRevision, (artifact.id, 1)) is None
    finally:
        jobs.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_restart_marks_queued_artifact_and_operation_failed(client_db):
    client, factory = client_db
    jobs.set_schedule_hook(lambda _job_id: None)
    try:
        _, result = await queue_document(client)
        async with factory() as session:
            assert await jobs.fail_interrupted_jobs(session) == 1
            assert (await session.get(WorkspaceArtifact, result["artifact_id"])).status == "failed"
            assert (await session.get(WorkspaceOperation, result["operation_id"])).status == "failed"
    finally:
        jobs.set_schedule_hook(None)


def test_selected_block_revision_preserves_other_blocks():
    original = {"blocks": document()["blocks"] + [{"id": "end", "type": "paragraph", "text": "Oförändrat", "source_refs": []}]}
    edited = {"blocks": document("Ny inledning")["blocks"] + original["blocks"][1:]}
    arguments = {"base_content": original, "block_id": "intro"}
    _validate_selected_revision(edited, arguments)
    with pytest.raises(ValueError, match="unselected"):
        _validate_selected_revision({"blocks": edited["blocks"][:1] + [{**original["blocks"][1], "text": "Ändrat"}]}, arguments)


@pytest.mark.asyncio
async def test_relations_publish_interpretations_but_reject_unsupported_facts(client_db):
    from fastapi import HTTPException
    from app.services.workspace.service import publish_artifact_revision

    client, factory = client_db
    workspace = (await client.post("/voice-workspaces?customer_id=1", json={"title": "Relations", "idempotency_key": str(uuid4())})).json()
    content = GeneratedRelations.model_validate({
        "nodes": [{"id": "hypothesis", "label": "Möjlig risk", "kind": "interpretation", "source_refs": []},
                  {"id": "consequence", "label": "Möjlig konsekvens", "kind": "interpretation", "source_refs": []}],
        "edges": [{"id": "link", "source": "hypothesis", "target": "consequence", "label": "Bedömning",
                   "interpretation": True, "source_refs": []}],
    }).model_dump()
    _validate_generated_content("relations", content, [])
    async with factory() as session:
        artifact = WorkspaceArtifact(id=str(uuid4()), workspace_id=workspace["id"], kind="relations", title="Bedömning", status="queued", revision=0, content={})
        session.add(artifact)
        await session.flush()
        await publish_artifact_revision(session, artifact, expected_revision=0, content=content)
        await session.commit()
        assert artifact.revision == 1 and artifact.content == content
        for unsupported in (
            {**content, "nodes": [{**content["nodes"][0], "kind": "effect"}, content["nodes"][1]]},
            {**content, "edges": [{**content["edges"][0], "interpretation": False}]},
        ):
            with pytest.raises(ValueError, match="require evidence"):
                _validate_generated_content("relations", unsupported, [])
            with pytest.raises(HTTPException) as error:
                await publish_artifact_revision(session, artifact, expected_revision=1, content=unsupported)
            assert error.value.status_code == 422
        assert artifact.revision == 1


def test_docx_preserves_unicode_and_escapes_document_text():
    revision = WorkspaceArtifactRevision(artifact_id="a", revision=7, title="Åäö & <risk>", content=document("Ägarkontroll & <villkor>"))
    with ZipFile(BytesIO(export_revision_docx(revision, []))) as package:
        root = ET.fromstring(package.read("word/document.xml"))
        text = " ".join(root.itertext())
    assert "Åäö & <risk>" in text
    assert "Ägarkontroll & <villkor>" in text


@pytest.mark.asyncio
async def test_generation_releases_single_connection_while_llm_pending(client_db, tmp_path, monkeypatch):
    import asyncio
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.database.base import Base
    from app.services import workspace_generation as generation

    client, source_factory = client_db
    jobs.set_schedule_hook(lambda _job_id: None)
    try:
        workspace, result = await queue_document(client)
    finally:
        jobs.set_schedule_hook(None)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/generation.db", pool_size=1, max_overflow=0, pool_timeout=0.3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with source_factory() as source:
        job = await source.get(Job, result["job_id"])
        pairs = [(Kund, 1), (Workspace, workspace["workspace_id"]), (WorkspaceChat, workspace["chat_id"]), (VoiceWorkspace, workspace["id"]), (Job, job.id), (UserAccount, job.request["owner_user_id"]),
                 (WorkspaceArtifact, result["artifact_id"]), (WorkspaceOperation, result["operation_id"])]
        copies = []
        for model, key in pairs:
            row = await source.get(model, key)
            copies.append(model(**{column.name: getattr(row, column.name) for column in model.__table__.columns}))
    async with factory() as target:
        target.add_all(copies)
        await target.commit()
    waiting = asyncio.Event()
    release = asyncio.Event()

    async def prompts(*_args, **_kwargs):
        return {"workspace.generate.document.system": "Generate", "workspace.generate.user": "{title} {request_json} {source_context_json}"}

    async def complete(*_args, **_kwargs):
        waiting.set()
        await release.wait()
        return GeneratedDocument.model_validate(document())

    monkeypatch.setattr(generation, "require_active_prompts", prompts)
    monkeypatch.setattr(generation, "complete_structured_retry", complete)
    task = asyncio.create_task(generation.run_workspace_generation_job(factory, job_id=job.id))
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        async with factory() as reader:
            assert await reader.get(VoiceWorkspace, workspace["id"]) is not None
    finally:
        release.set()
        await task
        await engine.dispose()


def test_document_generation_prompt_uses_conversation_as_basis():
    from app.services.prompt_catalog import PROMPT_FIELDS
    field = next(row for row in PROMPT_FIELDS if row["key"] == "workspace.generate.document.system")
    assert "conversation_brief" in field["defaults"]["sv"]
    assert "metadokument" in field["defaults"]["sv"]
    assert "Use only supplied evidence snapshots for facts" not in field["defaults"]["en"]


@pytest.mark.asyncio
async def test_create_document_stores_recent_conversation(client_db):
    from app.database.models import Persona, PersonaMessage

    client, factory = client_db
    jobs.set_schedule_hook(lambda _job_id: None)
    try:
        workspace = (await client.post(
            "/voice-workspaces?customer_id=1",
            json={"title": "Koncern", "module": "dd", "idempotency_key": str(uuid4())},
        )).json()
        expert_id = str(uuid4())
        async with factory() as session:
            session.add(Persona(
                id=expert_id, customer_id=1, kind="expert", name="Klas", occ="Revisor", district="Linköping",
            ))
            session.add(PersonaMessage(
                persona_id=expert_id, mode="character", role="user", content="Crowd Collective Linköping",
            ))
            session.add(PersonaMessage(
                persona_id=expert_id, mode="character", role="assistant",
                content="45,7 MSEK omsättning, 27 anställda",
            ))
            canvas = await session.get(VoiceWorkspace, workspace["id"])
            canvas.state = {**canvas.state, "expert_id": expert_id}
            await session.commit()
        result = await client.post(
            f"/voice-workspaces/{workspace['id']}/tools/create_document",
            json={"idempotency_key": "crowd-draft", "arguments": {"title": "Koncern", "instructions": "Helhetsbild"}},
        )
        assert result.status_code == 200, result.text
        async with factory() as session:
            job = await session.get(Job, result.json()["job_id"])
            assert job.request["arguments"]["conversation_brief"] == [
                {"role": "user", "content": "Crowd Collective Linköping"},
                {"role": "assistant", "content": "45,7 MSEK omsättning, 27 anställda"},
            ]
    finally:
        jobs.set_schedule_hook(None)
