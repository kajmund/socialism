"""A comment stays attached to the passage it was written on."""

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.base import Base
from app.database.models import Kund, StoredObject, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceReference, WorkspaceSource
from app.schemas.workspace import PassageCommentPatch, PassageCommentWrite
from app.services.workspace.passage_comments import (
    create_expert_passage_comment, create_passage_comment, delete_passage_comment, passage_comment_key,
    update_passage_comment,
)
from app.services.workspace.service import add_source, create_workspace, workspace_out
from app.services.workspace.sources import citation

ANCHOR = {
    "anchor_type": "text", "page_number": 1, "locator": "page:1", "exact_text": "Säljare",
    "prefix_text": None, "suffix_text": None, "asset_id": None,
    "rects": [{"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04}],
}


def test_passage_key_matches_the_browser_form():
    assert passage_comment_key("pdf", ANCHOR) == '["pdf",1,[[100000,200000,300000,40000]]]'
    assert passage_comment_key("pdf", {**ANCHOR, "page_number": None, "rects": []}) == '["pdf",null,["","Säljare"]]'


@pytest.fixture
async def workspace_case(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/comments.db")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add(Kund(id=1, name="Customer", slug="comment-test", available_modules=["dd"]))
        await session.flush()
        user = UserAccount(id="user-one", email="erik@example.test", first_name="Erik", last_name="Fremred", role="user", kund_id=1)
        session.add(user)
        await session.flush()
        workspace = await create_workspace(session, user, title="Avtal", module="dd")
        source = StoredObject(
            id="source-one", workspace_id=workspace.workspace_id, customer_id=1, owner_user_id=user.id,
            module="dd", kind="underlag", bucket="comment-test", object_key="avtal.pdf", filename="avtal.pdf",
            content_type="application/pdf", size_bytes=4, extraction_status="ok", extracted_text="Säljare",
            knowledge_status="ready",
        )
        session.add(source)
        await session.flush()
        await add_source(session, workspace, source.id)
        await session.commit()
        ids = user.id, workspace.id, source.id
    yield factory, ids
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_comment_is_saved_on_its_passage_and_listed_with_the_workspace(workspace_case):
    factory, (user_id, workspace_id, source_id) = workspace_case
    async with factory() as session:
        user = await session.get(UserAccount, user_id)
        workspace = await session.get(VoiceWorkspace, workspace_id)
        created = await create_passage_comment(session, workspace, user, PassageCommentWrite(source_id=source_id, anchor=ANCHOR, body="  Kontrollera villkoret.  "))
        await session.commit()
    assert created["author_name"] == "Erik Fremred"
    assert created["body"] == "Kontrollera villkoret."
    assert created["passage_key"] == '["pdf",1,[[100000,200000,300000,40000]]]'.replace("pdf", source_id)
    async with factory() as session:
        user = await session.get(UserAccount, user_id)
        workspace = await session.get(VoiceWorkspace, workspace_id)
        listed = (await workspace_out(session, workspace))["comments"]
        assert [row["id"] for row in listed] == [created["id"]]
        edited = await update_passage_comment(session, workspace, user, comment_id=created["id"], body=PassageCommentPatch(body="Nytt villkor."))
        await session.commit()
    assert edited["body"] == "Nytt villkor."
    async with factory() as session:
        user = await session.get(UserAccount, user_id)
        workspace = await session.get(VoiceWorkspace, workspace_id)
        other = UserAccount(id="other", email="other@example.test", role="user", kund_id=1)
        with pytest.raises(HTTPException) as forbidden:
            await update_passage_comment(session, workspace, other, comment_id=created["id"], body=PassageCommentPatch(body="Nej."))
        assert forbidden.value.status_code == 403
        await delete_passage_comment(session, workspace, user, created["id"])
        await session.commit()
        assert (await workspace_out(session, workspace))["comments"] == []


@pytest.mark.asyncio
async def test_a_comment_requires_a_document_in_the_workspace(workspace_case):
    factory, (user_id, workspace_id, _source_id) = workspace_case
    async with factory() as session:
        user = await session.get(UserAccount, user_id)
        workspace = await session.get(VoiceWorkspace, workspace_id)
        assert await session.get(WorkspaceSource, (workspace_id, "missing")) is None
        with pytest.raises(HTTPException) as missing:
            await create_passage_comment(session, workspace, user, PassageCommentWrite(source_id="missing", anchor=ANCHOR, body="Hej"))
        assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_an_expert_comment_stays_with_the_expert(workspace_case):
    factory, (user_id, workspace_id, source_id) = workspace_case
    async with factory() as session:
        user = await session.get(UserAccount, user_id)
        workspace = await session.get(VoiceWorkspace, workspace_id)
        created = await create_expert_passage_comment(
            session, workspace, source_id=source_id, anchor=ANCHOR,
            expert_id="karin", author_name="Karin Expert", body="Otydligt villkor.",
        )
        again = await create_expert_passage_comment(
            session, workspace, source_id=source_id, anchor=ANCHOR,
            expert_id="karin", author_name="Karin Expert", body="Otydligt villkor.",
        )
        await session.commit()
    assert created["id"] == again["id"]
    assert created["author_kind"] == "expert"
    assert created["author_id"] is None
    assert created["expert_id"] == "karin"
    assert created["author_name"] == "Karin Expert"
    async with factory() as session:
        user = await session.get(UserAccount, user_id)
        workspace = await session.get(VoiceWorkspace, workspace_id)
        with pytest.raises(HTTPException) as forbidden:
            await update_passage_comment(session, workspace, user, comment_id=created["id"], body=PassageCommentPatch(body="Ändrat."))
        assert forbidden.value.status_code == 403
        await delete_passage_comment(session, workspace, user, created["id"])
        await session.commit()
        assert (await workspace_out(session, workspace))["comments"] == []


@pytest.mark.asyncio
async def test_deleting_a_comment_removes_that_authors_mark(workspace_case):
    factory, (user_id, workspace_id, source_id) = workspace_case
    async with factory() as session:
        user = await session.get(UserAccount, user_id)
        workspace = await session.get(VoiceWorkspace, workspace_id)
        karin = await citation(session, workspace, kind="underlag", source_id=source_id, version="v1", anchor=ANCHOR, snapshot={
            "title": "avtal.pdf", "excerpt": "Säljare", "marked_by": {"kind": "expert", "id": "karin", "name": "Karin Expert"},
        })
        alfons = await citation(session, workspace, kind="underlag", source_id=source_id, version="v1", anchor=ANCHOR, snapshot={
            "title": "avtal.pdf", "excerpt": "Säljare", "marked_by": {"kind": "expert", "id": "alfons", "name": "Alfons Expert"},
        })
        first = await create_expert_passage_comment(
            session, workspace, source_id=source_id, anchor=ANCHOR, expert_id="karin", author_name="Karin Expert", body="Första.",
        )
        await create_expert_passage_comment(
            session, workspace, source_id=source_id, anchor=ANCHOR, expert_id="karin", author_name="Karin Expert", body="Andra.",
        )
        await create_expert_passage_comment(
            session, workspace, source_id=source_id, anchor=ANCHOR, expert_id="alfons", author_name="Alfons Expert", body="Alfons.",
        )
        await session.commit()
        kept = await delete_passage_comment(session, workspace, user, first["id"])
        await session.commit()
        assert kept == []
        assert await session.get(WorkspaceReference, karin.id) is not None
        remaining = (await workspace_out(session, workspace))["comments"]
        karin_left = next(row for row in remaining if row["body"] == "Andra.")
        removed = await delete_passage_comment(session, workspace, user, karin_left["id"])
        await session.commit()
        assert removed == [karin.id]
        assert await session.get(WorkspaceReference, karin.id) is None
        assert await session.get(WorkspaceReference, alfons.id) is not None
