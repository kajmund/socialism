"""Global SSR tone/style label vocabulary (shared across anchor sets)."""

from __future__ import annotations

import re
from typing import Literal, TypedDict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database.models import (
    SsrAnchorCalibrationItem,
    SsrAnchorPoolItem,
    SsrAnchorSet,
    SsrLabelVocabulary,
)
from app.serializers import utcnow

LabelKind = Literal["tone", "style"]
LabelLocale = Literal["sv", "en"]

_KINDS: tuple[LabelKind, ...] = ("tone", "style")
_LOCALES: tuple[LabelLocale, ...] = ("sv", "en")

_TRANSLIT = str.maketrans(
    {
        "å": "a",
        "ä": "a",
        "ö": "o",
        "Å": "a",
        "Ä": "a",
        "Ö": "o",
        "é": "e",
        "É": "e",
        "ü": "u",
        "Ü": "u",
    }
)


class LabelEntry(TypedDict):
    key: str
    label: str


class LabelVocabularyError(RuntimeError):
    """Raised when vocabulary operations fail validation."""


DEFAULT_VOCABULARIES: dict[tuple[LabelKind, LabelLocale], list[LabelEntry]] = {
    ("tone", "sv"): [
        {"key": "strongly_negative", "label": "Starkt negativ"},
        {"key": "somewhat_negative", "label": "Något negativ"},
        {"key": "neutral", "label": "Neutral"},
        {"key": "somewhat_positive", "label": "Något positiv"},
        {"key": "strongly_positive", "label": "Starkt positiv"},
    ],
    ("tone", "en"): [
        {"key": "strongly_negative", "label": "Strongly negative"},
        {"key": "somewhat_negative", "label": "Somewhat negative"},
        {"key": "neutral", "label": "Neutral"},
        {"key": "somewhat_positive", "label": "Somewhat positive"},
        {"key": "strongly_positive", "label": "Strongly positive"},
    ],
    ("style", "sv"): [
        {"key": "sarcastic_concrete", "label": "Sarkastisk + konkret kritik"},
        {"key": "resigned_metaphor", "label": "Uppgiven + vardagsmetafor"},
        {"key": "facts_authority", "label": "Fakta + yrkesauktoritet"},
        {"key": "personal_heartfelt", "label": "Personlig + hjärtlig berättelse"},
        {"key": "optimistic_solution", "label": "Optimistisk / lösningsfokuserad"},
        {"key": "provocative_confrontational", "label": "Provocerande / konfronterande"},
    ],
    ("style", "en"): [
        {"key": "sarcastic_concrete", "label": "Sarkastisk + konkret kritik"},
        {"key": "resigned_metaphor", "label": "Uppgiven + vardagsmetafor"},
        {"key": "facts_authority", "label": "Fakta + yrkesauktoritet"},
        {"key": "personal_heartfelt", "label": "Personlig + hjärtlig berättelse"},
        {"key": "optimistic_solution", "label": "Optimistisk / lösningsfokuserad"},
        {"key": "provocative_confrontational", "label": "Provocerande / konfronterande"},
    ],
}


def _normalize_entries(raw: object) -> list[LabelEntry]:
    if not isinstance(raw, list):
        raise LabelVocabularyError("Vocabulary entries must be a list")
    out: list[LabelEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            raise LabelVocabularyError("Vocabulary entry must be an object")
        key = str(item.get("key", "")).strip()
        label = str(item.get("label", "")).strip()
        if not key or not label:
            raise LabelVocabularyError("Vocabulary entry requires non-empty key and label")
        out.append({"key": key, "label": label})
    return out


def slugify_label_key(label: str, existing: set[str]) -> str:
    base = label.translate(_TRANSLIT).lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    if not base:
        base = "label"
    key = base
    n = 2
    while key in existing:
        key = f"{base}_{n}"
        n += 1
    return key


async def ensure_vocabularies_seeded(session: AsyncSession) -> int:
    """Insert default vocabularies for any missing (kind, locale) pairs."""
    created = 0
    now = utcnow()
    for kind in _KINDS:
        for locale in _LOCALES:
            row = await session.get(SsrLabelVocabulary, {"kind": kind, "locale": locale})
            if row is not None:
                continue
            entries = [dict(e) for e in DEFAULT_VOCABULARIES[(kind, locale)]]
            session.add(
                SsrLabelVocabulary(
                    kind=kind,
                    locale=locale,
                    entries=entries,
                    updated_at=now,
                )
            )
            created += 1
    if created:
        await session.commit()
    return created


async def _require_row(
    session: AsyncSession,
    kind: LabelKind,
    locale: LabelLocale,
) -> SsrLabelVocabulary:
    row = await session.get(SsrLabelVocabulary, {"kind": kind, "locale": locale})
    if row is None:
        raise LabelVocabularyError(f"No vocabulary for kind={kind!r} locale={locale!r}")
    return row


async def get_vocabulary(
    session: AsyncSession,
    kind: LabelKind,
    locale: LabelLocale,
) -> list[LabelEntry]:
    row = await _require_row(session, kind, locale)
    return _normalize_entries(row.entries)


async def list_vocabularies(
    session: AsyncSession,
    *,
    kind: LabelKind | None = None,
    locale: LabelLocale | None = None,
) -> list[SsrLabelVocabulary]:
    stmt = select(SsrLabelVocabulary).order_by(
        SsrLabelVocabulary.kind.asc(),
        SsrLabelVocabulary.locale.asc(),
    )
    if kind is not None:
        stmt = stmt.where(SsrLabelVocabulary.kind == kind)
    if locale is not None:
        stmt = stmt.where(SsrLabelVocabulary.locale == locale)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _sets_for_kind_locale(
    session: AsyncSession,
    kind: LabelKind,
    locale: LabelLocale,
) -> list[SsrAnchorSet]:
    stmt = select(SsrAnchorSet).where(
        SsrAnchorSet.kind == kind,
        SsrAnchorSet.locale == locale,
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _label_for_key(entries: list[LabelEntry], key: str) -> str:
    for entry in entries:
        if entry["key"] == key:
            return entry["label"]
    raise LabelVocabularyError(f"Unknown vocabulary key {key!r}")


async def label_usage_count(
    session: AsyncSession,
    kind: LabelKind,
    locale: LabelLocale,
    label: str,
) -> int:
    """Count pool + calibration rows using this display label for kind+locale sets."""
    sets = await _sets_for_kind_locale(session, kind, locale)
    if not sets:
        return 0
    set_ids = [s.id for s in sets]
    pool_stmt = select(SsrAnchorPoolItem).where(
        SsrAnchorPoolItem.anchor_set_id.in_(set_ids),
        SsrAnchorPoolItem.label == label,
    )
    calib_stmt = select(SsrAnchorCalibrationItem).where(
        SsrAnchorCalibrationItem.anchor_set_id.in_(set_ids),
        SsrAnchorCalibrationItem.human_label == label,
    )
    pool_n = len(list((await session.execute(pool_stmt)).scalars().all()))
    calib_n = len(list((await session.execute(calib_stmt)).scalars().all()))
    return pool_n + calib_n


async def usage_by_key(
    session: AsyncSession,
    kind: LabelKind,
    locale: LabelLocale,
) -> dict[str, int]:
    entries = await get_vocabulary(session, kind, locale)
    out: dict[str, int] = {}
    for entry in entries:
        out[entry["key"]] = await label_usage_count(session, kind, locale, entry["label"])
    return out


def _rewrite_labels_list(labels: list, old_label: str, new_label: str) -> tuple[list[str], bool]:
    next_labels = [new_label if str(x) == old_label else str(x) for x in labels]
    return next_labels, next_labels != [str(x) for x in labels]


async def rename_label(
    session: AsyncSession,
    kind: LabelKind,
    locale: LabelLocale,
    key: str,
    new_label: str,
) -> list[LabelEntry]:
    new_label = new_label.strip()
    if not new_label:
        raise LabelVocabularyError("new_label must be non-empty")

    row = await _require_row(session, kind, locale)
    entries = _normalize_entries(row.entries)
    old_label = _label_for_key(entries, key)
    if old_label == new_label:
        return entries

    for entry in entries:
        if entry["key"] != key and entry["label"] == new_label:
            raise LabelVocabularyError(f"Label {new_label!r} already exists in vocabulary")

    for entry in entries:
        if entry["key"] == key:
            entry["label"] = new_label

    row.entries = [dict(e) for e in entries]
    flag_modified(row, "entries")
    row.updated_at = utcnow()

    sets = await _sets_for_kind_locale(session, kind, locale)
    set_ids = [s.id for s in sets]
    for anchor in sets:
        next_labels, changed = _rewrite_labels_list(list(anchor.labels or []), old_label, new_label)
        if not changed:
            continue
        anchor.labels = next_labels
        flag_modified(anchor, "labels")
        anchor.updated_at = utcnow()
        if anchor.status == "published":
            anchor.pool_revision = int(anchor.pool_revision or 0) + 1

    if set_ids:
        pool_stmt = select(SsrAnchorPoolItem).where(
            SsrAnchorPoolItem.anchor_set_id.in_(set_ids),
            SsrAnchorPoolItem.label == old_label,
        )
        for item in (await session.execute(pool_stmt)).scalars().all():
            item.label = new_label

        calib_stmt = select(SsrAnchorCalibrationItem).where(
            SsrAnchorCalibrationItem.anchor_set_id.in_(set_ids),
            SsrAnchorCalibrationItem.human_label == old_label,
        )
        for item in (await session.execute(calib_stmt)).scalars().all():
            item.human_label = new_label

    await session.commit()
    return entries


async def add_label(
    session: AsyncSession,
    kind: LabelKind,
    locale: LabelLocale,
    label: str,
) -> list[LabelEntry]:
    label = label.strip()
    if not label:
        raise LabelVocabularyError("label must be non-empty")

    row = await _require_row(session, kind, locale)
    entries = _normalize_entries(row.entries)
    if any(e["label"] == label for e in entries):
        raise LabelVocabularyError(f"Label {label!r} already exists in vocabulary")

    key = slugify_label_key(label, {e["key"] for e in entries})
    entries.append({"key": key, "label": label})
    row.entries = [dict(e) for e in entries]
    flag_modified(row, "entries")
    row.updated_at = utcnow()

    # Keep draft sets in sync; published sets keep their own label lists.
    for anchor in await _sets_for_kind_locale(session, kind, locale):
        if anchor.status != "draft":
            continue
        labels = [str(x) for x in (anchor.labels or [])]
        statements = [str(x) for x in (anchor.statements or [])]
        if label in labels:
            continue
        labels.append(label)
        while len(statements) < len(labels):
            statements.append("")
        anchor.labels = labels
        anchor.statements = statements
        flag_modified(anchor, "labels")
        flag_modified(anchor, "statements")
        anchor.updated_at = utcnow()

    await session.commit()
    return entries


async def remove_label(
    session: AsyncSession,
    kind: LabelKind,
    locale: LabelLocale,
    key: str,
) -> list[LabelEntry]:
    row = await _require_row(session, kind, locale)
    entries = _normalize_entries(row.entries)
    label = _label_for_key(entries, key)

    sets = await _sets_for_kind_locale(session, kind, locale)
    published_using = [
        s
        for s in sets
        if s.status == "published" and label in [str(x) for x in (s.labels or [])]
    ]
    if published_using:
        ids = ", ".join(str(s.id) for s in published_using)
        raise LabelVocabularyError(
            f"Cannot remove label {label!r}: used by published anchor set(s) {ids}"
        )

    usage = await label_usage_count(session, kind, locale, label)
    if usage > 0:
        raise LabelVocabularyError(
            f"Cannot remove label {label!r}: used by {usage} pool/calibration item(s)"
        )

    entries = [e for e in entries if e["key"] != key]
    if not entries:
        raise LabelVocabularyError("Cannot remove the last vocabulary entry")

    row.entries = [dict(e) for e in entries]
    flag_modified(row, "entries")
    row.updated_at = utcnow()

    for anchor in sets:
        if anchor.status != "draft":
            continue
        labels = [str(x) for x in (anchor.labels or [])]
        statements = [str(x) for x in (anchor.statements or [])]
        if label not in labels:
            continue
        idx = labels.index(label)
        del labels[idx]
        if idx < len(statements):
            del statements[idx]
        anchor.labels = labels
        anchor.statements = statements
        flag_modified(anchor, "labels")
        flag_modified(anchor, "statements")
        anchor.updated_at = utcnow()

    await session.commit()
    return entries
