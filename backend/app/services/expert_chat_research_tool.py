import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona
from app.schemas.domain import JobCreate
from app.services.dd.company_mcp import ResearchToolHandler


def _explicit_research_confirmation(message: str) -> bool:
    normalized = " ".join(re.sub(r"[^\w]+", " ", message.casefold()).split())
    if any(
        re.search(rf"\b{word}\b", normalized)
        for word in ("nej", "inte", "stoppa", "avstå", "vänta")
    ):
        return False
    if normalized in {
        "ja",
        "ja tack",
        "ja gör det",
        "ja starta research",
        "absolut",
        "gör det",
        "starta research",
        "starta den",
        "kör",
        "kör igång",
        "kör researchen",
        "yes",
        "yes please",
        "start the research",
        "go ahead",
    }:
        return True
    approval = any(
        phrase in normalized
        for phrase in (
            "jag godkänner",
            "mitt godkännande",
            "du får",
            "gör gärna",
            "kör igång",
            "go ahead",
            "you may",
        )
    )
    action = any(
        phrase in normalized
        for phrase in (
            "research",
            "undersök",
            "ta reda på",
            "gör det",
            "starta",
        )
    )
    affirmative = normalized.startswith(("ja ", "absolut "))
    return (approval or affirmative) and action


def _assistant_offered_research(message: str) -> bool:
    normalized = " ".join(re.sub(r"[^\w]+", " ", message.casefold()).split())
    mentions_research = "research" in normalized
    mentions_start = any(
        re.search(rf"\b{word}\b", normalized)
        for word in ("starta", "startar", "start", "begin")
    )
    return mentions_research and mentions_start


def research_tool_handler_for_chat(
    session: AsyncSession,
    *,
    persona: Persona,
    history: list[tuple[str, str, str | None]],
    user_message: str,
) -> ResearchToolHandler:
    queued_job_id: str | None = None
    previous_assistant = (
        history[-1][1] if history and history[-1][0] == "assistant" else ""
    )
    specific_question = next(
        (content for role, content, _image in reversed(history) if role == "user"),
        "",
    )

    async def handle(arguments: dict[str, Any]) -> str:
        nonlocal queued_job_id
        if queued_job_id is not None:
            return f"Researchjobbet är redan köat: {queued_job_id}"
        offered = _assistant_offered_research(previous_assistant)
        if not offered or not _explicit_research_confirmation(user_message):
            return (
                "Research startades inte. Du måste först fråga användaren och invänta "
                "ett uttryckligt bekräftande svar i nästa chattmeddelande."
            )
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
        jobs_service.enqueue_job(job.id)
        queued_job_id = job.id
        return (
            f"Researchjobbet är köat i bakgrunden med id {job.id}. "
            "Resultatet finns inte ännu."
        )

    return handle
