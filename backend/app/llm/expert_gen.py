"""Build prompts and call LLM for expert-profile suggestions from underlag."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import complete_structured
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts

DEFAULT_SUGGEST_COUNT = 4
# Leave room for templates + JSON schema inside a single DeepSeek completion.
MAX_EXPERT_UNDERLAG_CHARS = 80_000


class ExpertCandidate(BaseModel):
    name: str
    description: str
    kompetensomrade: str
    radgivningsstil: str
    yrkesbakgrund: str
    professionell_anekdot: str


class ExpertCandidatesOut(BaseModel):
    candidates: list[ExpertCandidate] = Field(min_length=1)


def _require_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Underlag has no extracted text")
    if len(cleaned) > MAX_EXPERT_UNDERLAG_CHARS:
        raise ValueError(
            f"Underlag text is {len(cleaned)} characters; "
            f"maximum is {MAX_EXPERT_UNDERLAG_CHARS}"
        )
    return cleaned


async def llm_experts_from_underlag(
    text: str,
    count: int,
    module: str,
    session: AsyncSession,
    *,
    customer_id: int,
    language: str = "sv",
    prompts: dict[str, str] | None = None,
) -> list[ExpertCandidate]:
    if count < 1:
        raise ValueError("count must be at least 1")
    underlag_text = _require_text(text)
    if prompts is None:
        prompts = await require_active_prompts(
            session,
            customer_id=customer_id,
            module=module,
            language=language,
        )
    system = render_prompt(
        prompts,
        "expert.from_underlag.system",
        count=count,
        module=module,
    )
    user = render_prompt(
        prompts,
        "expert.from_underlag.user",
        count=count,
        module=module,
        underlag_text=underlag_text,
    )
    result = await complete_structured(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        ExpertCandidatesOut,
    )
    if len(result.candidates) != count:
        raise RuntimeError(
            f"Expected {count} expert candidates, got {len(result.candidates)}"
        )
    for index, candidate in enumerate(result.candidates):
        if not candidate.name.strip():
            raise RuntimeError(f"Expert candidate {index + 1} is missing a name")
    return result.candidates
