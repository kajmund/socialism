"""Interview / in-character chat with a persona."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.config import settings
from app.llm import complete_structured, complete_text, stream_text
from app.llm.vision_content import user_content_with_optional_image
from app.schemas.domain import ChatMode, EditablePersona, FollowUpQuestions
from app.services.actor_profiles import ActorToolHandler
from app.services.dd.company_mcp import (
    ConsultToolHandler,
    ResearchToolHandler,
    complete_text_with_company_tools,
)
from app.services.expert_tools import expert_tool_prompt_extra, resolve_chat_tools
from app.services.prompt_catalog import render_prompt

MAX_FOLLOW_UPS = 3
MAX_QUESTION_CHARS = 140
# Chips are short JSON. Thinking-mode DeepSeek otherwise occupies the
# same connection the first chat turn needs (HTTP 200, then a long body).
_FOLLOW_UP_MAX_TOKENS = 512
_FOLLOW_UP_TIMEOUT_SECONDS = 15.0


def _chat_prompt_key(mode: ChatMode) -> str:
    if mode == "interview":
        return "chat.mode.interview"
    return "chat.mode.in_character"


def _follow_up_reasoning_effort() -> str | None:
    if settings.llm_provider == "deepseek":
        return "none"
    return None


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
        role_lock = render_prompt(prompts, "chat.role_lock.in_character", name=profile.name)
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
    history: list[tuple[str, str]] | list[tuple[str, str, str | None]],
    user_message: str,
    *,
    prompts: dict[str, str],
    area_block: str = "",
    simulation_context: str = "",
    system_prompt: str | None = None,
    extra_system: str = "",
    profile_kind: str = "persona",
    user_image_sha256: str | None = None,
) -> list[dict[str, Any]]:
    if system_prompt is None:
        content = build_chat_system_prompt(
            profile,
            mode,
            prompts=prompts,
            area_block=area_block,
            simulation_context=simulation_context,
            extra_system=extra_system,
            profile_kind=profile_kind,
        )
    else:
        content = system_prompt
        extra = extra_system.strip()
        if extra:
            content = f"{content}\n\n{extra}"
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": content,
        },
    ]
    for entry in history:
        role = entry[0]
        text = entry[1]
        image_sha = entry[2] if len(entry) > 2 else None
        messages.append(
            {
                "role": role,
                "content": user_content_with_optional_image(text, image_sha),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": user_content_with_optional_image(user_message, user_image_sha256),
        }
    )
    return messages


async def reply_as_persona(
    profile: EditablePersona,
    mode: ChatMode,
    history: list[tuple[str, str]] | list[tuple[str, str, str | None]],
    user_message: str,
    *,
    prompts: dict[str, str],
    area_block: str = "",
    simulation_context: str = "",
    system_prompt: str | None = None,
    extra_system: str = "",
    model: str | None = None,
    profile_kind: str = "persona",
    user_image_sha256: str | None = None,
    tools: list[str] | None = None,
    research_tool_handler: ResearchToolHandler | None = None,
    consult_tool_handler: ConsultToolHandler | None = None,
    actor_tool_handler: ActorToolHandler | None = None,
) -> str:
    allowed = resolve_chat_tools(tools, kind=profile_kind)
    tool_extra = expert_tool_prompt_extra(prompts, allowed)
    combined_extra = extra_system
    if tool_extra:
        combined_extra = f"{extra_system}\n\n{tool_extra}".strip() if extra_system else tool_extra
    messages = _chat_messages(
        profile,
        mode,
        history,
        user_message,
        prompts=prompts,
        area_block=area_block,
        simulation_context=simulation_context,
        system_prompt=system_prompt,
        extra_system=combined_extra,
        profile_kind=profile_kind,
        user_image_sha256=user_image_sha256,
    )
    if allowed:
        return await complete_text_with_company_tools(
            messages,
            allowed_tools=frozenset(allowed),
            research_tool_handler=research_tool_handler,
            consult_tool_handler=consult_tool_handler,
            actor_tool_handler=actor_tool_handler,
            prompt_key=_chat_prompt_key(mode),
        )
    return await complete_text(
        messages, model=model, prompt_key=_chat_prompt_key(mode)
    )


async def stream_reply_as_persona(
    profile: EditablePersona,
    mode: ChatMode,
    history: list[tuple[str, str]] | list[tuple[str, str, str | None]],
    user_message: str,
    *,
    prompts: dict[str, str],
    area_block: str = "",
    simulation_context: str = "",
    system_prompt: str | None = None,
    extra_system: str = "",
    profile_kind: str = "persona",
    tools: list[str] | None = None,
    user_image_sha256: str | None = None,
    research_tool_handler: ResearchToolHandler | None = None,
    consult_tool_handler: ConsultToolHandler | None = None,
    actor_tool_handler: ActorToolHandler | None = None,
) -> AsyncIterator[str]:
    allowed = resolve_chat_tools(tools, kind=profile_kind)
    extra = expert_tool_prompt_extra(prompts, allowed)
    combined_extra = extra_system
    if extra:
        combined_extra = f"{extra_system}\n\n{extra}".strip() if extra_system else extra
    messages = _chat_messages(
        profile,
        mode,
        history,
        user_message,
        prompts=prompts,
        area_block=area_block,
        simulation_context=simulation_context,
        system_prompt=system_prompt,
        extra_system=combined_extra,
        profile_kind=profile_kind,
        user_image_sha256=user_image_sha256,
    )
    if allowed:
        reply = await complete_text_with_company_tools(
            messages,
            allowed_tools=frozenset(allowed),
            research_tool_handler=research_tool_handler,
            consult_tool_handler=consult_tool_handler,
            actor_tool_handler=actor_tool_handler,
            prompt_key=_chat_prompt_key(mode),
        )
        if reply:
            yield reply
        return
    async for chunk in stream_text(messages, prompt_key=_chat_prompt_key(mode)):
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
    async for chunk in stream_reply_as_persona(
        profile,
        mode,
        history,
        user_message,
        prompts=prompts,
        area_block=area_block,
        simulation_context=simulation_context,
        system_prompt=system_prompt,
        profile_kind="expert",
        tools=tools,
    ):
        yield chunk


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
        max_tokens=_FOLLOW_UP_MAX_TOKENS,
        timeout=_FOLLOW_UP_TIMEOUT_SECONDS,
        reasoning_effort=_follow_up_reasoning_effort(),
        prompt_key=questions_key,
    )
    return normalize_follow_up_questions(result.questions)
