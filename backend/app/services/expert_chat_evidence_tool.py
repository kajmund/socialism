"""Chat tool that reads frozen evidence for one asked question."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.session import SessionLocal
from app.services.dd.company_mcp import ResearchToolHandler

EVIDENCE_TOOL_NAME = "lookup_frozen_evidence"
_NOT_A_QUESTION = (
    "Inget evidensuppslag. Verktyget läser bara fryst evidens för en ställd fråga, "
    "inte för hälsningar eller småprat."
)
_GREETING_ONLY = re.compile(
    r"^(?:hej|hejsan|tjena|tja|hallå|halla|hello|hi|hey|"
    r"god morgon|god dag|god kväll|tack|tackar|thanks|thank you|ok|okej|okay)"
    r"[.!\s]*$",
    re.IGNORECASE,
)
_INTERROGATIVE = re.compile(
    r"(?:^|[\s,;:])(vad|vem|vilken|vilket|vilka|hur|varför|varfor|när|nar|var|"
    r"what|who|why|how|when|where|which)\b",
    re.IGNORECASE,
)


def evidence_lookup_question(text: str) -> str | None:
    """The asked question, or None when the text is not a question."""
    stripped = " ".join(text.split()).strip()
    if not stripped or _GREETING_ONLY.match(stripped):
        return None
    if "?" not in stripped and _INTERROGATIVE.search(stripped) is None:
        return None
    return stripped


def evidence_tool_handler_for_chat(
    *,
    customer_id: int,
    prompts: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> ResearchToolHandler:
    """Frozen-evidence lookup on its own session. Greetings never touch the graph."""
    factory = session_factory or SessionLocal

    async def handle(arguments: dict[str, Any]) -> str:
        question = evidence_lookup_question(str(arguments.get("question") or ""))
        if question is None:
            return _NOT_A_QUESTION
        # The evidence reader imports the research graph. Keep that off the chat import path.
        from app.services.expert_chat_evidence import reusable_expert_chat_evidence_context

        async with factory() as session:
            context = await reusable_expert_chat_evidence_context(
                session,
                customer_id=customer_id,
                question=question,
                prompts=prompts,
                include_claims=False,
            )
        if not context:
            return "Ingen fryst evidens matchar frågan."
        return context

    return handle
