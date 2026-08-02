"""Map population members / personas to OASIS Twitter agent profile CSV rows."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from app.database.models import PopulationMember
from app.serializers import profile_from_dict


@dataclass(frozen=True)
class OasisAgentProfile:
    username: str
    description: str
    user_char: str
    persona_id: str | None
    member_name: str


def _slug_username(name: str, index: int) -> str:
    parts = re.findall(r"[A-Za-zÅÄÖåäö0-9]+", name)
    base = "_".join(parts[:3]) if parts else f"agent_{index}"
    # OASIS / Twitter-style handles: ASCII-ish, no spaces
    ascii_base = (
        base.replace("Å", "A")
        .replace("Ä", "A")
        .replace("Ö", "O")
        .replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
    )
    return f"{ascii_base}_{index}"[:48]


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
) -> list[OasisAgentProfile]:
    capped = members[: max(0, max_agents)]
    out: list[OasisAgentProfile] = []
    for i, member in enumerate(capped):
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
                username=_slug_username(member.name, i),
                description=description,
                user_char=build_user_char(member),
                persona_id=member.persona_id,
                member_name=member.name,
            )
        )
    return out


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
