"""Interview / in-character chat with a persona."""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.llm import complete_structured, complete_text, stream_text
from app.schemas.domain import ChatMode, EditablePersona, FollowUpQuestions
from app.services.dd.company_mcp import complete_text_with_company_tools
from app.services.expert_tools import expert_tool_prompt_extra, resolve_expert_tools
from app.services.prompt_catalog import render_prompt

MAX_FOLLOW_UPS = 3
MAX_QUESTION_CHARS = 140


def _expert_block(profile: EditablePersona) -> str:
    lines = [f"Namn: {profile.name}"]
    for label, value in (
        ("Uppdrag", profile.beskrivning),
        ("Kompetensområde", profile.kompetensomrade),
        ("Rådgivningsstil", profile.radgivningsstil),
        ("Yrkesbakgrund", profile.yrkesbakgrund),
        ("Anekdot", profile.professionell_anekdot),
    ):
        text = (value or "").strip()
        if text and text != "—":
            lines.append(f"{label}: {text}")
    return "\n".join(lines)


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
    prompts: dict[str, str],
    area_block: str = "",
    simulation_context: str = "",
    extra_system: str = "",
    profile_kind: str = "persona",
) -> str:
    local = area_block.strip()
    if profile_kind == "expert":
        persona_block = _expert_block(profile)
        profile_header = f"Profil för {profile.name} — du är den här experten:\n{persona_block}"
    else:
        persona_block = _persona_block(profile)
        profile_header = f"Profil för {profile.name} — du är den här personen:\n{persona_block}"
    if mode == "interview":
        mode_rules = render_prompt(prompts, "chat.mode.interview")
        role_lock = render_prompt(prompts, "chat.role_lock", name=profile.name)
    else:
        mode_rules = render_prompt(prompts, "chat.mode.in_character")
        role_lock = render_prompt(
            prompts, "chat.role_lock.in_character", name=profile.name
        )
    parts = [
        mode_rules,
        role_lock,
        "",
        profile_header,
    ]
    if local:
        parts.extend(["", f"Lokal kontext:\n{local}"])
    if simulation_context.strip():
        parts.extend(
            [
                "",
                "Simuleringskontext (det du sett hittills — inget annat):",
                simulation_context.strip(),
                "",
                render_prompt(prompts, "chat.simulation_context.footer"),
            ]
        )
    extra = extra_system.strip()
    if extra:
        parts.extend(["", extra])
    return "\n".join(parts)


def build_run_interview_prompt(
    profile: EditablePersona,
    feed_context: str,
    *,
    prompts: dict[str, str],
    day: int,
    tick_index: int,
    area_block: str = "",
) -> str:
    """System prompt for post-hoc interview after a specific simulation tick."""
    header = render_prompt(
        prompts,
        "chat.run_interview.header",
        day=day,
        tick_number=tick_index + 1,
    )
    return build_chat_system_prompt(
        profile,
        "interview",
        prompts=prompts,
        area_block=area_block,
        simulation_context=f"{header}\n\n{feed_context}",
    )


def _chat_messages(
    profile: EditablePersona,
    mode: ChatMode,
    history: list[tuple[str, str]],
    user_message: str,
    *,
    prompts: dict[str, str],
    area_block: str = "",
    simulation_context: str = "",
    system_prompt: str | None = None,
    extra_system: str = "",
    profile_kind: str = "persona",
) -> list[dict[str, str]]:
    content = system_prompt or build_chat_system_prompt(
        profile,
        mode,
        prompts=prompts,
        area_block=area_block,
        simulation_context=simulation_context,
        extra_system=extra_system,
        profile_kind=profile_kind,
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
    return messages


async def reply_as_persona(
    profile: EditablePersona,
    mode: ChatMode,
    history: list[tuple[str, str]],
    user_message: str,
    *,
    prompts: dict[str, str],
    area_block: str = "",
    simulation_context: str = "",
    system_prompt: str | None = None,
    extra_system: str = "",
    model: str | None = None,
    profile_kind: str = "persona",
) -> str:
    messages = _chat_messages(
        profile,
        mode,
        history,
        user_message,
        prompts=prompts,
        area_block=area_block,
        simulation_context=simulation_context,
        system_prompt=system_prompt,
        extra_system=extra_system,
        profile_kind=profile_kind,
    )
    return await complete_text(messages, model=model)


async def stream_reply_as_persona(
    profile: EditablePersona,
    mode: ChatMode,
    history: list[tuple[str, str]],
    user_message: str,
    *,
    prompts: dict[str, str],
    area_block: str = "",
    simulation_context: str = "",
    system_prompt: str | None = None,
    extra_system: str = "",
    profile_kind: str = "persona",
) -> AsyncIterator[str]:
    messages = _chat_messages(
        profile,
        mode,
        history,
        user_message,
        prompts=prompts,
        area_block=area_block,
        simulation_context=simulation_context,
        system_prompt=system_prompt,
        extra_system=extra_system,
        profile_kind=profile_kind,
    )
    async for chunk in stream_text(messages):
        yield chunk


async def stream_reply_as_expert(
    profile: EditablePersona,
    mode: ChatMode,
    history: list[tuple[str, str]],
    user_message: str,
    *,
    prompts: dict[str, str],
    area_block: str = "",
    simulation_context: str = "",
    system_prompt: str | None = None,
    tools: list[str] | None = None,
) -> AsyncIterator[str]:
    allowed = resolve_expert_tools(tools)
    extra = expert_tool_prompt_extra(prompts, allowed)
    messages = _chat_messages(
        profile,
        mode,
        history,
        user_message,
        prompts=prompts,
        area_block=area_block,
        simulation_context=simulation_context,
        system_prompt=system_prompt,
        extra_system=extra,
        profile_kind="expert",
    )
    reply = await complete_text_with_company_tools(
        messages, allowed_tools=frozenset(allowed)
    )
    if reply:
        yield reply


def normalize_follow_up_questions(raw: list[str]) -> list[str]:
    """Keep up to three unique, short analyst questions."""
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        text = " ".join(item.split())
        if not text:
            continue
        if len(text) > MAX_QUESTION_CHARS:
            clipped = text[:MAX_QUESTION_CHARS].rsplit(" ", 1)[0]
            text = clipped or text[:MAX_QUESTION_CHARS]
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= MAX_FOLLOW_UPS:
            break
    return out


def format_follow_up_transcript(
    history: list[tuple[str, str]],
    *,
    persona_name: str,
    user_label: str = "Intervjuare",
) -> str:
    if not history:
        return "(Inget samtal ännu.)"
    speaker = persona_name.strip() or "Persona"
    lines: list[str] = []
    for role, content in history:
        label = speaker if role == "assistant" else user_label
        lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _follow_up_prompt_keys(mode: ChatMode) -> tuple[str, str, str]:
    if mode == "interview":
        return (
            "chat.follow_up.questions",
            "chat.follow_up.voice",
            "Intervjuare",
        )
    return (
        "chat.follow_up.questions.in_character",
        "chat.follow_up.voice.in_character",
        "Samtalspartner",
    )


async def suggest_follow_up_questions(
    profile: EditablePersona,
    mode: ChatMode,
    history: list[tuple[str, str]],
    *,
    prompts: dict[str, str],
) -> list[str]:
    """LLM-proposed next user messages (Grok-style chips)."""
    chat_mode = "intervju" if mode == "interview" else "in-character"
    name = profile.name.strip() or "personan"
    questions_key, voice_key, user_label = _follow_up_prompt_keys(mode)
    system = render_prompt(
        prompts,
        questions_key,
        chat_mode=chat_mode,
        name=name,
        persona_block=_persona_block(profile),
        transcript=format_follow_up_transcript(
            history,
            persona_name=name,
            user_label=user_label,
        ),
    )
    voice = render_prompt(prompts, voice_key, name=name)
    result = await complete_structured(
        [{"role": "system", "content": f"{system}\n\n{voice}"}],
        FollowUpQuestions,
    )
    return normalize_follow_up_questions(result.questions)
