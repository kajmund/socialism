"""Map population members / personas and injection senders to OASIS profiles."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.database.models import PopulationMember
from app.schemas.domain import Injection, InjectionType, Tick
from app.serializers import profile_from_dict

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


def build_injector_profile(injection: Injection, index: int) -> OasisAgentProfile:
    raw_sender = injection.sender.strip().lstrip("@")
    display = raw_sender or _TYPE_DEFAULT_NAME[injection.type]
    type_label = _TYPE_LABEL[injection.type]
    key = injector_key(injection)
    description = f"Officiellt {type_label}. Publicerar konfigurerade budskap."
    user_char = (
        f"Du är det officiella kontot {display} på en svensk social medietjänst. "
        f"Kontotyp: {type_label}. "
        "Du publicerar endast förberedda budskap och är inte en privatperson eller väljare. "
        "Du deltar inte i diskussioner, gillar inte andras inlägg och svarar inte."
    )
    return OasisAgentProfile(
        username=_slug_username(display, index),
        description=description,
        user_char=user_char,
        persona_id=None,
        member_name=display,
        role="injector",
        injector_key=key,
    )


def injectors_from_ticks(ticks: list[Tick]) -> list[OasisAgentProfile]:
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
            ordered.append(build_injector_profile(injection, len(ordered)))
    return ordered


def build_user_char(member: PopulationMember) -> str:
    profile = profile_from_dict(
        member.persona.profile if member.persona else None,
        member.name,
    )
    quote = (member.persona.quote if member.persona else "") or ""
    lines = [
        f"Du är {profile.name}, {profile.age} år, bor i {profile.ort} ({member.district}).",
        f"Yrke: {profile.yrke}. Livssituation: {profile.livssituation}.",
        f"Politisk lutning: {profile.lutning}. Parti: {profile.parti}.",
        f"Sakfrågor: {profile.sakfragor}.",
        f"Förtroende: {profile.fortroende}. Valdeltagande: {profile.valdeltagande}.",
        f"Ton: {profile.ton}. Språk: {profile.sprak}. Medievanor: {profile.medievanor}.",
    ]
    if member.trait.strip():
        lines.append(f"Karaktärsdrag: {member.trait.strip()}")
    if quote.strip():
        lines.append(f"Citat: {quote.strip()}")
    lines.append(
        "Du är användare på en svensk social medietjänst. "
        "Skriv korta inlägg på svenska, i din egen röst. "
        "Reagera autentiskt på politiska budskap utifrån din bakgrund."
    )
    return "\n".join(lines)


def members_to_profiles(
    members: list[PopulationMember],
    *,
    max_agents: int,
    start_index: int = 0,
) -> list[OasisAgentProfile]:
    capped = members[: max(0, max_agents)]
    out: list[OasisAgentProfile] = []
    for i, member in enumerate(capped):
        index = start_index + i
        profile = profile_from_dict(
            member.persona.profile if member.persona else None,
            member.name,
        )
        description = (
            f"{member.occ}, {member.age} år, {member.district}. "
            f"Lutning: {profile.lutning}."
        )
        out.append(
            OasisAgentProfile(
                username=_slug_username(member.name, index),
                description=description,
                user_char=build_user_char(member),
                persona_id=member.persona_id,
                member_name=member.name,
                role="population",
            )
        )
    return out


def build_run_profiles(
    members: list[PopulationMember],
    ticks: list[Tick],
    *,
    max_agents: int,
) -> tuple[list[OasisAgentProfile], dict[str, int]]:
    """Injectors first (no LLM), then population — combined length ≤ max_agents."""
    injectors = injectors_from_ticks(ticks)[: max(0, max_agents)]
    population_slots = max(0, max_agents - len(injectors))
    population = members_to_profiles(
        members,
        max_agents=population_slots,
        start_index=len(injectors),
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
