"""Reuse selected expert lookups without holding the workspace transaction."""

from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona, UserAccount
from app.database.workspace_conversations import WorkspaceConversationSession
from app.services.expert_session_tools import consult_tool_spec
from app.services.expert_tools import resolve_expert_tools
from app.services.actor_profiles import ACTOR_TOOL_IDS, ActorProfileTools
from app.services.live_voice_tools import live_voice_tool_specs, run_live_voice_tool
from app.services.prompt_store import require_prompts_for_persona
from app.database.workspace_models import WorkspaceOperation
from app.services.workspace.service import accept_operation, require_expert, require_workspace

# The workspace's source-bound tools own research start and evidence lookup.
WORKSPACE_RESEARCH_TOOLS = frozenset({"start_research", "lookup_research_evidence"})


class ExpertToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    arguments: dict


def selected_expert_specs(persona: Persona) -> list[dict]:
    specs = [spec["function"] for spec in live_voice_tool_specs(persona)
             if spec["function"]["name"] not in WORKSPACE_RESEARCH_TOOLS]
    if "ask_expert" in resolve_expert_tools(persona.tools):
        specs.append(consult_tool_spec()["function"])
    return specs


def expert_tool_schema(persona: Persona) -> dict:
    specs = selected_expert_specs(persona)
    return {"type": "object", "properties": {
        "name": {"type": "string", "enum": [spec["name"] for spec in specs]},
        "arguments": {"type": "object"}}, "required": ["name", "arguments"],
        "additionalProperties": False, "oneOf": [
            {"properties": {"name": {"const": spec["name"]}, "arguments": spec["parameters"]},
             "required": ["name", "arguments"]} for spec in specs]}


async def execute_expert_tool(session: AsyncSession, *, provider: WorkspaceConversationSession,
                              user: UserAccount, arguments: dict, idempotency_key: str) -> dict:
    args = ExpertToolArguments.model_validate(arguments)
    workspace = await require_workspace(session, provider.workspace_id, user)
    persona = await require_expert(session, workspace, provider.expert_id)
    if args.name not in {spec["name"] for spec in selected_expert_specs(persona)}:
        raise HTTPException(403, "workspace_expert_tool_not_allowed")
    session_id = provider.id
    user_message = getattr(provider, "turn_user_text", "")
    previous_agent = getattr(provider, "turn_previous_agent_text", "")
    history = [("assistant", previous_agent, None)] if previous_agent else []
    prompts = await require_prompts_for_persona(session, persona) if args.name == "ask_expert" else None
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("Expert tools require a read-only input transaction")
    operation, accepted = await accept_operation(
        session, workspace, tool_name="expert_tool", arguments=arguments,
        idempotency_key=idempotency_key,
    )
    if not accepted:
        return operation.result or {"operation_id": operation.id, "status": operation.status}
    operation_id = operation.id
    # Materialize/detach only inputs needed by the established handlers.
    session.expunge(persona)
    session.expunge(user)
    await session.commit()
    result = None
    try:
        result = await _run_selected_tool(session, persona, user, args, context={
            "session_id": session_id, "user_message": user_message,
            "history": history, "prompts": prompts, "owner_id": user.id,
            "workspace_parent_id": workspace.workspace_id,
            "conversation": f"voice-workspace:{workspace.id}:expert:{persona.id}",
        })
        return {"status": "completed", "operation_id": operation_id, "tool_name": args.name, "result": result}
    finally:
        await _persist_result(session, operation_id, result, args.name)


async def _run_selected_tool(session: AsyncSession, persona: Persona, user: UserAccount,
                             args: ExpertToolArguments, *, context: dict) -> str:
    if args.name in ACTOR_TOOL_IDS:
        result = await ActorProfileTools(session, user_id=user.id, customer_id=persona.customer_id,
                                         conversation=context["conversation"])(args.name, args.arguments)
    elif args.name == "ask_expert":
        from app.services.expert_consult import expert_consult_handler_for_chat

        result = await expert_consult_handler_for_chat(
            session, asker=persona, mode="interview", prompts=context["prompts"],
            workspace_owner_id=context["owner_id"],
            workspace_parent_id=context["workspace_parent_id"],
        )(args.arguments)
    else:
        result = await run_live_voice_tool(
            session, persona=persona, user=user, session_id=context["session_id"],
            name=args.name, arguments=args.arguments, history=context["history"],
            user_message=context["user_message"],
        )
    if session.in_transaction():
        await session.commit()
    return result


async def _persist_result(session: AsyncSession, operation_id: str, result: str | None, tool_name: str) -> None:
    await session.rollback()
    operation = await session.get(WorkspaceOperation, operation_id)
    operation.status = "completed" if result is not None else "failed"
    operation.result = {"status": operation.status, "operation_id": operation_id, "tool_name": tool_name,
                        "result": result} if result is not None else {"status": "failed", "error": "expert_tool_failed", "operation_id": operation_id}
    await session.commit()
