"""Workspace tools and the current selection for expert text chat."""

import json

from app.schemas.workspace import WorkspaceState
from app.services.prompt_catalog import render_prompt
from app.services.workspace_agent_deployment import (
    CLIENT_TOOLS,
    SERVER_TOOLS,
    argument_schema,
)

TURN_PROMPT_KEY = "workspace.chat.turn"
CLIENT_TOOL_NAMES = frozenset(CLIENT_TOOLS)
SERVER_TOOL_NAMES = frozenset(SERVER_TOOLS)


def workspace_turn_text(prompts: dict[str, str], state: WorkspaceState) -> str:
    selection = None if state.selection is None else state.selection.model_dump()
    payload = {
        "knowledge_scope": state.knowledge_scope,
        "view": state.view,
        "active_artifact_id": state.active_artifact_id,
        "documents": [row.model_dump() for row in state.documents],
        "selection": selection,
    }
    return render_prompt(
        prompts,
        TURN_PROMPT_KEY,
        workspace_json=json.dumps(payload, ensure_ascii=False),
    )


def workspace_openai_tools(
    prompts: dict[str, str],
    *,
    skip: frozenset[str] = frozenset(),
) -> list[dict]:
    specs = []
    for name in (*SERVER_TOOLS, *CLIENT_TOOLS):
        if name in skip:
            continue
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": render_prompt(prompts, f"workspace.voice.tool.{name}"),
                    "parameters": argument_schema(name),
                },
            }
        )
    return specs
