import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Persona, UserAccount
from app.llm import complete_text
from app.services.actor_profiles import ActorProfileTools
from app.services.dd.expert_keys import persona_catalog_key
from app.services.expertgranskning.memory import ExpertMemoryHit, get_expert_memory
from app.services.prompt_catalog import render_prompt

LIVE_MEMORY_WINDOW = timedelta(hours=4)


def _memory_timestamp(hit: ExpertMemoryHit) -> datetime | None:
    raw = (hit.updated_at or hit.created_at).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def recent_voice_memories(
    hits: list[ExpertMemoryHit],
    *,
    now: datetime,
) -> list[ExpertMemoryHit]:
    cutoff = now.astimezone(UTC) - LIVE_MEMORY_WINDOW
    recent = [
        hit
        for hit in hits
        if (timestamp := _memory_timestamp(hit)) is not None and timestamp >= cutoff
    ]
    return sorted(
        recent,
        key=lambda hit: _memory_timestamp(hit) or datetime.min.replace(tzinfo=UTC),
    )


async def _memory_summary(
    persona: Persona,
    *,
    prompts: dict[str, str],
    now: datetime,
) -> str:
    hits = await get_expert_memory().list_all(
        customer_id=persona.customer_id,
        expert_id=persona_catalog_key(persona),
    )
    recent = recent_voice_memories(hits, now=now)
    if not recent:
        return ""
    source = [
        {
            "text": hit.text,
            "source": hit.source,
            "created_at": hit.created_at,
            "updated_at": hit.updated_at,
        }
        for hit in recent
    ]
    return await complete_text(
        [
            {
                "role": "system",
                "content": render_prompt(prompts, "chat.live.memory_summary"),
            },
            {
                "role": "user",
                "content": json.dumps({"memories": source}, ensure_ascii=False),
            },
        ],
        prompt_key="chat.live.memory_summary",
    )


async def build_live_voice_context(
    session: AsyncSession,
    *,
    persona: Persona,
    user: UserAccount,
    prompts: dict[str, str],
    now: datetime | None = None,
) -> tuple[str, str]:
    actor_context = await ActorProfileTools(
        session,
        user_id=user.id,
        customer_id=persona.customer_id,
        conversation=f"expert:{persona.id}:voice",
    )("get_actor_context", {})
    memory_summary = await _memory_summary(
        persona,
        prompts=prompts,
        now=now or datetime.now(UTC),
    )
    first_name = persona.name.strip().split(maxsplit=1)[0] or persona.name
    context = render_prompt(
        prompts,
        "chat.live.context",
        first_name=first_name,
        actor_context=actor_context,
        memory_summary=memory_summary,
    )
    initial_turn = render_prompt(prompts, "chat.live.initial_turn")
    return context, initial_turn
