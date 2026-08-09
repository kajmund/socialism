"""Persona bio fields for report segmentation (SSR, interviews, målgrupp)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.schemas.domain import EditablePersona
from app.serializers import profile_from_dict

if TYPE_CHECKING:
    from app.services.report.bundles import RunBundle

# Catalog-aligned profile keys used for deterministic segment bucketing.
BIO_KEYS: tuple[str, ...] = (
    "kön",
    "ort",
    "yrke",
    "utbildning",
    "livssituation",
    "lutning",
    "parti",
    "valdeltagande",
    "sakfragor",
    "fortroende",
    "ton",
    "sprak",
    "medievanor",
)

# Tier-1 segments for snabbrapport målgruppsanalys (later cards).
PRIMARY_SEGMENT_KEYS: tuple[str, ...] = ("livssituation", "ort", "lutning")

# Extended keys for rule-based audience takeaway (snabbrapport summary).
SUMMARY_SEGMENT_KEYS: tuple[str, ...] = ("livssituation", "yrke", "kön", "age_band")


def normalize_bio_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text == "—":
        return ""
    return text


def bio_fields_from_profile(
    profile: EditablePersona,
    *,
    district: str,
    age: int | str,
) -> dict[str, str]:
    """Flatten persona profile to segment lookup values."""
    ort = normalize_bio_value(profile.ort) or normalize_bio_value(district)
    out: dict[str, str] = {
        "ort": ort,
        "age": normalize_bio_value(age) or normalize_bio_value(profile.age),
    }
    for key in BIO_KEYS:
        if key == "ort":
            continue
        out[key] = normalize_bio_value(getattr(profile, key, ""))
    return out


def persona_record_from_member(
    *,
    persona_id: str | None,
    name: str,
    age: int,
    occ: str,
    district: str,
    trait: str,
    profile_data: dict[str, Any] | None,
) -> dict[str, Any]:
    profile = profile_from_dict(profile_data, name)
    bio = bio_fields_from_profile(profile, district=district, age=age)
    if not bio.get("yrke"):
        bio["yrke"] = normalize_bio_value(occ)
    return {
        "persona_id": persona_id,
        "name": name,
        "age": age,
        "occ": occ,
        "district": district,
        "trait": trait,
        "bio": bio,
    }


def persona_bio_by_id(personas: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for row in personas:
        pid = str(row.get("persona_id") or "").strip()
        bio = row.get("bio")
        if pid and isinstance(bio, dict):
            out[pid] = {k: str(v) for k, v in bio.items() if v}
    return out


def build_agent_bio_by_index(bundle: RunBundle) -> dict[int, dict[str, str]]:
    """Map OASIS agent index (post/comment user_id) → bio fields."""
    by_persona = persona_bio_by_id(bundle.personas)
    by_name: dict[str, dict[str, str]] = {}
    for row in bundle.personas:
        bio = row.get("bio")
        if isinstance(bio, dict):
            name = str(row.get("name") or "").strip().casefold()
            if name:
                by_name[name] = bio

    out: dict[int, dict[str, str]] = {}
    for agent in bundle.agents:
        if str(agent.get("role") or "") == "injector":
            continue
        try:
            idx = int(agent.get("index"))
        except (TypeError, ValueError):
            continue
        pid = str(agent.get("persona_id") or "").strip()
        if pid and pid in by_persona:
            out[idx] = by_persona[pid]
            continue
        member = str(agent.get("member_name") or "").strip().casefold()
        if member and member in by_name:
            out[idx] = by_name[member]
    return out


def segment_value(bio: dict[str, str], key: str) -> str:
    return normalize_bio_value(bio.get(key))


def parse_bio_age(bio: dict[str, str]) -> int | None:
    raw = normalize_bio_value(bio.get("age"))
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def age_band_label(bio: dict[str, str], *, locale: str = "sv") -> str:
    age = parse_bio_age(bio)
    if age is None:
        return ""
    if locale == "en":
        return "Over 40" if age >= 40 else "Under 40"
    return "Över 40" if age >= 40 else "Under 40"


def segment_key_value(bio: dict[str, str], key: str, *, locale: str = "sv") -> str:
    if key == "age_band":
        return age_band_label(bio, locale=locale)
    return segment_value(bio, key)
