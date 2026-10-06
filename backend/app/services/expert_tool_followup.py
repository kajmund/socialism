"""Weave a tool result into the expert's next line, and open a requested document."""

import json
import logging

from app.database.models import Persona, PersonaMessage
from app.services.dd.company_mcp import visible_assistant_text
from app.llm import complete_text, complete_with_tools
from app.llm.tool_messages import assistant_message_dict
from app.realtime.library_chat_broadcast import library_chat_broadcast
from app.serializers import profile_from_dict, utcnow
from app.services.district_context import area_block_for_name
from app.services.expert_async_tools import (
    LibraryToolScope,
    PlannedCall,
    ToolWork,
    _Thread,
    _last_user_text,
    _library_messages,
    _planned_calls,
    _prompts,
    tool_result_extra,
)
from app.services.jobs import job_session_factory
from app.services.library_chat_fifo import trim_and_commit_library_chat
from app.services.prompt_catalog import render_prompt
from app.services.workspace_chat_tools import CLIENT_TOOL_NAMES, workspace_openai_tools

logger = logging.getLogger(__name__)


def queue_document_open(scope: LibraryToolScope, source_id: str) -> None:
    scope.client_calls = [
        call for call in scope.client_calls
        if call.name != "show_document" or call.arguments.get("source_id") == source_id
    ]
    already_open = any(
        call.name == "show_document" and call.arguments.get("source_id") == source_id
        for call in scope.client_calls
    )
    if not already_open:
        scope.client_calls.append(PlannedCall(f"open-{source_id}", "show_document", {"source_id": source_id}))
    scope._calls = [call for call in scope._calls if call.name not in {"search_knowledge", "get_workspace_context"}]


async def _wake(thread: _Thread, work: ToolWork, blob: str) -> None:
    try:
        text = await _compose_followup(work, blob)
    except Exception:
        logger.exception("Expert tool wake failed for %s", work.persona_id)
        text = ""
    async with thread.cond:
        if thread.busy or not text.strip():
            if thread.busy and blob:
                thread.pending.append(blob)
            thread.waking = False
            thread.cond.notify_all()
            return
    try:
        await _save_followup(work, text)
    except Exception:
        logger.exception("Expert tool wake save failed for %s", work.persona_id)
        async with thread.cond:
            thread.pending.append(blob)
    finally:
        async with thread.cond:
            thread.waking = False
            thread.cond.notify_all()


async def _compose_followup(work: ToolWork, blob: str) -> str:
    from app.llm.chat import _chat_messages  # chat.py imports expert_async_tools

    factory = job_session_factory()
    async with factory() as session:
        persona = await session.get(Persona, work.persona_id)
        if persona is None:
            return ""
        prompts = await _prompts(session, persona)
        profile = profile_from_dict(persona.profile, persona.name)
        kind = persona.kind
        area = await area_block_for_name(session, profile.ort or persona.district)
        rows = list((await session.execute(_library_messages(work.persona_id, work.mode))).scalars())
        history = [(row.role, row.content, row.image_sha256) for row in rows]
        customer_id = persona.customer_id
        session.expunge(persona)
        await session.commit()
    messages = _chat_messages(
        profile,
        work.mode,
        history,
        tool_result_extra(prompts, blob),
        prompts=prompts,
        area_block=area,
        profile_kind=kind,
    )
    if work.workspace_id is None:
        return (await complete_text(messages, prompt_key="chat.expert.tool_result")).strip()
    turn = render_prompt(
        prompts, "workspace.chat.turn", workspace_json=json.dumps(work.workspace_state or {}, ensure_ascii=False),
    )
    messages[-1] = {**messages[-1], "content": f"{messages[-1]['content']}\n\n{turn}"}
    specs = [spec for spec in workspace_openai_tools(prompts) if spec["function"]["name"] in CLIENT_TOOL_NAMES]
    reply = await complete_with_tools(messages, specs, prompt_key="chat.expert.tool_result")
    payload = assistant_message_dict(reply)
    text = visible_assistant_text(payload)
    calls = [call for call in _planned_calls(reply, text, messages, consult=False) if call.name in CLIENT_TOOL_NAMES]
    if calls:
        await _publish_workspace_tools(customer_id, work, calls)
    return text.strip()


async def _publish_workspace_tools(customer_id: int, work: ToolWork, calls: list[PlannedCall]) -> None:
    for call in calls:
        await library_chat_broadcast.publish(customer_id, work.persona_id, {
            "type": "workspace_tool", "thread_type": "expert", "thread_id": work.persona_id,
            "mode": work.mode, "name": call.name, "arguments": call.arguments,
        })


async def _save_followup(work: ToolWork, text: str) -> None:
    from app.services.persona_chat import schedule_expert_memory_update, serialize_persona_message

    factory = job_session_factory()
    async with factory() as session:
        persona = await session.get(Persona, work.persona_id)
        if persona is None:
            return
        row = PersonaMessage(
            persona_id=work.persona_id,
            mode=work.mode,
            role="assistant",
            content=text,
            created_at=utcnow(),
        )
        session.add(row)
        await trim_and_commit_library_chat(session, work.persona_id, work.mode)
        stored = list((await session.execute(_library_messages(work.persona_id, work.mode))).scalars())
        customer_id = persona.customer_id
        question = _last_user_text(stored) or work.user_message
        payload = [serialize_persona_message(item).model_dump(mode="json") for item in stored]
        session.expunge(persona)
        await session.commit()
    await library_chat_broadcast.publish(
        customer_id,
        work.persona_id,
        {
            "type": "thread.message",
            "thread_type": "expert",
            "thread_id": work.persona_id,
            "mode": work.mode,
            "messages": payload,
        },
    )
    schedule_expert_memory_update(persona, message=question, reply=text, image_sha256=None)
