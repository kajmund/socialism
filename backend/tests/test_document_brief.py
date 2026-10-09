import pytest

from uuid import uuid4

from app.database.models import Persona, PersonaMessage
from app.services.workspace.document_brief import document_conversation_brief


@pytest.mark.asyncio
async def test_document_conversation_brief_keeps_newest_turns(client_db):
    _client, factory = client_db
    expert_id = str(uuid4())
    async with factory() as session:
        session.add(Persona(
            id=expert_id, customer_id=1, kind="expert", name="Klas", occ="Revisor", district="Linköping",
        ))
        session.add(PersonaMessage(persona_id=expert_id, mode="interview", role="user", content="äldre"))
        session.add(PersonaMessage(
            persona_id=expert_id, mode="interview", role="assistant",
            content="45,7 MSEK",
        ))
        session.add(PersonaMessage(persona_id=expert_id, mode="workspace", role="user", content="fel läge"))
        await session.commit()
        brief = await document_conversation_brief(session, expert_id)
    assert brief == [
        {"role": "user", "content": "äldre"},
        {"role": "assistant", "content": "45,7 MSEK"},
    ]


@pytest.mark.asyncio
async def test_document_conversation_brief_without_expert_is_empty(client_db):
    _client, factory = client_db
    async with factory() as session:
        assert await document_conversation_brief(session, None) == []
