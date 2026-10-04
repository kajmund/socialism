"""Materialize database prompts before publishing native tools and procedures."""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import Persona
from app.database.workspace_conversations import WorkspaceAgentDeployment
from app.services.elevenlabs_agents import ElevenLabsAgentsClient, ElevenLabsError, require_string
from app.services.prompt_store import render_prompt, require_active_prompts
from app.services.workspace.tool_arguments import (
    ChartArguments, ExportArguments, GenerationArguments, IngestArguments, JobArguments,
    ReadArguments, ResearchArguments, ReviseArguments, SearchArguments,
)

SERVER_TOOLS = (
    "get_workspace_context", "ingest_source", "get_job_status", "search_knowledge", "read_source",
    "compare_sources", "get_relations", "render_chart", "create_document", "revise_document",
    "export_document", "start_research",
)
CLIENT_TOOLS = (
    "open_ingest_picker", "show_evidence", "show_document", "focus_anchor", "show_comparison",
    "show_relations", "show_knowledge", "show_artifact",
)
PROMPT_PREFIX = "workspace.voice."
TOOL_ARGUMENT_MODELS = {
    "ingest_source": IngestArguments, "get_job_status": JobArguments, "search_knowledge": SearchArguments,
    "read_source": ReadArguments, "compare_sources": GenerationArguments, "get_relations": GenerationArguments,
    "render_chart": ChartArguments, "create_document": GenerationArguments, "revise_document": ReviseArguments,
    "export_document": ExportArguments, "start_research": ResearchArguments,
}


@dataclass(frozen=True)
class AgentSnapshot:
    identity: dict
    prompt_version: str
    prompts: dict[str, str]
    system: str
    tools: dict[str, dict]
    existing: dict | None


def argument_schema(name: str) -> dict:
    if name in TOOL_ARGUMENT_MODELS:
        return TOOL_ARGUMENT_MODELS[name].model_json_schema()
    if name in {"open_ingest_picker", "get_workspace_context"}:
        properties = {}
    elif name == "show_document":
        properties = {"reference_id": {"type": "string"}, "source_id": {"type": "string"},
                      "page": {"type": "integer", "minimum": 1}}
    elif name == "focus_anchor":
        properties = {"reference_id": {"type": "string"}}
    elif name in {"show_evidence", "show_knowledge"}:
        properties = {"reference_ids": {"type": "array", "items": {"type": "string"}}}
    elif name == "show_relations":
        properties = {"artifact_id": {"type": "string"}, "node_id": {"type": "string"}, "edge_id": {"type": "string"}}
    else:
        properties = {"artifact_id": {"type": "string"}}
    result = {"type": "object", "properties": properties, "additionalProperties": False}
    if name in {"show_artifact", "show_comparison", "show_relations"}:
        result["required"] = ["artifact_id"]
    if name == "focus_anchor":
        result["required"] = ["reference_id"]
    return result


def tool_config(name: str, description: str, argument_description: str) -> dict:
    # ElevenLabs' schema subset cannot carry our full Pydantic schemas. Keep
    # the validated local contract explicit inside the JSON argument field.
    parameters = {"type": "object", "properties": {
        "arguments_json": {"type": "string", "description": argument_description}},
        "required": ["arguments_json"]}
    return {"name": name, "description": description, "type": "client", "parameters": parameters,
            "execution_mode": "immediate", "interruption_mode": "allow", "tool_error_handling_mode": "passthrough",
            "expects_response": True, "response_timeout_secs": 60}


def procedure_configs(prompts: dict[str, str], tool_ids: dict[str, str]) -> dict[str, dict]:
    result = {"explore": {"name": "explore", "type": "free_form",
                          "trigger": render_prompt(prompts, PROMPT_PREFIX + "procedure.explore_trigger"),
                          "content": render_prompt(prompts, PROMPT_PREFIX + "procedure.explore")}}
    for name, tool in (("create", "create_document"), ("compare", "compare_sources"), ("revise", "revise_document")):
        # Tool failures and queued jobs must never lead to an unconditional
        # success announcement. These tools are terminal procedure steps.
        steps = [{"type": "tool_call", "tool_id": tool_ids[tool], "tool_name": tool,
                  "instruction": render_prompt(prompts, PROMPT_PREFIX + "procedure." + name),
                  "on_failure": {"branches": [], "fallback": [{"type": "tell", "instruction":
                      render_prompt(prompts, PROMPT_PREFIX + "procedure.failure")}]} }]
        result[name] = {"name": name, "type": "deterministic", "content": json.dumps({"steps": steps}),
                        "trigger": render_prompt(prompts, PROMPT_PREFIX + "procedure." + name + "_trigger")}
    return result


async def prepare_agent_snapshot(session: AsyncSession, *, persona: Persona, language: str, module: str) -> AgentSnapshot:
    prompts = await require_active_prompts(session, customer_id=persona.customer_id, module=module, language=language)
    tools = {name: tool_config(name, render_prompt(prompts, PROMPT_PREFIX + "tool." + name),
                              tool_argument_description(prompts, argument_schema(name)))
             for name in (*SERVER_TOOLS, *CLIENT_TOOLS)}
    from app.services.workspace_expert_tools import expert_tool_schema
    expert_schema = expert_tool_schema(persona)
    if expert_schema["properties"]["name"].get("enum"):
        config = tool_config("expert_tool", render_prompt(prompts, PROMPT_PREFIX + "tool.expert_tool"),
                             tool_argument_description(prompts, expert_schema))
        tools["expert_tool"] = config
    system = render_prompt(prompts, PROMPT_PREFIX + "system", expert_name=persona.name,
                           expert_profile=json.dumps(persona.profile, ensure_ascii=False))
    version = hashlib.sha256(json.dumps({
        "prompts": {key: value for key, value in prompts.items() if key.startswith(PROMPT_PREFIX)},
        "system": system, "tools": tools, "llm": settings.elevenlabs_llm,
        "voice_id": settings.elevenlabs_voice_id, "duration": settings.elevenlabs_session_ttl_seconds, "adapter_version": 2,
    }, sort_keys=True).encode()).hexdigest()
    identity = {"customer_id": persona.customer_id, "expert_id": persona.id, "language": language}
    row = (await session.execute(select(WorkspaceAgentDeployment).filter_by(
        **identity, prompt_version=version))).scalar_one_or_none()
    existing = deployment_values(row) if row else None
    return AgentSnapshot({**identity, "expert_name": persona.name}, version, prompts, system, tools, existing)


def tool_argument_description(prompts: dict[str, str], schema: dict) -> str:
    return render_prompt(prompts, PROMPT_PREFIX + "tool_arguments",
                         argument_schema=json.dumps(schema, ensure_ascii=False))


def deployment_values(row: WorkspaceAgentDeployment) -> dict:
    return {"agent_id": row.agent_id, "agent_version": row.agent_version,
            "tool_ids": dict(row.tool_ids), "procedure_ids": dict(row.procedure_ids)}


def agent_config(snapshot: AgentSnapshot, tool_ids: dict[str, str]) -> dict:
    return {"conversation_config": {
        "agent": {"language": snapshot.identity["language"],
                  "first_message": render_prompt(snapshot.prompts, PROMPT_PREFIX + "first_message",
                                                 expert_name=snapshot.identity["expert_name"]),
                  "prompt": {"prompt": snapshot.system, "llm": settings.elevenlabs_llm,
                             "tool_ids": list(tool_ids.values()), "backup_llm_config": {"preference": "disabled"},
                             "enable_parallel_tool_calls": False, "timezone": "Europe/Stockholm",
                             "knowledge_base": [], "rag": {"enabled": False}}},
        "tts": {"voice_id": settings.elevenlabs_voice_id},
        "conversation": {"max_duration_seconds": settings.elevenlabs_session_ttl_seconds,
                         "client_events": ["conversation_initiation_metadata", "audio", "interruption", "user_transcript",
                                           "tentative_user_transcript", "agent_response", "agent_response_correction",
                                           "agent_chat_response_part", "agent_response_complete", "client_tool_call"]}},
        "platform_settings": {"auth": {"enable_auth": True}, "queueing_config": {"enabled": False},
                              "overrides": {"conversation_config_override": {"conversation": {"text_only": True}}},
                              "privacy": {"record_voice": False}},
        "name": f"Socialism {snapshot.identity['expert_id']} {snapshot.identity['language']} {snapshot.prompt_version[:12]}"}


async def cleanup_deployment(client: ElevenLabsAgentsClient, deployment: dict) -> None:
    failed = False
    resources = [("agents", deployment["agent_id"])] if deployment.get("agent_id") else []
    resources.extend(("tools", identifier) for identifier in deployment.get("tool_ids", {}).values())
    for category, identifier in resources:
        try:
            # Deleting an agent retains branch/version tool dependencies.
            # These IDs belong only to this unused deployment, so remove them
            # explicitly from those retained dependencies as well.
            await client.request("DELETE", f"/v1/convai/{category}/{identifier}",
                                 params={"force": True} if category == "tools" else None)
        except ElevenLabsError:
            failed = True
    if failed:
        raise ElevenLabsError("elevenlabs_publish_failed_cleanup_required")


async def publish_agent_snapshot(snapshot: AgentSnapshot, client: ElevenLabsAgentsClient) -> dict:
    """External phase only: no session or ORM object may be consulted here."""
    if snapshot.existing:
        return snapshot.existing
    models = await client.request("GET", "/v1/convai/llm/list")
    model = next((item for item in models.get("llms", []) if item.get("llm") == settings.elevenlabs_llm), None)
    if not model or (model.get("deprecation_info") or {}).get("is_deprecated"):
        raise ElevenLabsError("elevenlabs_model_unavailable_or_deprecated")
    resources = {"tool_ids": {}}
    completed = False
    try:
        for name, config in snapshot.tools.items():
            created = await client.request("POST", "/v1/convai/tools", body={"tool_config": config})
            resources["tool_ids"][name] = require_string(created, "id")
        created = await client.request("POST", "/v1/convai/agents/create", body=agent_config(snapshot, resources["tool_ids"]))
        resources["agent_id"] = require_string(created, "agent_id")
        result = await publish_procedures(snapshot, client, resources)
        completed = True
        return result
    finally:
        if not completed:
            await cleanup_deployment(client, resources)


async def publish_procedures(snapshot: AgentSnapshot, client: ElevenLabsAgentsClient, resources: dict) -> dict:
    agent_id, tool_ids = resources["agent_id"], resources["tool_ids"]
    agent = await client.request("GET", f"/v1/convai/agents/{agent_id}")
    branch_id = require_string(agent, "main_branch_id")
    procedure_ids = {}
    for name, procedure in procedure_configs(snapshot.prompts, tool_ids).items():
        created = await client.request("POST", f"/v1/convai/agents/{agent_id}/branches/{branch_id}/procedures", body=procedure)
        procedure_ids[name] = require_string(created, "procedure_id")
    published = await client.request("PATCH", f"/v1/convai/agents/{agent_id}", params={"branch_id": branch_id},
                                     body={"version_description": f"database-prompt-snapshot:{snapshot.prompt_version}"})
    version = require_string(published, "version_id")
    if not set(procedure_ids.values()).issubset(published.get("procedures", {})):
        raise ElevenLabsError("elevenlabs_procedures_not_published")
    return {"agent_id": agent_id, "agent_version": version, "tool_ids": tool_ids, "procedure_ids": procedure_ids}


async def save_agent_deployment(session: AsyncSession, snapshot: AgentSnapshot, deployment: dict) -> dict:
    identity = {key: value for key, value in snapshot.identity.items() if key != "expert_name"}
    existing = (await session.execute(select(WorkspaceAgentDeployment).filter_by(
        **identity, prompt_version=snapshot.prompt_version))).scalar_one_or_none()
    if existing is None:
        try:
            async with session.begin_nested():
                session.add(WorkspaceAgentDeployment(**identity, prompt_version=snapshot.prompt_version, **deployment))
                await session.flush()
        except IntegrityError:
            existing = (await session.execute(select(WorkspaceAgentDeployment).filter_by(
                **identity, prompt_version=snapshot.prompt_version))).scalar_one()
    result = deployment_values(existing) if existing else deployment
    await session.commit()
    return result


async def deploy_agent_snapshot(session: AsyncSession, snapshot: AgentSnapshot, client: ElevenLabsAgentsClient) -> dict:
    deployment = await publish_agent_snapshot(snapshot, client)
    cached = False
    try:
        selected = await save_agent_deployment(session, snapshot, deployment)
        cached = True
    finally:
        if not cached and snapshot.existing is None:
            await session.rollback()
            await cleanup_deployment(client, deployment)
    if selected["agent_id"] != deployment["agent_id"]:
        # A concurrent publisher won the identical snapshot's unique key.
        # Remove this unused copy before minting a connection to the winner.
        await cleanup_deployment(client, deployment)
    return selected
