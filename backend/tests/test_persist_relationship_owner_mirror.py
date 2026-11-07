"""Regression: transitional relationship mirror must not run when Owner writes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.knowledge.persist import persist_extracted_knowledge
from app.services.knowledge.relationships import ABOUT, knowledge_relationship


@pytest.mark.asyncio
async def test_transitional_relationship_mirror_skipped_when_owner_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edge = knowledge_relationship(
        customer_id=1,
        relation=ABOUT,
        from_kind="entity",
        from_id="entity-a",
        to_kind="entity",
        to_id="entity-b",
    )
    mirror_calls: list[object] = []

    async def fake_persist(session, relationship):  # noqa: ANN001
        return relationship, False

    def fake_mirror(relationship: object) -> None:
        mirror_calls.append(relationship)

    runtime = MagicMock()
    runtime.client = object()

    monkeypatch.setattr(
        "app.services.knowledge.persist.persist_knowledge_relationship_result",
        AsyncMock(side_effect=fake_persist),
    )
    monkeypatch.setattr("app.services.knowledge.persist.mirror_relationship", fake_mirror)
    monkeypatch.setattr("app.services.knowledge.persist.get_owner_runtime", lambda: runtime)

    session = MagicMock()
    await persist_extracted_knowledge(session, relationships=[edge])

    assert mirror_calls == []


@pytest.mark.asyncio
async def test_transitional_relationship_mirror_runs_without_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edge = knowledge_relationship(
        customer_id=1,
        relation=ABOUT,
        from_kind="entity",
        from_id="entity-a",
        to_kind="entity",
        to_id="entity-b",
    )
    mirror_calls: list[object] = []

    async def fake_persist(session, relationship):  # noqa: ANN001
        return relationship, False

    def fake_mirror(relationship: object) -> None:
        mirror_calls.append(relationship)

    runtime = MagicMock()
    runtime.client = None

    monkeypatch.setattr(
        "app.services.knowledge.persist.persist_knowledge_relationship_result",
        AsyncMock(side_effect=fake_persist),
    )
    monkeypatch.setattr("app.services.knowledge.persist.mirror_relationship", fake_mirror)
    monkeypatch.setattr("app.services.knowledge.persist.get_owner_runtime", lambda: runtime)

    session = MagicMock()
    await persist_extracted_knowledge(session, relationships=[edge])

    assert mirror_calls == [edge]
