"""Map population members / personas and injection senders to OASIS profiles."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.database.models import PopulationMember
from app.schemas.domain import Injection, InjectionType, OasisPlatform, OasisRunOptions, Tick
from app.services.oasis_agent_tools import population_tool_rules
from app.serializers import profile_from_dict
from app.services.prompt_catalog import default_prompts, render_prompt

AgentRole = Literal["population", "injector"]

_TYPE_LABEL: dict[InjectionType, str] = {
    "party_post": "partikonto",
    "news_post": "nyhetskonto",
    "ad_post": "annonskonto",
}

_TYPE_DEFAULT_NAME: dict[InjectionType, str] = {
    "party_post": "Partikonto",
    "news_post": "Nyhetskonto",
    "ad_post": "Annonskonto",
}


@dataclass(frozen=True)
class OasisAgentProfile:
    username: str
    description: str
    user_char: str
    persona_id: str | None
    member_name: str
    role: AgentRole = "population"
    injector_key: str | None = None
    age: int = 30
    kön: str = "—"
    mbti: str | None = None


def _ascii_slug(name: str) -> str:
    parts = re.findall(r"[A-Za-zÅÄÖåäö0-9]+", name)
    base = "_".join(parts[:4]) if parts else "konto"
    return (
        base.replace("Å", "A")
        .replace("Ä", "A")
        .replace("Ö", "O")
        .replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
    )


def _slug_username(name: str, index: int) -> str:
    return f"{_ascii_slug(name)}_{index}"[:48]


def injector_key(injection: Injection) -> str:
    sender = injection.sender.strip().lstrip("@")
    if sender:
        return f"{injection.type}:{sender.casefold()}"
    return f"{injection.type}:default"


def injection_has_content(injection: Injection) -> bool:
    if injection.mode == "link" and injection.url.strip():
        return True
    return bool(injection.text.strip())


def injection_body(injection: Injection) -> str:
    """Post body shown to agents — matches OASIS injector content."""
    if injection.mode == "link" and injection.url.strip():
        body = injection.text.strip() or injection.sourceDomain.strip() or injection.url
        return f"{body}\n{injection.url.strip()}".strip()
    return injection.text.strip()


def _kon_is_set(kön: str) -> bool:
    return bool(kön.strip()) and kön.strip() not in ("—", "-", "?")


def oasis_gender_from_kon(kön: str) -> str:
    """Map Swedish kön label to OASIS Reddit gender enum string."""
    token = (
        kön.lower()
        .replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace(" ", "_")
        .replace("-", "_")
    )
    if token in {"kvinna", "female", "woman", "f"} or "kvinna" in token:
        return "female"
    if token in {"man", "male", "m"} or token == "man":
        return "male"
    if "icke" in token or "nonbinary" in token or "non_binary" in token:
        return "nonbinary"
    return "other"


def _short_description(
    *,
    occ: str,
    age: int,
    district: str,
    lutning: str,
    kön: str,
) -> str:
    parts: list[str] = []
    if _kon_is_set(kön):
        parts.append(kön.strip().casefold())
    parts.append(f"{age} år")
    parts.append(occ)
    parts.append(district)
    base = ", ".join(parts)
    return f"{base}. Lutning: {lutning}."


def population_action_rules(
    *,
    prompts: dict[str, str],
    allow_create_post: bool = False,
    platform: OasisPlatform = "twitter",
) -> str:
    if allow_create_post:
        post_rule = render_prompt(prompts, "oasis.agents.create_post.allow")
    elif platform == "reddit":
        post_rule = render_prompt(prompts, "oasis.agents.create_post.deny_reddit")
    else:
        post_rule = render_prompt(prompts, "oasis.agents.create_post.deny_twitter")
    base = render_prompt(prompts, "oasis.agents.action_rules").strip()
    marker = "ÅTGÄRDER (viktigt):\n"
    if marker in base:
        head, rest = base.split(marker, 1)
        return f"{head}{marker}{post_rule.strip()}\n{rest}"
    # English defaults use "ACTIONS (important):"
    en_marker = "ACTIONS (important):\n"
    if en_marker in base:
        head, rest = base.split(en_marker, 1)
        return f"{head}{en_marker}{post_rule.strip()}\n{rest}"
    return f"{base}\n{post_rule.strip()}"


# Tests / callers that expect the default Swedish rules (no create_post).
_POPULATION_ACTION_RULES = population_action_rules(
    prompts=default_prompts("sv"),
    allow_create_post=False,
)


def build_injector_profile(
    injection: Injection,
    index: int,
    *,
    prompts: dict[str, str],
) -> OasisAgentProfile:
    raw_sender = injection.sender.strip().lstrip("@")
    display = raw_sender or _TYPE_DEFAULT_NAME[injection.type]
    type_label = _TYPE_LABEL[injection.type]
    key = injector_key(injection)
    description = f"Officiellt {type_label}. Publicerar konfigurerade budskap."
    user_char = render_prompt(
        prompts,
        "oasis.agents.injector.user_char",
        display=display,
        type_label=type_label,
    )
    return OasisAgentProfile(
        username=_slug_username(display, index),
        description=description,
        user_char=user_char,
        persona_id=None,
        member_name=display,
        role="injector",
        injector_key=key,
        age=40,
        kön="—",
    )


def injectors_from_ticks(
    ticks: list[Tick],
    *,
    prompts: dict[str, str],
) -> list[OasisAgentProfile]:
    """One institutional injector per unique (type, sender) among non-empty injections."""
    ordered: list[OasisAgentProfile] = []
    seen: set[str] = set()
    for tick in ticks:
        if tick.silent:
            continue
        for injection in tick.injections:
            if not injection_has_content(injection):
                continue
            key = injector_key(injection)
            if key in seen:
                continue
            seen.add(key)
            ordered.append(
                build_injector_profile(injection, len(ordered), prompts=prompts)
            )
    return ordered


def build_user_char(
    member: PopulationMember,
    *,
    prompts: dict[str, str],
    area_block: str = "",
    allow_create_post: bool = False,
    platform: OasisPlatform = "twitter",
    oasis_options: OasisRunOptions | None = None,
) -> str:
    profile = profile_from_dict(
        member.persona.profile if member.persona else None,
        member.name,
    )
    quote = (member.persona.quote if member.persona else "") or ""
    trait = member.trait.strip()
    ton = profile.ton.strip() if profile.ton.strip() not in ("", "—") else ""
    kön = profile.kön.strip() if _kon_is_set(profile.kön) else ""
    identity = f"Du är {profile.name}, {profile.age} år"
    if kön:
        identity += f", {kön.casefold()}"
    identity += f", bor i {profile.ort} ({member.district})."
    lines = [identity]
    if trait:
        lines.append(f"Temperament / karaktärsdrag: {trait}")
    if ton and ton.casefold() not in trait.casefold():
        lines.append(
            f"Skrivsärdrag: håll dig till tonen «{ton}» — det är din röst, "
            "inte en fras att klistra in."
        )
    if quote.strip() and quote.strip().casefold() not in trait.casefold():
        lines.append(f"Citat / ledstjärna: {quote.strip()}")
    anekdot = profile.anekdot.strip()
    if anekdot and anekdot != "—":
        lines.append(
            "Personlig vardagsdetalj (anekdot du kan väva in ibland — "
            "inte i varje inlägg, ingen politisk poäng): "
            f"{anekdot}"
        )
    lines.append(
        "Din röst och temperament ska synas tydligare än ditt yrke — "
        "nämn jobb eller titel sällan, bara när det är direkt relevant."
    )
    if area_block.strip():
        lines.append(area_block.strip())
    lines.extend(
        [
            f"Yrke: {profile.yrke}. Livssituation: {profile.livssituation}.",
            f"Politisk lutning: {profile.lutning}. Parti: {profile.parti}.",
            f"Sakfrågor: {profile.sakfragor}.",
            f"Förtroende: {profile.fortroende}. Valdeltagande: {profile.valdeltagande}.",
            f"Språk: {profile.sprak}. Medievanor: {profile.medievanor}.",
        ]
    )
    lines.append(render_prompt(prompts, "oasis.agents.population.closing"))
    lines.append(
        population_action_rules(
            prompts=prompts,
            allow_create_post=allow_create_post,
            platform=platform,
        )
    )
    tool_rules = population_tool_rules(oasis_options or OasisRunOptions())
    if tool_rules:
        lines.append(tool_rules)
    return "\n".join(lines)


def _mbti_from_persona(member: PopulationMember) -> str | None:
    if member.persona is None or not member.persona.profile:
        return None
    raw = member.persona.profile.get("mbti")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().upper()
    return None


def members_to_profiles(
    members: list[PopulationMember],
    *,
    prompts: dict[str, str],
    start_index: int = 0,
    area_blocks: dict[str, str] | None = None,
    allow_create_post: bool = False,
    platform: OasisPlatform = "twitter",
    oasis_options: OasisRunOptions | None = None,
) -> list[OasisAgentProfile]:
    """Map every population member to an OASIS profile (no capping)."""
    blocks = area_blocks or {}
    out: list[OasisAgentProfile] = []
    for i, member in enumerate(members):
        index = start_index + i
        profile = profile_from_dict(
            member.persona.profile if member.persona else None,
            member.name,
        )
        kön = profile.kön if _kon_is_set(profile.kön) else "—"
        description = _short_description(
            occ=member.occ,
            age=member.age,
            district=member.district,
            lutning=profile.lutning,
            kön=kön,
        )
        area_block = (
            blocks.get(member.district)
            or blocks.get(profile.ort)
            or ""
        )
        out.append(
            OasisAgentProfile(
                username=_slug_username(member.name, index),
                description=description,
                user_char=build_user_char(
                    member,
                    prompts=prompts,
                    area_block=area_block,
                    allow_create_post=allow_create_post,
                    platform=platform,
                    oasis_options=oasis_options,
                ),
                persona_id=member.persona_id,
                member_name=member.name,
                role="population",
                age=member.age,
                kön=kön,
                mbti=_mbti_from_persona(member),
            )
        )
    return out


def build_run_profiles(
    members: list[PopulationMember],
    ticks: list[Tick],
    *,
    prompts: dict[str, str],
    area_blocks: dict[str, str] | None = None,
    allow_create_post: bool = False,
    platform: OasisPlatform = "twitter",
    oasis_options: OasisRunOptions | None = None,
) -> tuple[list[OasisAgentProfile], dict[str, int]]:
    """Injectors first (no LLM), then the full population — no agent cap."""
    injectors = injectors_from_ticks(ticks, prompts=prompts)
    population = members_to_profiles(
        members,
        prompts=prompts,
        start_index=len(injectors),
        area_blocks=area_blocks,
        allow_create_post=allow_create_post,
        platform=platform,
        oasis_options=oasis_options,
    )
    profiles = injectors + population
    key_to_index = {
        p.injector_key: i
        for i, p in enumerate(injectors)
        if p.injector_key is not None
    }
    return profiles, key_to_index


def write_twitter_profile_csv(profiles: list[OasisAgentProfile], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["username", "description", "user_char"])
        writer.writeheader()
        for row in profiles:
            writer.writerow(
                {
                    "username": row.username,
                    "description": row.description,
                    "user_char": row.user_char,
                }
            )
    return path


def write_reddit_profile_json(profiles: list[OasisAgentProfile], path: Path) -> Path:
    """Write OASIS Reddit agent JSON (generate_reddit_agent_graph format)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for profile in profiles:
        row: dict[str, object] = {
            "username": profile.username,
            "realname": profile.member_name,
            "bio": profile.description,
            "persona": profile.user_char,
            "age": profile.age,
            "gender": oasis_gender_from_kon(profile.kön),
            "country": "Sweden",
        }
        if profile.mbti:
            row["mbti"] = profile.mbti.strip().upper()
        rows.append(row)
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
