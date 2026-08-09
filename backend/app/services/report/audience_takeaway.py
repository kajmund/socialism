"""Rule-based målgruppssammanfattning for snabbrapport (no LLM)."""

from __future__ import annotations

from collections import Counter

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification
from app.services.report.locale import ReportLocale
from app.services.report.metrics import pct
from app.services.report.persona_bio import (
    SUMMARY_SEGMENT_KEYS,
    build_agent_bio_by_index,
    parse_bio_age,
    segment_value,
)
from app.services.report.segment_ssr import SegmentToneRow, build_segment_tone_rows

_POSITIVE_STRONG = 0.40
_POSITIVE_WEAK = 0.28
_CRITICAL_HIGH = 0.42
_GENDER_GAP = 0.08


def _usable(rows: list[SegmentToneRow]) -> list[SegmentToneRow]:
    return [r for r in rows if not r.too_few]


def short_bundle_arm_label(bundle: RunBundle) -> str:
    label = bundle.label.strip()
    if "—" in label:
        tail = label.rsplit("—", 1)[-1].strip()
        if tail:
            return tail
    if bundle.variant_id:
        vid = bundle.variant_id.strip()
        if len(vid) == 1:
            return f"Version {vid.upper()}"
        return vid
    return label or "Budskapet"


def _normalize_gender(label: str) -> str:
    low = label.casefold()
    if low in {"kvinna", "woman", "female"}:
        return "kvinna"
    if low in {"man", "male"}:
        return "man"
    return low


def _rich_segment_label(
    row: SegmentToneRow,
    agent_bio: dict[int, dict[str, str]],
    *,
    locale: ReportLocale,
) -> str:
    """Combine yrke, livssituation and age band for the strongest segment."""
    bios = [agent_bio[uid] for uid in row.agent_ids if uid in agent_bio]
    if not bios:
        return row.label.casefold() if locale == "sv" else row.label.lower()

    yrke = Counter(segment_value(b, "yrke") for b in bios if segment_value(b, "yrke"))
    liv = Counter(
        segment_value(b, "livssituation") for b in bios if segment_value(b, "livssituation")
    )
    ages = [parse_bio_age(b) for b in bios]
    ages = [a for a in ages if a is not None]

    parts: list[str] = []
    if row.dimension == "yrke":
        parts.append(row.label.casefold() if locale == "sv" else row.label.lower())
        if liv:
            parts.append(liv.most_common(1)[0][0].casefold())
    elif row.dimension == "livssituation":
        if yrke:
            parts.append(yrke.most_common(1)[0][0].casefold())
        parts.append(row.label.casefold() if locale == "sv" else row.label.lower())
    else:
        if yrke:
            parts.append(yrke.most_common(1)[0][0].casefold())
        if liv:
            parts.append(liv.most_common(1)[0][0].casefold())

    if ages:
        over = sum(1 for a in ages if a >= 40)
        under = len(ages) - over
        if over > under:
            parts.append("över 40" if locale == "sv" else "over 40")
        elif under > over:
            parts.append("under 40" if locale == "sv" else "under 40")

    if not parts:
        return row.label.casefold() if locale == "sv" else row.label.lower()
    return ", ".join(parts)


def _pick_worst_livssituation(rows: list[SegmentToneRow]) -> SegmentToneRow | None:
    candidates = _usable([r for r in rows if r.dimension == "livssituation"])
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda r: (r.positive_share - r.critical_share, r.positive_share),
    )
    worst = ranked[0]
    if worst.positive_share <= _POSITIVE_WEAK or worst.critical_share >= _CRITICAL_HIGH:
        return worst
    return None


def _pick_best_highlight(
    rows: list[SegmentToneRow],
    *,
    worst: SegmentToneRow | None = None,
) -> SegmentToneRow | None:
    candidates = _usable([r for r in rows if r.dimension in {"livssituation", "yrke"}])
    if not candidates:
        return None
    ranked = sorted(
        candidates,
        key=lambda r: (r.positive_share - r.critical_share, r.positive_share),
        reverse=True,
    )
    best = ranked[0]
    if best.positive_share >= _POSITIVE_STRONG:
        return best
    if worst and worst.label != best.label:
        gap = best.positive_share - worst.positive_share
        if gap >= 0.12 and best.positive_share >= _POSITIVE_WEAK:
            return best
    return None


def _gender_sentence(rows: list[SegmentToneRow], *, locale: ReportLocale) -> str | None:
    by_gender: dict[str, SegmentToneRow] = {}
    for row in _usable([r for r in rows if r.dimension == "kön"]):
        key = _normalize_gender(row.label)
        if key in {"kvinna", "man"}:
            by_gender[key] = row
    if "kvinna" not in by_gender or "man" not in by_gender:
        return None
    f = by_gender["kvinna"]
    m = by_gender["man"]
    diff = f.positive_share - m.positive_share
    if abs(diff) < _GENDER_GAP:
        if locale == "en":
            return (
                f"Women and men responded similarly "
                f"({pct(f.positive_share)} vs {pct(m.positive_share)} positive tone)."
            )
        return (
            f"Kvinnor och män reagerade liknande "
            f"({pct(f.positive_share)} vs {pct(m.positive_share)} positiv ton)."
        )
    if diff > 0:
        if locale == "en":
            return (
                f"Women were more positive ({pct(f.positive_share)}) "
                f"than men ({pct(m.positive_share)})."
            )
        return (
            f"Kvinnor var mer positiva ({pct(f.positive_share)}) "
            f"än män ({pct(m.positive_share)})."
        )
    if locale == "en":
        return (
            f"Men were more positive ({pct(m.positive_share)}) "
            f"than women ({pct(f.positive_share)})."
        )
    return (
        f"Män var mer positiva ({pct(m.positive_share)}) "
        f"än kvinnor ({pct(f.positive_share)})."
    )


def build_bundle_takeaway(
    bundle: RunBundle,
    classification: BundleClassification,
    *,
    locale: ReportLocale = "sv",
) -> str | None:
    rows = build_segment_tone_rows(
        bundle,
        classification,
        locale=locale,
        segment_keys=SUMMARY_SEGMENT_KEYS,
    )
    agent_bio = build_agent_bio_by_index(bundle)
    worst = _pick_worst_livssituation(rows)
    best = _pick_best_highlight(rows, worst=worst)
    if not worst and not best:
        return None

    name = short_bundle_arm_label(bundle)
    parts: list[str] = []

    if locale == "en":
        if worst:
            parts.append(
                f"did not land as well with {worst.label.casefold()} "
                f"({pct(worst.positive_share)} positive tone)"
            )
        if best:
            rich = _rich_segment_label(best, agent_bio, locale=locale)
            parts.append(
                f"landed better with {rich} ({pct(best.positive_share)} positive tone)"
            )
        if not parts:
            return None
        if len(parts) == 2:
            body = f"{parts[0]}, but {parts[1]}"
        else:
            body = parts[0]
        return f"{name}: The message {body}."
    else:
        if worst:
            parts.append(
                f"gick sämre hem hos {worst.label.casefold()} "
                f"({pct(worst.positive_share)} positiv ton)"
            )
        if best:
            rich = _rich_segment_label(best, agent_bio, locale=locale)
            parts.append(
                f"landade bättre hos {rich} ({pct(best.positive_share)} positiv ton)"
            )
        if not parts:
            return None
        if len(parts) == 2:
            body = f"{parts[0]}, men {parts[1]}"
        else:
            body = parts[0]
        return f"{name}: Budskapet {body}."


def build_audience_takeaways(
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    *,
    locale: ReportLocale = "sv",
) -> list[str]:
    paragraphs: list[str] = []
    for bundle, clf in zip(bundles, classifications, strict=True):
        line = build_bundle_takeaway(bundle, clf, locale=locale)
        if line:
            paragraphs.append(line)
        gender_rows = build_segment_tone_rows(
            bundle,
            clf,
            locale=locale,
            segment_keys=("kön",),
        )
        gender_line = _gender_sentence(gender_rows, locale=locale)
        if gender_line:
            if len(bundles) > 1:
                paragraphs.append(f"{short_bundle_arm_label(bundle)}: {gender_line}")
            else:
                paragraphs.append(gender_line)

    return paragraphs
