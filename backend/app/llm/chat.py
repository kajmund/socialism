"""Interview / in-character chat with a persona."""

from __future__ import annotations

from app.llm import complete_text
from app.locality import load_norrkoping_brief
from app.schemas.domain import ChatMode, EditablePersona


def _persona_block(profile: EditablePersona) -> str:
    lines = [
        f"Namn: {profile.name}",
        f"Ålder: {profile.age}",
        f"Kön: {profile.kön}",
        f"Ort: {profile.ort}",
        f"Yrke: {profile.yrke}",
        f"Utbildning: {profile.utbildning}",
        f"Livssituation: {profile.livssituation}",
        f"Lutning: {profile.lutning}",
        f"Sakfrågor: {profile.sakfragor}",
        f"Förtroende: {profile.fortroende}",
        f"Ton: {profile.ton}",
        f"Språk: {profile.sprak}",
        f"Medievanor: {profile.medievanor}",
        f"Parti: {profile.parti}",
        f"Valdeltagande: {profile.valdeltagande}",
    ]
    anekdot = (profile.anekdot or "").strip()
    if anekdot and anekdot != "—":
        lines.append(f"Vardagsdetalj: {anekdot}")
    return "\n".join(lines)


def build_chat_system_prompt(
    profile: EditablePersona,
    mode: ChatMode,
    *,
    area_block: str = "",
    simulation_context: str = "",
) -> str:
    brief = load_norrkoping_brief()
    local = brief
    if area_block.strip():
        local = f"{brief}\n\n{area_block.strip()}"
    persona_block = _persona_block(profile)
    if mode == "interview":
        mode_rules = (
            "Läge: INTERVJU. En analytiker intervjuar dig. Svara i första person som personan. "
            "Var kort (1–4 meningar), konkret, och håll dig till din bakgrund. "
            "Hitta inte på statistik du inte skulle kunna. Svara på svenska."
        )
    else:
        mode_rules = (
            "Läge: IN-CHARACTER. Användaren pratar med dig som i din vardag/sociala flöde. "
            "Svara i första person, naturligt talspråk, kort. Svara på svenska."
        )
    parts = [
        mode_rules,
        "",
        f"Din persona:\n{persona_block}",
        "",
        f"Lokal kontext:\n{local}",
    ]
    if simulation_context.strip():
        parts.extend(
            [
                "",
                "Simuleringskontext (det du sett hittills — inget annat):",
                simulation_context.strip(),
                "",
                "Viktigt: Du befinner dig vid tidpunkten ovan. Du har inte sett något "
                "som hände efteråt. Hitta inte på händelser som inte finns i flödet.",
            ]
        )
    return "\n".join(parts)


def build_run_interview_prompt(
    profile: EditablePersona,
    feed_context: str,
    *,
    day: int,
    tick_index: int,
    area_block: str = "",
) -> str:
    """System prompt for post-hoc interview after a specific simulation tick."""
    header = (
        f"Du befinner dig efter dag {day} (tick {tick_index + 1}) i en "
        "simulering av ett socialt flöde. En analytiker intervjuar dig."
    )
    return build_chat_system_prompt(
        profile,
        "interview",
        area_block=area_block,
        simulation_context=f"{header}\n\n{feed_context}",
    )


async def reply_as_persona(
    profile: EditablePersona,
    mode: ChatMode,
    history: list[tuple[str, str]],
    user_message: str,
    *,
    area_block: str = "",
    simulation_context: str = "",
    system_prompt: str | None = None,
) -> str:
    content = system_prompt or build_chat_system_prompt(
        profile,
        mode,
        area_block=area_block,
        simulation_context=simulation_context,
    )
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": content,
        },
    ]
    for role, content_row in history:
        messages.append({"role": role, "content": content_row})
    messages.append({"role": "user", "content": user_message})
    return await complete_text(messages)
