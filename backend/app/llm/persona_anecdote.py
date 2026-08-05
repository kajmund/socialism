"""Generate short personal anecdotes for population personas."""

from __future__ import annotations

from random import Random

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import complete_structured
from app.locality import load_norrkoping_brief
from app.schemas.domain import EditablePersona, PersonaAnecdoteOut
from app.services.district_context import area_block_for_name
from app.services.prompt_catalog import render_prompt
from app.services.prompt_store import require_active_prompts

_MAX_ANECDOTE_WORDS = 20
_POLITICAL_MARKERS = (
    " sympatiserar",
    " röstar ",
    " röstar på",
    " borde rösta",
    " bästa partiet",
    " rösta på",
    " politiskt",
    " regeringen borde",
    " oppositionen",
)


def _field(value: str, fallback: str) -> str:
    cleaned = value.strip()
    return cleaned if cleaned and cleaned != "—" else fallback


def stub_persona_anecdote(profile: EditablePersona, rng: Random) -> str:
    """Deterministic anecdote for stub population generation."""
    ort = _field(profile.ort, "stan")
    yrke = _field(profile.yrke, "jobbet")
    liv = profile.livssituation.strip()
    templates = [
        f"Igår mötte jag en kollega från {yrke} vid affären i {ort}.",
        f"Min syster brukar fråga om vardagen när hon ringer från {ort}.",
        f"Förra veckan stod jag i kö vid busshållplatsen i {ort} i regnet.",
        f"En granne i {ort} berättade nyligen om sitt barns fotbollsmatch i kväll.",
        f"Min kusin jobbar också inom {yrke} och skickade bilder från lunchrummet igår.",
    ]
    if liv and liv != "—":
        templates.append(
            f"Som {liv.casefold()} hänger jag ofta vid biblioteket i {ort} en stund."
        )
    return rng.choice(templates)


def anecdote_is_usable(text: str, profile: EditablePersona) -> bool:
    words = text.split()
    if len(words) < 4 or len(words) > _MAX_ANECDOTE_WORDS:
        return False
    lower = text.casefold()
    if any(marker in lower for marker in _POLITICAL_MARKERS):
        return False
    parti = profile.parti.strip().casefold()
    if len(parti) > 2 and parti in lower:
        return False
    return True


def _anecdote_context_lines(profile: EditablePersona) -> str:
    lines = [
        f"- Namn: {profile.name}",
        f"- Ålder: {profile.age}",
        f"- Ort/stadsdel: {profile.ort}",
        f"- Yrke: {profile.yrke}",
    ]
    if profile.livssituation.strip() not in ("", "—"):
        lines.append(f"- Livssituation: {profile.livssituation}")
    if profile.kön.strip() not in ("", "—"):
        lines.append(f"- Kön: {profile.kön}")
    return "\n".join(lines)


async def llm_persona_anecdote(
    profile: EditablePersona,
    *,
    session: AsyncSession | None = None,
    previous_anecdotes: tuple[str, ...] = (),
    prompts: dict[str, str] | None = None,
) -> str:
    if prompts is None:
        if session is None:
            raise RuntimeError("session or prompts is required for anecdote generation")
        prompts = await require_active_prompts(session)
    area_block = ""
    if session is not None:
        area_block = await area_block_for_name(session, profile.ort)
    brief = load_norrkoping_brief()
    prev_block = ""
    if previous_anecdotes:
        listed = "\n".join(f"  * {a}" for a in previous_anecdotes[-10:])
        prev_block = (
            f"\nAnekdoter som redan använts i populationen (skriv en annan):\n{listed}\n"
        )
    user = render_prompt(
        prompts,
        "persona.anecdote.user",
        persona_block=_anecdote_context_lines(profile),
        prev_block=prev_block,
    )
    local = brief
    if area_block.strip():
        local = f"{brief}\n\n{area_block.strip()}"
    system = render_prompt(prompts, "persona.anecdote.system", local_context=local)
    last_error = ""
    for _attempt in range(3):
        result = await complete_structured(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            PersonaAnecdoteOut,
        )
        if anecdote_is_usable(result.anekdot, profile):
            return result.anekdot
        last_error = result.anekdot
    return last_error or stub_persona_anecdote(profile, Random())
