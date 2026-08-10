"""REST + help-tool coverage for feedback inbox."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.schemas.domain import FeedbackItemCreate
from app.services.feedback import create_feedback_item, list_feedback_items
from app.services.feedback_tools import run_feedback_tool


@pytest.mark.asyncio
async def test_feedback_crud_via_api(client):
    created = await client.post(
        "/feedback",
        json={
            "kind": "bug",
            "title": "Chat shows raw markdown",
            "body": "**bold** is shown literally",
            "source": "admin",
        },
    )
    assert created.status_code == 201
    item = created.json()
    assert item["kind"] == "bug"
    assert item["status"] == "open"
    item_id = item["id"]

    idea = await client.post(
        "/feedback",
        json={"kind": "idea", "title": "Export CSV", "body": "From reports", "source": "admin"},
    )
    assert idea.status_code == 201

    listed = await client.get("/feedback")
    assert listed.status_code == 200
    assert len(listed.json()) >= 2

    patched = await client.patch(f"/feedback/{item_id}", json={"status": "in_progress"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "in_progress"

    archived = await client.patch(f"/feedback/{item_id}", json={"status": "archived"})
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    without_archived = await client.get("/feedback")
    assert without_archived.status_code == 200
    assert all(row["id"] != item_id for row in without_archived.json())

    with_archived = await client.get("/feedback", params={"include_archived": True})
    assert with_archived.status_code == 200
    assert any(row["id"] == item_id for row in with_archived.json())

    only_archived = await client.get("/feedback", params={"status": "archived"})
    assert only_archived.status_code == 200
    assert any(row["id"] == item_id for row in only_archived.json())


@pytest.mark.asyncio
async def test_feedback_tools_create_and_list():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        created_raw = await run_feedback_tool(
            session,
            "feedback_create",
            {
                "kind": "opinion",
                "title": "UI feels dense",
                "body": "Jobs page is hard to scan",
            },
            help_session_id="sess-1",
            view_path="/jobs",
        )
        created = json.loads(created_raw)
        assert created["ok"] is True
        assert created["item"]["title"] == "UI feels dense"
        assert created["item"]["session_id"] == "sess-1"
        assert created["item"]["view_path"] == "/jobs"
        assert created["item"]["source"] == "help"
        item_id = created["item"]["id"]

        listed = json.loads(await run_feedback_tool(session, "feedback_list", {"limit": 10}))
        assert listed["count"] == 1
        assert listed["items"][0]["title"] == "UI feels dense"

        got = json.loads(await run_feedback_tool(session, "feedback_get", {"id": item_id}))
        assert got["body"] == "Jobs page is hard to scan"

        other = await create_feedback_item(
            session,
            FeedbackItemCreate(kind="bug", title="Old bug", body="gone", source="admin"),
        )
        other.status = "archived"
        await session.commit()

        default_list = json.loads(await run_feedback_tool(session, "feedback_list", {}))
        titles = {row["title"] for row in default_list["items"]}
        assert "UI feels dense" in titles
        assert "Old bug" not in titles

        archived_list = json.loads(
            await run_feedback_tool(session, "feedback_list", {"status": "archived"})
        )
        assert any(row["title"] == "Old bug" for row in archived_list["items"])

        open_rows = await list_feedback_items(session)
        assert all(row.status != "archived" for row in open_rows)

    await engine.dispose()
