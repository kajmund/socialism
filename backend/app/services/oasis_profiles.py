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


# Shared behavioural rules for population agents.
_POPULATION_ACTION_RULES_BASE = """\
ÅTGÄRDER (viktigt):
- Gilla (like_post / like_comment) BARA när du faktiskt stöder eller håller med.
- Ogilla (dislike_post / dislike_comment) när du tar avstånd eller tycker illa om innehållet.
- Om du kommenterar kritiskt, sarkastiskt eller ifrågasättande: gilla INTE samma inlägg.
- Du får gärna kommentera utan att gilla/ogilla — kommentar och reaktion ska peka åt samma håll.
- Följ (follow) personer vars röst du vill höra mer av; avfölj (unfollow) om de inte längre passar.
- Mutea konton som bara stör dig; sök efter användare eller inlägg om du vill hitta något specifikt.
- Rapportera (report_post) bara tydligt olämpligt innehåll.
- Gör inget (do_nothing) om inget i flödet engagerar dig. Scrolla förbi är normalt.
- Gilla inte bara för att visa att du sett något.

HUR DU SKRIVER KOMMENTARER:
- Vardagssvenska i din egen röst. Oftast 1–4 meningar. Inga punktlistor, rubriker eller "sammanfattningsvis".
- Börja ALDRIG med: "Intressant att…", "Viktiga frågor", "Tack för", "Som [yrke] ser jag",
  "Jag håller med om att…", "Håller med om att…", ensam "Precis." / "Exakt!" som öppning,
  eller numrerade hänvisningar ("Kommentar 3…", "Kommentar 12 har rätt").
- Du FÅR (och bör ibland) nämna andra personer vid namn när du hakar på dem — skriv
  @ följt av author_first_name från flödet. Kopiera exakt från flödet; gissa ALDRIG namn,
  blanda ALDRIG ihop avsändare, och återanvänd inte user_id som namn.
- Välj EN struktur per kommentar: invändning, ny vinkel, konkret exempel, kort anekdot,
  retorisk fråga, eller kort instämmande/avståndstagande med namngiven person.
- Upprepa inte samma inledning/avslutning mellan inlägg. Variera språket; håll åsikten konsekvent.
- Undvik att upprepa politikerns eller nyhetens exakta ordval och slogans. Reagera med
  dina egna ord och din egen röst — sakinnehållet kan vara detsamma, men formuleringen
  ska vara din.
"""

_NO_CREATE_POST_RULE_TWITTER = """\
- Skapa INTE egna inlägg (create_post). Reagera bara på det du ser: gilla, ogilla, kommentera, dela, följ eller gör inget.
"""

_NO_CREATE_POST_RULE_REDDIT = """\
- Skapa INTE egna inlägg (create_post). Reagera bara på det du ser: gilla, ogilla, kommentera, följ eller gör inget.
"""

_ALLOW_CREATE_POST_RULE = """\
- Du FÅR skapa egna inlägg (create_post) när du har något eget att säga — kort, i din röst, utan att kopiera andras budskap ordagrant.
"""


def population_action_rules(
    *,
    allow_create_post: bool = False,
    platform: OasisPlatform = "twitter",
) -> str:
    if allow_create_post:
        post_rule = _ALLOW_CREATE_POST_RULE
    elif platform == "reddit":
        post_rule = _NO_CREATE_POST_RULE_REDDIT
    else:
        post_rule = _NO_CREATE_POST_RULE_TWITTER
    base = _POPULATION_ACTION_RULES_BASE.strip()
    marker = "ÅTGÄRDER (viktigt):\n"
    if marker in base:
        head, rest = base.split(marker, 1)
        return f"{head}{marker}{post_rule.strip()}\n{rest}"
    return f"{base}\n{post_rule.strip()}"


# Back-compat alias for tests / callers that expect the default (no create_post).
_POPULATION_ACTION_RULES = population_action_rules(allow_create_post=False)


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
        "Du deltar inte i diskussioner, gillar inte, ogillar inte andras inlägg och svarar inte."
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


def build_user_char(
    member: PopulationMember,
    *,
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
    lines.append(
        "Du är en vanlig svensk person på en social medietjänst — inte debattör, "
        "assistent eller balanserad analytiker. "
        "Reagera autentiskt på politiska budskap utifrån din bakgrund."
    )
    lines.append(
        population_action_rules(
            allow_create_post=allow_create_post,
            platform=platform,
        )
    )
    tool_rules = population_tool_rules(oasis_options or OasisRunOptions())
    if tool_rules:
        lines.append(tool_rules)
    return "\n".join(lines)


def members_to_profiles(
    members: list[PopulationMember],
    *,
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
            )
        )
    return out


def build_run_profiles(
    members: list[PopulationMember],
    ticks: list[Tick],
    *,
    area_blocks: dict[str, str] | None = None,
    allow_create_post: bool = False,
    platform: OasisPlatform = "twitter",
    oasis_options: OasisRunOptions | None = None,
) -> tuple[list[OasisAgentProfile], dict[str, int]]:
    """Injectors first (no LLM), then the full population — no agent cap."""
    injectors = injectors_from_ticks(ticks)
    population = members_to_profiles(
        members,
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
        rows.append(
            {
                "username": profile.username,
                "realname": profile.member_name,
                "bio": profile.description,
                "persona": profile.user_char,
                "age": profile.age,
                "gender": oasis_gender_from_kon(profile.kön),
                "mbti": "ISFJ",
                "country": "Sweden",
            }
        )
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
