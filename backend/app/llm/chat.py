"""Interview / in-character chat with a persona."""

from __future__ import annotations

from app.llm import complete_text
from app.locality import load_norrkoping_brief
from app.schemas.domain import ChatMode, EditablePersona


def build_chat_system_prompt(
    profile: EditablePersona,
    mode: ChatMode,
    *,
    area_block: str = "",
) -> str:
    brief = load_norrkoping_brief()
    local = brief
    if area_block.strip():
        local = f"{brief}\n\n{area_block.strip()}"
    persona_block = "\n".join(
        [
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
    )
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
    return (
        f"{mode_rules}\n\n"
        f"Din persona:\n{persona_block}\n\n"
        f"Lokal kontext:\n{local}"
    )


async def reply_as_persona(
    profile: EditablePersona,
    mode: ChatMode,
    history: list[tuple[str, str]],
    user_message: str,
    *,
    area_block: str = "",
) -> str:
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": build_chat_system_prompt(profile, mode, area_block=area_block),
        },
    ]
    for role, content in history:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})
    return await complete_text(messages)
