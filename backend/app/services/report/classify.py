"""Topic packs + tone classification via LLM (no keyword/heuristic fallback)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.llm import complete_structured
from app.services.prompt_catalog import render_prompt
from app.services.report.bundles import RunBundle
from app.services.report.locale import (
    ReportLocale,
    meta_topics_fallback,
    other_topic_label,
    tone_labels,
)

ToneMode = Literal["llm"]

# Keep batches small — large structured prompts stall on DeepSeek.
_CLASSIFY_BATCH_SIZE = 8
_TEXT_CHARS = 200
# Cap LLM calls: sample highest-engagement texts (likes).
_MAX_CLASSIFY_TEXTS = 16

# Historical Swedish labels (tests / callers).
TONE_LABELS: tuple[str, ...] = tone_labels("sv")


@dataclass
class TopicPack:
    label: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class BundleClassification:
    topic_packs: list[TopicPack] = field(default_factory=list)
    topic_shares: dict[str, float] = field(default_factory=dict)
    tone_shares: dict[str, float] = field(default_factory=dict)
    tone_mode: ToneMode = "llm"


class _TopicPackModel(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    keywords: list[str] = Field(default_factory=list, max_length=16)


class _TopicPacksResponse(BaseModel):
    topics: list[_TopicPackModel] = Field(min_length=1, max_length=4)


class _TopicItem(BaseModel):
    index: int
    topic: str


class _TopicBatchResponse(BaseModel):
    items: list[_TopicItem]


class _ToneItem(BaseModel):
    index: int
    tone: str


class _ToneBatchResponse(BaseModel):
    items: list[_ToneItem]


def _item_likes(item: dict) -> int:
    for key in ("num_likes", "likes", "like_count"):
        v = item.get(key)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _texts_for_classify(bundle: RunBundle, *, limit: int = _MAX_CLASSIFY_TEXTS) -> list[str]:
    """Prefer higher-engagement posts/comments; cap count for LLM cost/latency."""
    scored: list[tuple[int, str]] = []
    for p in bundle.posts:
        c = p.get("content") or p.get("text") or ""
        if c:
            scored.append((_item_likes(p), str(c)))
    for c in bundle.comments:
        t = c.get("content") or c.get("text") or ""
        if t:
            scored.append((_item_likes(c), str(t)))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [text for _, text in scored[:limit]]


def _share_counts(labels: list[str], allowed: list[str]) -> dict[str, float]:
    counts: Counter[str] = Counter({lab: 0 for lab in allowed})
    for lab in labels:
        counts[lab if lab in counts else allowed[-1]] += 1
    total = sum(counts.values()) or 1
    return {lab: counts[lab] / total for lab in allowed}


async def derive_topic_packs(
    injection_texts: list[str],
    *,
    locale: ReportLocale = "sv",
    prompts: dict[str, str],
) -> list[TopicPack]:
    if not injection_texts:
        return []

    blob = "\n---\n".join(t[:800] for t in injection_texts[:8])
    system = render_prompt(prompts, "report.classify.topic_packs.system")
    user = (
        f"Injection texts:\n{blob}"
        if locale == "en"
        else f"Injektionstexter:\n{blob}"
    )
    result = await complete_structured(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        _TopicPacksResponse,
    )
    packs = [
        TopicPack(
            label=t.label.strip(),
            keywords=[k.strip().lower() for k in t.keywords if k.strip()],
        )
        for t in result.topics
        if t.label.strip()
    ]
    if not packs:
        raise RuntimeError("LLM returned no topic packs for injections")
    return packs


async def classify_topics(
    texts: list[str],
    packs: list[TopicPack],
    *,
    locale: ReportLocale = "sv",
    prompts: dict[str, str],
    batch_size: int = _CLASSIFY_BATCH_SIZE,
) -> dict[str, float]:
    other = other_topic_label(locale)
    allowed = [p.label for p in packs] + [other]
    if not texts:
        return {lab: 0.0 for lab in allowed}
    if not packs:
        return {other: 1.0}

    allowed_set = set(allowed)
    labels: list[str] = [""] * len(texts)
    pack_list = ", ".join(f"'{p.label}'" for p in packs)

    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        numbered = "\n".join(f"{i}. {t[:_TEXT_CHARS]}" for i, t in enumerate(chunk))
        system = render_prompt(
            prompts,
            "report.classify.topics.system",
            pack_list=pack_list,
            other=other,
        )
        result = await complete_structured(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": numbered},
            ],
            _TopicBatchResponse,
        )
        by_idx = {item.index: item.topic for item in result.items}
        for i in range(len(chunk)):
            raw = by_idx.get(i, other)
            labels[start + i] = raw if raw in allowed_set else other
    return _share_counts(labels, allowed)


async def classify_tones(
    texts: list[str],
    *,
    locale: ReportLocale = "sv",
    prompts: dict[str, str],
    batch_size: int = _CLASSIFY_BATCH_SIZE,
) -> tuple[dict[str, float], ToneMode]:
    labels_allowed = list(tone_labels(locale))
    if not texts:
        return {lab: 0.0 for lab in labels_allowed}, "llm"

    labels: list[str] = [""] * len(texts)
    quoted = ", ".join(f"'{lab}'" for lab in labels_allowed)
    default = labels_allowed[-1]
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        numbered = "\n".join(f"{i}. {t[:_TEXT_CHARS]}" for i, t in enumerate(chunk))
        system = render_prompt(
            prompts,
            "report.classify.tones.system",
            quoted=quoted,
            sharp_tone=labels_allowed[0],
        )
        result = await complete_structured(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": numbered},
            ],
            _ToneBatchResponse,
        )
        by_idx = {item.index: item.tone for item in result.items}
        allowed_set = set(labels_allowed)
        for i in range(len(chunk)):
            raw = by_idx.get(i, default)
            labels[start + i] = raw if raw in allowed_set else default
    return _share_counts(labels, labels_allowed), "llm"


async def classify_bundle(
    bundle: RunBundle,
    *,
    locale: ReportLocale = "sv",
    prompts: dict[str, str],
) -> BundleClassification:
    texts = _texts_for_classify(bundle)
    packs = await derive_topic_packs(
        bundle.injection_texts, locale=locale, prompts=prompts
    )
    topic_shares = await classify_topics(
        texts, packs, locale=locale, prompts=prompts
    )
    tone_shares, tone_mode = await classify_tones(
        texts, locale=locale, prompts=prompts
    )
    return BundleClassification(
        topic_packs=packs,
        topic_shares=topic_shares,
        tone_shares=tone_shares,
        tone_mode=tone_mode,
    )


async def classify_bundles(
    bundles: list[RunBundle],
    *,
    locale: ReportLocale = "sv",
    prompts: dict[str, str],
) -> list[BundleClassification]:
    return [
        await classify_bundle(b, locale=locale, prompts=prompts) for b in bundles
    ]


def meta_topics_line(
    classifications: list[BundleClassification],
    *,
    locale: ReportLocale = "sv",
) -> str:
    other = other_topic_label(locale)
    labels: list[str] = []
    seen: set[str] = set()
    for c in classifications:
        for pack in c.topic_packs:
            if pack.label not in seen:
                seen.add(pack.label)
                labels.append(pack.label)
        if other in c.topic_shares and c.topic_shares.get(other, 0) > 0:
            if other not in seen:
                seen.add(other)
                labels.append(other)
    return "; ".join(labels) if labels else meta_topics_fallback(locale)
