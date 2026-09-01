"""Chat turns that search companies through the company MCP (BolagsAPI or Allabolag)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import complete_with_tools
from app.llm.tool_messages import assistant_message_dict
from app.services.dd.company_mcp import (
    CompanyMcpError,
    run_company_tool_loop,
    visible_assistant_text,
)
from app.services.dd.schemas import DdCandidateCompany, DdSourcingChatMessage
from app.services.prompt_store import render_prompt, require_active_prompts

_HISTORY_LIMIT = 16


class SourcingChatError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def merge_candidates(
    existing: list[DdCandidateCompany],
    incoming: list[DdCandidateCompany],
) -> list[DdCandidateCompany]:
    by_orgnr = {row.organisationsnummer: row for row in existing}
    order = [row.organisationsnummer for row in existing]
    for row in incoming:
        if row.organisationsnummer not in by_orgnr:
            order.append(row.organisationsnummer)
        by_orgnr[row.organisationsnummer] = row
    return [by_orgnr[orgnr] for orgnr in order]


async def run_sourcing_chat_turn(
    session: AsyncSession,
    *,
    message: str,
    history: Sequence[DdSourcingChatMessage] = (),
    customer_id: int,
) -> tuple[str, list[DdCandidateCompany]]:
    text = message.strip()
    if not text:
        raise SourcingChatError("Message is required")

    try:
        prompts = await require_active_prompts(
            session,
            customer_id=customer_id,
            module="dd",
            language="sv",
        )
        system_prompt = render_prompt(prompts, "dd.sourcing.chat.system")
    except Exception as exc:
        raise SourcingChatError(str(exc), status_code=503) from exc

    prior = [
        {"role": row.role, "content": row.content}
        for row in history[-_HISTORY_LIMIT:]
        if row.content.strip()
    ]
    working: list[dict] = [
        {"role": "system", "content": system_prompt},
        *prior,
        {"role": "user", "content": text},
    ]

    try:
        working, found = await run_company_tool_loop(working)
    except CompanyMcpError as exc:
        raise SourcingChatError(str(exc), status_code=502) from exc

    content = visible_assistant_text(working[-1])
    if not content:
        working.append(
            {
                "role": "user",
                "content": render_prompt(prompts, "dd.sourcing.chat.visible_reply"),
            }
        )
        reply = await complete_with_tools(working, None)
        working.append(assistant_message_dict(reply))
        content = visible_assistant_text(working[-1])
    if not content:
        raise SourcingChatError("Company search chat produced an invalid reply")
    return content, found
