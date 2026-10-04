"""Native general turns cannot read or generate from customer-private sources."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Job, Kund, StoredObject, UserAccount
from app.database.workspace_models import (
    VoiceWorkspace, WorkspaceArtifact, WorkspaceArtifactRevision, WorkspaceReference,
)
from app.services.workspace import tool_handlers
from app.services.workspace.generation_tools import source_context
from app.services.workspace.service import add_source, create_workspace, publish_artifact_revision
from app.services.workspace.sources import citation
from app.services.workspace.tools import execute_workspace_tool
from tests.test_research_graph_v2_reuse import seed_fact


def document(refs):
    return {"blocks": [{"id": "intro", "type": "paragraph", "text": "Synthetic source summary", "source_refs": refs}]}


async def graph_reference(session, workspace, scope):
    suffix = scope.replace(":", "-")
    return await citation(session, workspace, kind="graph", source_id=f"version-{suffix}", version="version-hash",
        anchor={"anchor_type": "text", "locator": "a4.2", "exact_text": "Synthetic passage", "rects": []},
        snapshot={"title": "Prop. 1994/95:17", "excerpt": "Synthetic passage", "source_url": "https://lagen.nu/prop/1994/95:17",
                  "supporting_text_unit_ids": [f"unit-{suffix}"], "visibility": "shared"})


@pytest.fixture
async def scoped_sources():
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=1, name="Synthetic customer", slug="general-source-guard", available_modules=["dd"]))
        await session.flush()
        user = UserAccount(id="general-reader", email="general-reader@example.test", role="user", kund_id=1)
        session.add(user)
        await session.flush()
        workspace = await create_workspace(session, user, title="Synthetic canvas", module="dd")
        other = await create_workspace(session, user, title="Other synthetic canvas", module="dd")
        await seed_fact(session, scope="shared")
        await seed_fact(session, scope="customer:1")
        shared = await graph_reference(session, workspace, "shared")
        private = await graph_reference(session, workspace, "customer:1")
        foreign = await graph_reference(session, other, "shared")
        source = StoredObject(id="private-file", workspace_id=workspace.workspace_id, customer_id=1, owner_user_id=user.id,
            module="dd", kind="underlag", bucket="synthetic", object_key="private.txt", filename="private.txt",
            content_type="text/plain", size_bytes=15, extraction_status="ok", extracted_text="Synthetic private policy",
            knowledge_status="ready")
        session.add(source)
        await session.flush()
        await add_source(session, workspace, source.id)
        underlag = (await source_context(session, workspace, [], [source.id]))[0]["reference_id"]
        evidence = await citation(session, workspace, kind="evidence", source_id="synthetic-evidence", version="evidence-hash",
            anchor={}, snapshot={"excerpt": "Synthetic research evidence", "visibility": "shared"})
        artifact = WorkspaceArtifact(id="private-artifact", workspace_id=workspace.id, kind="document", title="Synthetic draft",
            status="queued", revision=0, content={})
        session.add(artifact)
        await session.flush()
        await publish_artifact_revision(session, artifact, expected_revision=0, content=document([underlag]))
        shared_artifact = WorkspaceArtifact(id="shared-artifact", workspace_id=workspace.id, kind="document", title="Public draft",
            status="queued", revision=0, content={})
        session.add(shared_artifact)
        await session.flush()
        await publish_artifact_revision(session, shared_artifact, expected_revision=0, content=document([shared.id]))
        workspace.state = {**workspace.state, "knowledge_scope": "general"}
        ids = {"workspace": workspace.id, "user": user.id, "source": source.id, "underlag": underlag,
               "private_graph": private.id, "shared": shared.id, "foreign": foreign.id, "evidence": evidence.id}
        await session.commit()
    yield factory, ids
    await engine.dispose()


async def invoke(session, ids, name, args, *, turn_scope=None):
    user = await session.get(UserAccount, ids["user"])
    agent = None
    if turn_scope:
        workspace = await session.get(VoiceWorkspace, ids["workspace"])
        agent = SimpleNamespace(workspace_id=workspace.id, user_id=user.id, customer_id=1, status="active",
            expires_at=datetime.now(UTC) + timedelta(minutes=5), expert_id=None,
            turn_state={**workspace.state, "knowledge_scope": turn_scope}, turn_revision=workspace.revision)
    return await execute_workspace_tool(session, workspace_id=ids["workspace"], user=user, tool_name=name, arguments=args,
        idempotency_key=str(uuid4()), agent_session=agent)


async def durable_basis(session, ids):
    workspace = await session.get(VoiceWorkspace, ids["workspace"])
    return {
        "state": workspace.state, "revision": workspace.revision, "reference_number": workspace.next_reference_number,
        "jobs": await session.scalar(select(func.count()).select_from(Job)),
        "artifacts": await session.scalar(select(func.count()).select_from(WorkspaceArtifact)),
        "revisions": await session.scalar(select(func.count()).select_from(WorkspaceArtifactRevision)),
        "references": await session.scalar(select(func.count()).select_from(WorkspaceReference)),
    }


async def assert_blocked(fixture, name, args, *, turn_scope=None, detail="private_document_requires_workspace", status=409):
    factory, ids = fixture
    async with factory() as session:
        before = await durable_basis(session, ids)
        with pytest.raises(HTTPException) as caught:
            await invoke(session, ids, name, args, turn_scope=turn_scope)
        assert (caught.value.status_code, caught.value.detail) == (status, detail)
        assert await durable_basis(session, ids) == before
        await session.rollback()


@pytest.mark.parametrize("kind", ["source", "underlag", "private_graph", "evidence"])
async def test_general_read_rejects_private_sources_despite_shared_snapshot_label(scoped_sources, kind):
    _, ids = scoped_sources
    args = {"source_id" if kind == "source" else "reference_id": ids[kind]}
    await assert_blocked(scoped_sources, "read_source", args)


async def test_general_read_preserves_shared_original_reference(scoped_sources):
    factory, ids = scoped_sources
    async with factory() as session:
        result = await invoke(session, ids, "read_source", {"reference_id": ids["shared"]})
        assert result["reference_id"] == ids["shared"]
        assert result["source_id"] == "version-shared"
        assert result["anchor"]["locator"] == "a4.2"
        assert result["snapshot"]["source_url"] == "https://lagen.nu/prop/1994/95:17"
        assert result["source_version"] == "version-hash" and not result["stale"]


@pytest.mark.parametrize("name", ["read_source", "create_document"])
async def test_general_reference_guard_preserves_other_canvas_404(scoped_sources, name):
    _, ids = scoped_sources
    args = {"reference_id": ids["foreign"]} if name == "read_source" else {"source_refs": [ids["foreign"]]}
    await assert_blocked(scoped_sources, name, args, status=404, detail="workspace_reference_not_found")


@pytest.mark.parametrize("kind", ["source", "underlag", "private_graph"])
@pytest.mark.parametrize("scope", ["workspace", "research"])
async def test_other_scopes_keep_private_reads(scoped_sources, kind, scope):
    factory, ids = scoped_sources
    async with factory() as session:
        args = {"source_id" if kind == "source" else "reference_id": ids[kind]}
        result = await invoke(session, ids, "read_source", args, turn_scope=scope)
        assert result["status"] == "completed"
        assert result["source_id"] == ("version-customer-1" if kind == "private_graph" else ids["source"])
        if kind == "source":
            assert result["text"] == "Synthetic private policy"


@pytest.mark.parametrize("name", ["create_document", "compare_sources", "get_relations"])
@pytest.mark.parametrize("kind", ["source", "underlag", "private_graph", "evidence"])
async def test_general_generation_rejects_private_inputs_before_writes(scoped_sources, name, kind):
    _, ids = scoped_sources
    args = {"source_ids" if kind == "source" else "source_refs": [ids[kind]], "instructions": "Synthetic summary"}
    await assert_blocked(scoped_sources, name, args)


@pytest.mark.parametrize("direct", [False, True])
async def test_general_revision_rejects_private_base_references_before_writes(scoped_sources, direct):
    args = {"artifact_id": "private-artifact", "expected_revision": 1, "instructions": "Synthetic change"}
    if direct:
        args["content"] = document([])
    await assert_blocked(scoped_sources, "revise_document", args)


async def test_general_direct_revision_rejects_new_private_reference(scoped_sources):
    _, ids = scoped_sources
    args = {"artifact_id": "shared-artifact", "expected_revision": 1, "content": document([ids["underlag"]])}
    await assert_blocked(scoped_sources, "revise_document", args)


async def test_general_chart_rejects_private_references_before_writes(scoped_sources):
    _, ids = scoped_sources
    args = {"title": "Synthetic chart", "chart_type": "stat_number", "series": [{"label": "Amount", "value": 1}],
            "source_refs": [ids["underlag"]]}
    await assert_blocked(scoped_sources, "render_chart", args)


@pytest.mark.parametrize("name", ["read_source", "create_document", "revise_document", "render_chart"])
async def test_scope_guard_uses_frozen_general_turn_after_ui_scope_changes(scoped_sources, name):
    factory, ids = scoped_sources
    async with factory() as session:
        workspace = await session.get(VoiceWorkspace, ids["workspace"])
        workspace.state = {**workspace.state, "knowledge_scope": "workspace"}
        await session.commit()
    args = {
        "read_source": {"source_id": ids["source"]},
        "create_document": {"source_ids": [ids["source"]]},
        "revise_document": {"artifact_id": "private-artifact", "expected_revision": 1, "instructions": "Synthetic change"},
        "render_chart": {"title": "Synthetic chart", "chart_type": "stat_number", "series": [{"label": "Amount", "value": 1}],
                         "source_refs": [ids["underlag"]]},
    }[name]
    await assert_blocked(scoped_sources, name, args, turn_scope="general")


@pytest.mark.parametrize("name", ["create_document", "compare_sources", "get_relations"])
async def test_general_generation_keeps_shared_source_context(scoped_sources, monkeypatch, name):
    factory, ids = scoped_sources
    captured = []
    async def generate(*_args, **kwargs):
        captured.append(kwargs["arguments"]["source_context"])
        return {"status": "completed"}
    monkeypatch.setattr(tool_handlers, "queue_generation", generate)
    async with factory() as session:
        result = await invoke(session, ids, name, {"source_refs": [ids["shared"]]})
        assert result["status"] == "completed"
    assert captured[0][0]["source_id"] == "version-shared"
    assert captured[0][0]["reference_id"] == ids["shared"]


@pytest.mark.parametrize("name", ["read_source", "create_document", "revise_document"])
async def test_general_shared_reference_still_checks_canonical_passages(scoped_sources, name):
    factory, ids = scoped_sources
    async with factory() as session:
        ref = await session.get(WorkspaceReference, ids["shared"])
        ref.snapshot = {**ref.snapshot, "supporting_text_unit_ids": ["unit-customer-1"]}
        await session.commit()
    args = {
        "read_source": {"reference_id": ids["shared"]},
        "create_document": {"source_refs": [ids["shared"]]},
        "revise_document": {"artifact_id": "shared-artifact", "expected_revision": 1, "content": document([ids["shared"]])},
    }[name]
    await assert_blocked(scoped_sources, name, args, detail="workspace_graph_grounding_invalid")
