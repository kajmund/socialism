"""Remembered expert turns rendered into the next chat prompt."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.database.models import Persona
from app.services.dd.expert_keys import persona_catalog_key
from app.services.expertgranskning.memory import ExpertMemoryHit, get_expert_memory
from app.services.prompt_catalog import render_prompt

MEMORY_TIME_ZONE = ZoneInfo("Europe/Stockholm")

_SOURCE_LABELS = {
    "persona_chat": "chatt",
    "panel_chat": "panel",
    "expert_consult": "konsult",
    "intent_interview": "intervju",
    "word_findings": "dokumentgranskning",
}


def _memory_age(created_at: str) -> str:
    raw = (created_at or "").strip()
    if not raw:
        return ""
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    created_utc = created.astimezone(timezone.utc)
    days = (datetime.now(timezone.utc) - created_utc).days
    if days < 0:
        return ""
    if days <= 1:
        return "idag" if days == 0 else "igår"
    if days < 30:
        return f"{days} dagar sedan"
    return created_utc.astimezone(MEMORY_TIME_ZONE).strftime("%Y-%m-%d")


def expert_memory_context_line(hit: ExpertMemoryHit) -> str:
    age = _memory_age(hit.created_at)
    if hit.source == "research_receipt":
        question_id = str(hit.metadata.get("knowledge_question_id") or "unknown")
        attempt_id = str(hit.metadata.get("source_attempt_id") or "unknown")
        origin = (
            f"research_receipt; knowledge_question_id={question_id}; "
            f"source_attempt_id={attempt_id}"
        )
        if age:
            origin = f"{origin}; {age}"
        return f"- {hit.text} [{origin}]"
    label = _SOURCE_LABELS.get(hit.source) or hit.source or "okänd"
    origin = f"källa: {label}"
    if age:
        origin = f"{origin}, {age}"
    return f"- {hit.text} [{origin}]"


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
    memories = "\n".join(expert_memory_context_line(hit) for hit in hits)
    return render_prompt(prompts, "chat.expert.memory", memories=memories)
