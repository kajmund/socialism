"""Remembered expert turns rendered into the next chat prompt."""

from app.database.models import Persona
from app.services.dd.expert_keys import persona_catalog_key
from app.services.expertgranskning.memory import ExpertMemoryHit, get_expert_memory
from app.services.prompt_catalog import render_prompt


async def expert_memory_context(
    persona: Persona,
    message: str,
    prompts: dict[str, str],
    *,
    image_sha256: str | None = None,
) -> str:
    if persona.kind != "expert":
        return ""
    hits = await get_expert_memory().search(
        customer_id=persona.customer_id,
        expert_id=persona_catalog_key(persona),
        query=message,
        image_sha256=image_sha256,
        sources=frozenset(
            {
                "persona_chat",
                "panel_chat",
                "expert_consult",
                "intent_interview",
                "word_findings",
                "research_receipt",
            }
        ),
    )
    if not hits:
        return ""
    memories = "\n".join(_expert_memory_context_line(hit) for hit in hits)
    return render_prompt(prompts, "chat.expert.memory", memories=memories)


def _expert_memory_context_line(hit: ExpertMemoryHit) -> str:
    if hit.source != "research_receipt":
        return f"- {hit.text}"
    question_id = str(hit.metadata.get("knowledge_question_id") or "unknown")
    attempt_id = str(hit.metadata.get("source_attempt_id") or "unknown")
    return (
        "- [research_receipt; "
        f"knowledge_question_id={question_id}; source_attempt_id={attempt_id}] "
        f"{hit.text}"
    )
