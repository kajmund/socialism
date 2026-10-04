"""One authorized, idempotent server-tool path for UI and live voice calls."""
from datetime import UTC, datetime
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import UserAccount
from app.schemas.workspace import WorkspaceState
from app.services.workspace.service import accept_operation, require_workspace
from app.services.workspace.tool_handlers import HANDLERS, ToolContext


def _validate_agent(workspace, user, agent_session) -> None:
    if agent_session is not None:
        expires = agent_session.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if (agent_session.workspace_id != workspace.id or agent_session.user_id != user.id
                or agent_session.customer_id != workspace.customer_id or agent_session.status != "active"
                or expires <= datetime.now(UTC) or workspace.state.get("expert_id") != agent_session.expert_id):
            raise HTTPException(status_code=403, detail="workspace_agent_session_revoked")

async def execute_workspace_tool(session: AsyncSession, *, workspace_id: str, user: UserAccount,
                                 tool_name: str, arguments: dict, idempotency_key: str,
                                 agent_session=None) -> dict:
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("VoiceWorkspace commands require their own clean transaction")
    workspace = await require_workspace(session, workspace_id, user)
    _validate_agent(workspace, user, agent_session)
    turn_state = getattr(agent_session, "turn_state", None) if agent_session is not None else None
    turn_context = None if turn_state is None else {
        "revision": getattr(agent_session, "turn_revision", workspace.revision),
        "state": WorkspaceState.model_validate(turn_state).model_dump(),
    }
    operation, accepted = await accept_operation(session, workspace, tool_name=tool_name, arguments=arguments,
        idempotency_key=idempotency_key, context_snapshot=turn_context)
    if not accepted:
        return operation.result or {"operation_id": operation.id, "status": operation.status}
    if agent_session is not None:
        if tool_name == "start_research":
            from app.services.expert_chat_research_tool import _assistant_offered_research, _explicit_research_confirmation
            if not (_explicit_research_confirmation(getattr(agent_session, "turn_user_text", ""))
                    and _assistant_offered_research(getattr(agent_session, "turn_previous_agent_text", ""))):
                raise HTTPException(status_code=409, detail="research_confirmation_required")
    completed = False
    try:
        handler = HANDLERS.get(tool_name)
        if handler is None:
            raise HTTPException(status_code=404, detail="workspace_tool_not_found")
        state = WorkspaceState.model_validate(operation.context_snapshot["state"])
        context = ToolContext(session, workspace, user, operation, state, state.language)
        result = await handler(context, arguments)
        completed = True
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_input=False)) from exc
    finally:
        if not completed and getattr(operation, "external_started", False):
            operation_id = operation.id
            await session.rollback()
            from app.database.workspace_models import WorkspaceOperation
            persisted = await session.get(WorkspaceOperation, operation_id)
            if persisted is not None:
                persisted.status = "failed"
                persisted.result = {"operation_id": operation_id, "status": "failed", "error": "workspace_external_operation_failed"}
                await session.commit()
    operation.status = "queued" if result.get("status") == "queued" else "completed"
    operation.result = {**result, "operation_id": operation.id}
    operation.job_id = result.get("job_id")
    await session.flush()
    return operation.result
