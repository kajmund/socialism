import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona
from app.schemas.domain import JobCreate
from app.services.dd.company_mcp import RESEARCH_TOOL_NAME, ResearchToolHandler

_RESEARCH_START_CLAIM = re.compile(
    r"("
    r"\b(startat|startade|startar|startad|köat|köade|köar)\b[^.!?]{0,48}\bresearch"
    r"|"
    r"\bresearch\w*\b[^.!?]{0,48}\b(startat|startade|startar|startad|igång|köat|köade|köar)\b"
    r"|"
    r"\bresearchjobbet är\b"
    r"|"
    r"\b(started|queued)\b[^.!?]{0,24}\bresearch\b"
    r"|"
    r"\bresearch\b[^.!?]{0,24}\b(started|queued|underway)\b"
    r")",
    re.IGNORECASE,
)
_RESEARCH_OFFER = re.compile(r"\b(ska jag|vill du|ska vi|should i|do you want)\b", re.IGNORECASE)
_QUEUED_TOOL_RESULT = re.compile(r"(^köat\b|är redan köat\b|är köat\b)", re.IGNORECASE)
_RESEARCH_NOT_STARTED = (
    "Research startades inte. Jag måste fråga dig först och vänta på ett uttryckligt ja "
    "i nästa meddelande."
)


def research_job_was_queued(messages: list[dict[str, Any]]) -> bool:
    for message in messages:
        if message.get("role") != "tool" or message.get("name") != RESEARCH_TOOL_NAME:
            continue
        if _QUEUED_TOOL_RESULT.search(str(message.get("content") or "").casefold()):
            return True
    return False


def _substantive_user_question(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        text = content.strip() if isinstance(content, str) else ""
        if not text or _explicit_research_confirmation(text):
            continue
        return text[:4000]
    return ""


def _claims_research_started(text: str) -> bool:
    if not text.strip() or not _RESEARCH_START_CLAIM.search(text):
        return False
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return any(
        _RESEARCH_START_CLAIM.search(sentence) and not _RESEARCH_OFFER.search(sentence)
        for sentence in sentences
    )


def research_calls_from_start_claim(
    text: str,
    messages: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Queue start_research when the reply claims a start but never called the tool."""
    if any(
        message.get("role") == "tool" and message.get("name") == RESEARCH_TOOL_NAME
        for message in messages
    ):
        return []
    question = _substantive_user_question(messages)
    if not question or not _claims_research_started(text):
        return []
    return [{"question": question}]


def reply_without_unbacked_research_start(text: str, *, queued: bool) -> str:
    """Drop a claim that research started unless this turn queued a job."""
    if queued or not text.strip() or not _RESEARCH_START_CLAIM.search(text):
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = [
        sentence
        for sentence in sentences
        if _RESEARCH_OFFER.search(sentence) or not _RESEARCH_START_CLAIM.search(sentence)
    ]
    if kept:
        return " ".join(kept)
    return _RESEARCH_NOT_STARTED


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
    persona_row_id = persona.id
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
                    "persona_id": persona_row_id,
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
