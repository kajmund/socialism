"""Achieved population fingerprint, target QA, and slot-key inference."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.schemas.domain import DistGroup, DistRow, GeneratedPersonaOut, GenerationCandidate

if TYPE_CHECKING:
    from app.database.models import PopulationMember

QA_THRESHOLD_PP = 5


@dataclass(frozen=True)
class MemberSlots:
    age_bucket: str | None
    lean_key: str | None
    district_key: str | None


class _SlotSource(Protocol):
    age: int
    age_bucket: str | None
    lean_key: str | None
    district_key: str | None
    district: str


def _norm_token(value: str) -> str:
    return (
        value.lower()
        .replace("å", "a")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace(" ", "_")
        .replace("-", "_")
    )


def infer_age_bucket(age: int) -> str:
    if age <= 34:
        return "ung"
    if age >= 60:
        return "aldre"
    return "medel"


def _row_keys(rows: list[DistRow] | None) -> dict[str, DistRow]:
    if not rows:
        return {}
    return {row.k: row for row in rows}


def _match_row_key(
    value: str,
    rows: list[DistRow] | None,
    *,
    fallback_key: str,
) -> str:
    if not value.strip():
        return fallback_key
    if not rows:
        return fallback_key
    token = _norm_token(value)
    for row in rows:
        if _norm_token(row.k) == token or _norm_token(row.l) == token:
            return row.k
    for row in rows:
        row_token = _norm_token(row.l)
        if token in row_token or row_token in token:
            return row.k
    return fallback_key


def infer_district_key(district_label: str, group: DistGroup | dict | None) -> str:
    rows = _rows_from_group(group)
    return _match_row_key(district_label, rows, fallback_key="centrum")


def infer_lean_key(lutning_label: str, group: DistGroup | dict | None) -> str:
    rows = _rows_from_group(group)
    return _match_row_key(lutning_label, rows, fallback_key="mitt")


def infer_lean_key_optional(
    lutning_label: str,
    group: DistGroup | dict | None,
) -> str | None:
    """Return None when lutning is unknown — do not silently default to mitt."""
    if not lutning_label.strip():
        return None
    return infer_lean_key(lutning_label, group)


def lutning_from_profile(profile: dict | None) -> str:
    if not profile:
        return ""
    return str(profile.get("lutning") or profile.get("leaning") or "")


def _rows_from_group(group: DistGroup | dict | None) -> list[DistRow] | None:
    if group is None:
        return None
    if isinstance(group, DistGroup):
        return group.rows
    raw_rows = group.get("rows")
    if not isinstance(raw_rows, list):
        return None
    rows: list[DistRow] = []
    for item in raw_rows:
        if isinstance(item, DistRow):
            rows.append(item)
        elif isinstance(item, dict) and "k" in item:
            rows.append(DistRow.model_validate(item))
    return rows


def _lean_bucket(row: DistRow) -> str:
    key = _norm_token(row.k)
    label = _norm_token(row.l)
    if key in {"vanster", "mvanster"} or "vanster" in label:
        return "left"
    if key in {"mhoger", "hoger"} or "hoger" in label:
        return "right"
    if key == "mitt" or label == "mitt":
        return "mid"
    return "mid"


def _is_centrum_row(row: DistRow) -> bool:
    key = _norm_token(row.k)
    label = _norm_token(row.l)
    return key == "centrum" or label == "centrum"


def _is_ovriga_row(row: DistRow) -> bool:
    key = _norm_token(row.k)
    label = _norm_token(row.l)
    return key in {"ovriga", "ovrig"} or label in {"ovriga", "ovrig"}


def slots_from_persona(persona: GeneratedPersonaOut) -> MemberSlots:
    age_bucket = persona.age_bucket or infer_age_bucket(persona.age)
    lean_key = persona.lean or "mitt"
    district_key = persona.district_key or "centrum"
    return MemberSlots(
        age_bucket=age_bucket,
        lean_key=lean_key,
        district_key=district_key,
    )


def slots_from_member(member: PopulationMember | _SlotSource) -> MemberSlots:
    age_bucket = member.age_bucket or infer_age_bucket(member.age)
    lean_key = member.lean_key
    district_key = member.district_key or infer_district_key(
        member.district,
        None,
    )
    return MemberSlots(
        age_bucket=age_bucket,
        lean_key=lean_key,
        district_key=district_key,
    )


def infer_slots_from_profile(
    *,
    age: int,
    district: str,
    profile: dict | None,
    dist: dict[str, DistGroup | dict],
) -> MemberSlots:
    lutning = lutning_from_profile(profile)
    ort = district
    if profile:
        ort = str(profile.get("ort") or profile.get("district") or district)
    return MemberSlots(
        age_bucket=infer_age_bucket(age),
        lean_key=infer_lean_key_optional(lutning, dist.get("leaning")),
        district_key=infer_district_key(ort, dist.get("district")),
    )


def fingerprint_from_dist(dist: dict[str, DistGroup | dict]) -> list[list[int]]:
    """Target distribution summary from recipe sliders (unchanged semantics)."""
    age_group = dist.get("age")
    age_rows = _rows_from_group(age_group)
    age = [r.v for r in age_rows] if age_rows else [33, 34, 33]

    lean_rows = _rows_from_group(dist.get("leaning")) or []
    left = sum(r.v for r in lean_rows if _lean_bucket(r) == "left")
    mid = sum(r.v for r in lean_rows if _lean_bucket(r) == "mid")
    right = sum(r.v for r in lean_rows if _lean_bucket(r) == "right")
    lean = [left, mid, right]

    d_rows = _rows_from_group(dist.get("district")) or []
    centrum = sum(r.v for r in d_rows if _is_centrum_row(r))
    ovriga = sum(r.v for r in d_rows if _is_ovriga_row(r))
    middle = max(0, 100 - centrum - ovriga)
    return [age, lean, [centrum, middle, ovriga]]


def fingerprint_from_slot_rows(
    slot_rows: list[MemberSlots | dict[str, str | None]],
    dist: dict[str, DistGroup | dict],
) -> list[list[int]]:
    if not slot_rows:
        age_rows = _rows_from_group(dist.get("age")) or []
        return [
            [0 for _ in age_rows] or [0, 0, 0],
            [0, 0, 0],
            [0, 0, 0],
        ]

    normalized: list[MemberSlots] = []
    for row in slot_rows:
        if isinstance(row, MemberSlots):
            normalized.append(row)
        else:
            normalized.append(
                MemberSlots(
                    age_bucket=row.get("age_bucket"),
                    lean_key=row.get("lean_key"),
                    district_key=row.get("district_key"),
                )
            )

    total = len(normalized)

    age_rows = _rows_from_group(dist.get("age")) or []
    age_counts = {row.k: 0 for row in age_rows}
    for slots in normalized:
        bucket = slots.age_bucket or infer_age_bucket(35)
        if bucket not in age_counts and age_counts:
            bucket = next(iter(age_counts))
        age_counts[bucket] = age_counts.get(bucket, 0) + 1
    age = [
        round(100 * age_counts.get(row.k, 0) / total)
        for row in age_rows
    ] or [33, 34, 33]

    lean_rows = _rows_from_group(dist.get("leaning")) or []
    lean_row_counts = {row.k: 0 for row in lean_rows}
    lean_known = [slots for slots in normalized if slots.lean_key]
    lean_total = len(lean_known)
    for slots in lean_known:
        key = slots.lean_key or "mitt"
        if key not in lean_row_counts and lean_row_counts:
            key = next(iter(lean_row_counts))
        lean_row_counts[key] = lean_row_counts.get(key, 0) + 1

    if lean_total == 0:
        lean = [0, 0, 0]
    else:
        left = mid = right = 0
        for row in lean_rows:
            count = lean_row_counts.get(row.k, 0)
            bucket = _lean_bucket(row)
            if bucket == "left":
                left += count
            elif bucket == "right":
                right += count
            else:
                mid += count
        lean = [
            round(100 * left / lean_total),
            round(100 * mid / lean_total),
            round(100 * right / lean_total),
        ]

    district_rows = _rows_from_group(dist.get("district")) or []
    district_counts = {row.k: 0 for row in district_rows}
    for slots in normalized:
        key = slots.district_key or "centrum"
        if key not in district_counts and district_counts:
            key = next(iter(district_counts))
        district_counts[key] = district_counts.get(key, 0) + 1

    centrum = ovriga = 0
    for row in district_rows:
        count = district_counts.get(row.k, 0)
        if _is_centrum_row(row):
            centrum += count
        elif _is_ovriga_row(row):
            ovriga += count
    middle_count = max(0, total - centrum - ovriga)
    district = [
        round(100 * centrum / total),
        round(100 * middle_count / total),
        round(100 * ovriga / total),
    ]
    return [age, lean, district]


def fingerprint_from_candidates(
    candidates: list[GenerationCandidate],
    dist: dict[str, DistGroup | dict],
) -> list[list[int]]:
    slots = [slots_from_persona(c.persona) for c in candidates if c.persona is not None]
    return fingerprint_from_slot_rows(slots, dist)


def fingerprint_from_members(
    members: list[PopulationMember | _SlotSource],
    dist: dict[str, DistGroup | dict],
) -> list[list[int]]:
    slots = [slots_from_member(member) for member in members]
    return fingerprint_from_slot_rows(slots, dist)


@dataclass(frozen=True)
class _CandidateSlots:
    age: int
    age_bucket: str | None
    lean_key: str | None
    district_key: str | None
    district: str


def compare_target_vs_candidates(
    dist: dict[str, DistGroup | dict],
    candidates: list[GenerationCandidate],
) -> list[str]:
    pseudo_members = []
    for candidate in candidates:
        if candidate.persona is None:
            continue
        persona = candidate.persona
        pseudo_members.append(
            _CandidateSlots(
                age=persona.age,
                age_bucket=persona.age_bucket or infer_age_bucket(persona.age),
                lean_key=persona.lean or "mitt",
                district_key=persona.district_key or "centrum",
                district=persona.district,
            )
        )
    return compare_target_vs_achieved(dist, pseudo_members)


def compare_target_vs_achieved(
    dist: dict[str, DistGroup | dict],
    members: list[PopulationMember | _SlotSource],
    *,
    fingerprint_inferred: bool = False,
) -> list[str]:
    if not members:
        return []

    total = len(members)
    warnings: list[str] = []
    checks = (
        ("age", "age_bucket", "Ålder"),
        ("leaning", "lean_key", "Lutning"),
        ("district", "district_key", "Ort"),
    )
    lean_known = sum(1 for member in members if slots_from_member(member).lean_key)
    for group_key, slot_field, label in checks:
        if group_key == "leaning" and (
            fingerprint_inferred or lean_known < total
        ):
            continue
        rows = _rows_from_group(dist.get(group_key)) or []
        if not rows:
            continue
        counts = {row.k: 0 for row in rows}
        scoped_members = members
        scoped_total = total
        if group_key == "leaning":
            scoped_members = [
                member
                for member in members
                if slots_from_member(member).lean_key
            ]
            scoped_total = len(scoped_members)
            if scoped_total == 0:
                continue
        for member in scoped_members:
            slots = slots_from_member(member)
            value = getattr(slots, slot_field) or ""
            key = str(value)
            if key not in counts and counts:
                key = next(iter(counts))
            counts[key] = counts.get(key, 0) + 1
        for row in rows:
            target = row.v
            achieved = round(100 * counts.get(row.k, 0) / scoped_total)
            delta = abs(achieved - target)
            if delta > QA_THRESHOLD_PP:
                warnings.append(
                    f"{label}: {row.l} mål {target} %, utfall {achieved} % (Δ {delta} pp)"
                )
    return warnings


def dist_qa_rows(
    dist: dict[str, DistGroup | dict],
    members: list[PopulationMember | _SlotSource],
    *,
    fingerprint_inferred: bool = False,
) -> list[dict]:
    if not members:
        return []

    total = len(members)
    out: list[dict] = []
    checks = (
        ("age", "age_bucket"),
        ("leaning", "lean_key"),
        ("district", "district_key"),
    )
    lean_known = sum(1 for member in members if slots_from_member(member).lean_key)
    for group_key, slot_field in checks:
        if group_key == "leaning" and (
            fingerprint_inferred or lean_known < total
        ):
            continue
        group = dist.get(group_key)
        rows = _rows_from_group(group) or []
        if not rows:
            continue
        counts = {row.k: 0 for row in rows}
        scoped_members = members
        scoped_total = total
        if group_key == "leaning":
            scoped_members = [
                member
                for member in members
                if slots_from_member(member).lean_key
            ]
            scoped_total = len(scoped_members)
            if scoped_total == 0:
                continue
        for member in scoped_members:
            slots = slots_from_member(member)
            key = getattr(slots, slot_field) or ""
            if key not in counts and counts:
                key = next(iter(counts))
            counts[key] = counts.get(key, 0) + 1
        group_label = group.label if isinstance(group, DistGroup) else str(group.get("label", group_key))
        out.append(
            {
                "key": group_key,
                "label": group_label,
                "rows": [
                    {
                        "k": row.k,
                        "l": row.l,
                        "target_v": row.v,
                        "achieved_v": round(100 * counts.get(row.k, 0) / scoped_total),
                    }
                    for row in rows
                ],
            }
        )
    return out
