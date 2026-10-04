"""Native tool serialization guidance is rendered from active database prompts."""

import json

import pytest
from sqlalchemy import select

from app.database.models import Persona, PromptField, PromptOverride
from app.services.workspace_agent_deployment import prepare_agent_snapshot, tool_argument_description


async def test_active_database_transport_prompt_applies_to_native_and_expert_tools(client_db):
    _client, factory = client_db
    async with factory() as session:
        persona = await session.scalar(select(Persona).where(
            Persona.customer_id == 1, Persona.kind == "expert").limit(1))
        persona.tools = ["search_duckduckgo"]
        field_id = await session.scalar(select(PromptField.id).where(
            PromptField.key == "workspace.voice.tool_arguments"))
        session.add(PromptOverride(customer_id=1, prompt_field_id=field_id, language="sv",
                                   text="Active transport instruction:\n{argument_schema}"))
        await session.commit()
        snapshot = await prepare_agent_snapshot(session, persona=persona, language="sv", module="dd")
    assert "expert_tool" in snapshot.tools
    for config in snapshot.tools.values():
        parameters = config["parameters"]
        assert parameters["required"] == ["arguments_json"]
        assert set(parameters["properties"]) == {"arguments_json"}
        argument = parameters["properties"]["arguments_json"]
        assert argument["type"] == "string"
        assert argument["description"].startswith("Active transport instruction:\n")
        schema = json.loads(argument["description"].split("\n", 1)[1])
        assert schema["type"] == "object"
        if config["name"] == "expert_tool":
            assert "search_duckduckgo" in schema["properties"]["name"]["enum"]
        if config["name"] == "focus_anchor":
            assert schema["required"] == ["reference_id"]
            assert set(schema["properties"]) == {"reference_id"}


def test_native_transport_rejects_missing_database_prompt():
    with pytest.raises(RuntimeError, match="workspace.voice.tool_arguments"):
        tool_argument_description({}, {"type": "object", "properties": {}})
