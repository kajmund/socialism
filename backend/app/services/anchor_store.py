"""SSR anchor library: seed defaults, resolve config → AnchorSet for reports."""

from __future__ import annotations

from typing import Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Configuration, SsrAnchorCalibrationItem, SsrAnchorSet
from app.services.report.locale import ReportLocale, normalize_locale
from app.services.ssr.anchors import (
    STYLE_ANCHORS_EN,
    STYLE_ANCHORS_SV,
    TONE_ANCHORS_EN,
    TONE_ANCHORS_SV,
    AnchorSet,
)

AnchorKind = Literal["tone", "style"]
AnchorLocale = Literal["sv", "en"]
AnchorStatus = Literal["draft", "published"]


class AnchorResolutionError(RuntimeError):
    """Raised when SSR anchor sets cannot be resolved for reports or config."""


class AnchorRef(TypedDict):
    tone: int
    style: int


class ResolvedReportAnchors(TypedDict):
    tone: AnchorSet
    style: AnchorSet
    tone_id: int
    tone_version: str
    style_id: int
    style_version: str


def row_to_anchor_set(row: SsrAnchorSet) -> AnchorSet:
    labels = tuple(str(x) for x in (row.labels or []))
    statements = tuple(str(x) for x in (row.statements or []))
    return AnchorSet(
        name=row.name,
        version=row.version,
        labels=labels,
        statements=statements,
    )


def default_anchor_sets_payload() -> list[dict]:
    """Seed rows mirroring app.services.ssr.anchors v1."""
    rows: list[dict] = []
    for anchor in (TONE_ANCHORS_SV, TONE_ANCHORS_EN, STYLE_ANCHORS_SV, STYLE_ANCHORS_EN):
        kind: AnchorKind = "tone" if anchor.name.startswith("tone_") else "style"
        locale: AnchorLocale = "en" if anchor.name.endswith("_en") else "sv"
        rows.append(
            {
                "name": anchor.name,
                "kind": kind,
                "locale": locale,
                "version": anchor.version,
                "labels": list(anchor.labels),
                "statements": list(anchor.statements),
                "status": "published",
            }
        )
    return rows


async def _published_by_kind_locale(
    session: AsyncSession,
) -> dict[tuple[AnchorKind, AnchorLocale], SsrAnchorSet]:
    stmt = select(SsrAnchorSet).where(SsrAnchorSet.status == "published")
    result = await session.execute(stmt)
    out: dict[tuple[AnchorKind, AnchorLocale], SsrAnchorSet] = {}
    for row in result.scalars().all():
        key = (row.kind, row.locale)  # type: ignore[arg-type]
        if key not in out:
            out[key] = row
    return out


async def ensure_default_anchor_sets(session: AsyncSession) -> int:
    """Seed v1 anchor sets from code constants if the library is empty."""
    count = await session.scalar(select(SsrAnchorSet.id).limit(1))
    if count is not None:
        return 0
    from app.serializers import utcnow

    now = utcnow()
    for payload in default_anchor_sets_payload():
        session.add(
            SsrAnchorSet(
                **payload,
                created_at=now,
                updated_at=now,
            )
        )
    await session.commit()
    return len(default_anchor_sets_payload())


async def default_anchor_refs(session: AsyncSession) -> dict[str, AnchorRef]:
    published = await _published_by_kind_locale(session)
    refs: dict[str, AnchorRef] = {}
    for loc in ("sv", "en"):
        tone = published.get(("tone", loc))
        style = published.get(("style", loc))
        if tone is None or style is None:
            raise AnchorResolutionError(
                f"Missing published SSR anchor sets for locale '{loc}'"
            )
        refs[loc] = {"tone": int(tone.id), "style": int(style.id)}
    return refs


async def backfill_configuration_anchor_sets(session: AsyncSession) -> int:
    """Ensure every configuration has sv/en anchor refs pointing at published sets."""
    refs = await default_anchor_refs(session)
    result = await session.execute(select(Configuration))
    changed = 0
    for row in result.scalars().all():
        current = dict(row.anchor_sets or {})
        if current.get("sv") and current.get("en"):
            continue
        row.anchor_sets = refs
        from app.serializers import utcnow

        row.updated_at = utcnow()
        changed += 1
    if changed:
        await session.commit()
    return changed


def configuration_anchor_sets_out(raw: dict | None) -> dict[str, dict[str, int]]:
    refs = dict(raw or {})
    sv = refs.get("sv") if isinstance(refs.get("sv"), dict) else {}
    en = refs.get("en") if isinstance(refs.get("en"), dict) else {}
    return {
        "sv": {"tone": int(sv.get("tone") or 0), "style": int(sv.get("style") or 0)},
        "en": {"tone": int(en.get("tone") or 0), "style": int(en.get("style") or 0)},
    }


async def get_anchor_set_row(session: AsyncSession, anchor_set_id: int) -> SsrAnchorSet | None:
    return await session.get(SsrAnchorSet, anchor_set_id)


async def require_anchor_set_row(session: AsyncSession, anchor_set_id: int) -> SsrAnchorSet:
    row = await get_anchor_set_row(session, anchor_set_id)
    if row is None:
        raise AnchorResolutionError(f"SSR anchor set {anchor_set_id} not found")
    return row


def _validate_anchor_row(row: SsrAnchorSet, *, kind: AnchorKind, locale: ReportLocale) -> None:
    if row.status != "published":
        raise AnchorResolutionError(
            f"SSR anchor set '{row.name}' (id={row.id}) is not published"
        )
    if row.kind != kind:
        raise AnchorResolutionError(
            f"SSR anchor set id={row.id} is kind={row.kind!r}, expected {kind!r}"
        )
    if row.locale != locale:
        raise AnchorResolutionError(
            f"SSR anchor set id={row.id} is locale={row.locale!r}, expected {locale!r}"
        )


async def validate_configuration_anchor_refs(
    session: AsyncSession,
    refs: dict[str, dict[str, int]],
) -> None:
    for loc in ("sv", "en"):
        block = refs.get(loc)
        if not isinstance(block, dict):
            raise ValueError(f"anchor_sets[{loc!r}] is required")
        for kind in ("tone", "style"):
            anchor_id = int(block.get(kind) or 0)
            if anchor_id <= 0:
                raise ValueError(f"anchor_sets[{loc!r}].{kind} must be a positive id")
            row = await require_anchor_set_row(session, anchor_id)
            _validate_anchor_row(row, kind=kind, locale=loc)  # type: ignore[arg-type]


async def resolve_anchor_set_for_config(
    session: AsyncSession,
    *,
    configuration: Configuration,
    locale: ReportLocale,
    kind: AnchorKind,
) -> tuple[SsrAnchorSet, AnchorSet]:
    loc = normalize_locale(locale)
    refs = dict(configuration.anchor_sets or {})
    block = refs.get(loc)
    if not block:
        raise AnchorResolutionError(
            f"Configuration '{configuration.name}' (id={configuration.id}) has no "
            f"anchor_sets[{loc!r}]"
        )
    anchor_id = int(block.get(kind) or 0)
    if anchor_id <= 0:
        raise AnchorResolutionError(
            f"Configuration '{configuration.name}' (id={configuration.id}) missing "
            f"{kind} anchor for locale {loc!r}"
        )
    row = await require_anchor_set_row(session, anchor_id)
    _validate_anchor_row(row, kind=kind, locale=loc)
    return row, row_to_anchor_set(row)


async def require_anchor_sets_for_language(
    session: AsyncSession,
    language: ReportLocale,
) -> ResolvedReportAnchors:
    """Resolve tone/style AnchorSets from the active configuration.

    Requires the active configuration's language to match ``language``.
    Never falls back to an inactive config of that language.
    """
    from app.services.prompt_catalog import ConfigurationLanguage
    from app.services.prompt_store import get_active_configuration

    lang: ConfigurationLanguage = "en" if language == "en" else "sv"
    row = await get_active_configuration(session)
    if row is None:
        raise AnchorResolutionError(
            "No active prompt configuration. Activate one under Konfigurationer."
        )
    if row.language != lang:
        raise AnchorResolutionError(
            f"Active configuration '{row.name}' (id={row.id}) is language "
            f"'{row.language}', but '{lang}' anchors were required. "
            f"Activate a {lang} configuration under Konfigurationer."
        )
    tone_row, tone_set = await resolve_anchor_set_for_config(
        session, configuration=row, locale=language, kind="tone"
    )
    style_row, style_set = await resolve_anchor_set_for_config(
        session, configuration=row, locale=language, kind="style"
    )
    return {
        "tone": tone_set,
        "style": style_set,
        "tone_id": int(tone_row.id),
        "tone_version": tone_row.version,
        "style_id": int(style_row.id),
        "style_version": style_row.version,
    }


def validate_anchor_payload(
    *,
    kind: AnchorKind,
    locale: AnchorLocale,
    labels: list[str],
    statements: list[str],
) -> None:
    if not labels or not statements:
        raise ValueError("labels and statements must be non-empty")
    if len(labels) != len(statements):
        raise ValueError("labels and statements must have the same length")
    if kind == "tone" and len(labels) != 5:
        raise ValueError("tone anchor sets must have exactly 5 labels")
    if kind == "style" and len(labels) != 6:
        raise ValueError("style anchor sets must have exactly 6 labels")
    if locale not in ("sv", "en"):
        raise ValueError("locale must be sv or en")


async def calibration_items(
    session: AsyncSession, anchor_set_id: int
) -> list[SsrAnchorCalibrationItem]:
    stmt = (
        select(SsrAnchorCalibrationItem)
        .where(SsrAnchorCalibrationItem.anchor_set_id == anchor_set_id)
        .order_by(SsrAnchorCalibrationItem.sort_order.asc(), SsrAnchorCalibrationItem.id.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


__all__ = [
    "AnchorKind",
    "AnchorLocale",
    "AnchorRef",
    "AnchorResolutionError",
    "AnchorStatus",
    "ResolvedReportAnchors",
    "backfill_configuration_anchor_sets",
    "calibration_items",
    "configuration_anchor_sets_out",
    "default_anchor_refs",
    "ensure_default_anchor_sets",
    "get_anchor_set_row",
    "require_anchor_set_row",
    "require_anchor_sets_for_language",
    "resolve_anchor_set_for_config",
    "row_to_anchor_set",
    "validate_anchor_payload",
    "validate_configuration_anchor_refs",
]
