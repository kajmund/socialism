import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona
from app.schemas.domain import JobCreate
from app.services.expert_session_tools import ResearchToolHandler
from app.services.expert_turn_cancel import turn_is_cancelled


def research_tool_handler_for_chat(
    session: AsyncSession,
    *,
    persona: Persona,
    history: list[tuple[str, str, str | None, str | None]],
    user_message: str,
) -> ResearchToolHandler:
    # Callers still pass the current user text. The tool call itself is the
    # decision; that text is not a second confirmation gate.
    del user_message
    queued_job_id: str | None = None
    specific_question = next(
        (entry[1] for entry in reversed(history) if entry[0] == "user"),
        "",
    )

    async def handle(arguments: dict[str, Any]) -> str:
        nonlocal queued_job_id
        if turn_is_cancelled():
            raise asyncio.CancelledError
        if queued_job_id is not None:
            return f"Researchjobbet är redan köat: {queued_job_id}"
        question = str(arguments.get("question") or "").strip()
        if not question or len(question) > 4000:
            return "Research startades inte: question måste vara 1–4000 tecken."
        # jobs imports the research execution graph, which imports this chat path
        # during app startup. Delay this strict circular boundary until invocation.
        from app.services import jobs as jobs_service

        job = await jobs_service.create_job(
            session,
            JobCreate(
                kind="expert_chat_research",
                label=f"Expertresearch: {question[:80]}",
                request={
                    "persona_id": persona.id,
                    "specific_question": specific_question or question,
                    "question": question,
                },
            ),
        )
        if session.in_transaction():
            await session.commit()
        jobs_service.enqueue_job(job.id)
        queued_job_id = job.id
        return (
            f"Researchjobbet är köat i bakgrunden med id {job.id}. "
            "Resultatet finns inte ännu."
        )

    return handle
