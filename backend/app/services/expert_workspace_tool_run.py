"""Run one workspace tool without holding a caller transaction around I/O."""

from __future__ import annotations

import json

from fastapi import HTTPException

from app.database.models import UserAccount
from app.schemas.workspace import WorkspaceState
from app.services.jobs import enqueue_job, job_session_factory
from app.services.speculative_results import speculative_result_for
from app.services.workspace_intent import (
    IntentDecision,
    apply_intent_to_find_arguments,
)


async def run_workspace_tool_call(call: object, work: object) -> str:
    cached = speculative_result_for(call.name, dict(call.arguments))
    if cached is not None:
        return cached

    from app.services.workspace.tools import _turn_state, execute_workspace_tool

    if not work.workspace_id or not work.actor_user_id or work.workspace_state is None:
        raise ValueError("workspace_required")
    arguments = dict(call.arguments)
    if call.name == "find_documents":
        intent = getattr(work, "workspace_intent", None)
        if not isinstance(intent, IntentDecision):
            intent = None
        arguments = apply_intent_to_find_arguments(arguments, intent)
    factory = job_session_factory()
    async with factory() as session:
        user = await session.get(UserAccount, work.actor_user_id)
        if user is None:
            raise ValueError("actor_not_found")
        session.expunge(user)
        await session.rollback()
        try:
            token = _turn_state.set(WorkspaceState.model_validate(work.workspace_state))
            try:
                result = await execute_workspace_tool(
                    session,
                    workspace_id=work.workspace_id,
                    user=user,
                    tool_name=call.name,
                    arguments=arguments,
                    idempotency_key=call.id,
                )
            finally:
                _turn_state.reset(token)
        except HTTPException as exc:
            await session.rollback()
            return str(exc.detail)
        await session.commit()
    if result.get("status") == "queued" and result.get("job_id"):
        enqueue_job(result["job_id"])
    text = json.dumps(result, ensure_ascii=False)
    return text if len(text) <= 12000 else text[:12000]
