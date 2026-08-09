"""Topic packs (LLM or injection keywords) + tone/style via direct SSR embeddings.

Tone and style rate population reaction texts against anchors (OpenAI embeddings).
No DeepSeek free-text judgments in the SSR path.
"""

from __future__ import annotations

import re
import time
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
from app.schemas.domain import DEFAULT_SSR_TEMPERATURE
from app.services.ssr import (
    AnchorSet,
    STYLE_LABELS,
    STYLE_UNCLASSIFIED,
    rate_texts,
    style_anchors,
    tone_anchors,
)

ToneMode = Literal["ssr"]
TopicMode = Literal["llm", "injection"]

# Keep batches small — large structured prompts stall on DeepSeek.
_CLASSIFY_BATCH_SIZE = 8
_TEXT_CHARS = 200
# Cap embed/LLM samples: highest-engagement texts (likes).
_MAX_CLASSIFY_TEXTS = 16

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9%]{3,}")
_STOP_SV = frozenset(
    {
        "och",
        "att",
        "det",
        "som",
        "för",
        "med",
        "är",
        "på",
        "en",
        "ett",
        "den",
        "de",
        "vi",
        "ni",
        "om",
        "till",
        "från",
        "har",
        "kan",
        "ska",
        "vill",
        "inte",
        "men",
        "eller",
        "var",
        "vad",
        "hur",
        "när",
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "from",
        "are",
        "was",
        "will",
        "not",
    }
)

# Historical Swedish labels (tests / callers) — now 5-level SSR scale.
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
    tone_mode: ToneMode = "ssr"
    topic_mode: TopicMode = "llm"
    style_avg_likes: list[tuple[str, float]] = field(default_factory=list)
    tone_pmfs: list[dict[str, float]] = field(default_factory=list)
    style_pmfs: list[dict[str, float]] = field(default_factory=list)
    classify_llm_seconds: float = 0.0
    embed_seconds: float = 0.0
    sample_texts: list[str] = field(default_factory=list)
    sample_likes: list[int] = field(default_factory=list)
    sample_user_ids: list[int] = field(default_factory=list)
    # Texts that were embedded for SSR (reaction snippets, not LLM judgments).
    tone_rated_texts: list[str] = field(default_factory=list)
    style_rated_texts: list[str] = field(default_factory=list)


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


def _item_likes(item: dict) -> int:
    for key in ("num_likes", "likes", "like_count"):
        v = item.get(key)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _samples_for_classify(
    bundle: RunBundle, *, limit: int = _MAX_CLASSIFY_TEXTS
) -> tuple[list[str], list[int], list[int]]:
    """Prefer higher-engagement posts/comments; cap count for cost/latency."""
    scored: list[tuple[int, str, int]] = []
    for p in bundle.posts:
        c = p.get("content") or p.get("text") or ""
        if c:
            scored.append((_item_likes(p), str(c), int(p.get("user_id") or -1)))
    for c in bundle.comments:
        t = c.get("content") or c.get("text") or ""
        if t:
            scored.append((_item_likes(c), str(t), int(c.get("user_id") or -1)))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]
    return (
        [text for _, text, _ in top],
        [likes for likes, _, _ in top],
        [uid for _, _, uid in top],
    )


def _texts_for_classify(
    bundle: RunBundle, *, limit: int = _MAX_CLASSIFY_TEXTS
) -> tuple[list[str], list[int]]:
    texts, likes, _uids = _samples_for_classify(bundle, limit=limit)
    return texts, likes


def _share_counts(labels: list[str], allowed: list[str]) -> dict[str, float]:
    counts: Counter[str] = Counter({lab: 0 for lab in allowed})
    for lab in labels:
        counts[lab if lab in counts else allowed[-1]] += 1
    total = sum(counts.values()) or 1
    return {lab: counts[lab] / total for lab in allowed}


def _keywords_from_text(text: str, *, limit: int = 8) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for w in _WORD_RE.findall(text.lower()):
        if w in _STOP_SV or w in seen:
            continue
        seen.add(w)
        words.append(w)
        if len(words) >= limit:
            break
    return words


def topic_packs_from_injections(
    injection_texts: list[str],
    *,
    locale: ReportLocale = "sv",
) -> list[TopicPack]:
    """Deterministic packs from injection copy — no LLM (quick reports)."""
    if not injection_texts:
        return []
    packs: list[TopicPack] = []
    for raw in injection_texts[:4]:
        text = raw.strip()
        if not text:
            continue
        label = text.split(".")[0].strip()[:48] or text[:48]
        keywords = _keywords_from_text(text)
        if not keywords:
            keywords = [label.lower()[:24]]
        packs.append(TopicPack(label=label, keywords=keywords))
    if not packs:
        fallback = "Message" if locale == "en" else "Budskap"
        packs = [TopicPack(label=fallback, keywords=[fallback.lower()])]
    return packs


def classify_topics_by_keywords(
    texts: list[str],
    packs: list[TopicPack],
    *,
    locale: ReportLocale = "sv",
) -> dict[str, float]:
    """Keyword topic shares — no LLM (quick reports / drift support)."""
    other = other_topic_label(locale)
    allowed = [p.label for p in packs] + [other]
    if not texts:
        return {lab: 0.0 for lab in allowed}
    if not packs:
        return {other: 1.0}
    labels: list[str] = []
    for text in texts:
        low = text.lower()
        hit = other
        for pack in packs:
            if any(k and k in low for k in pack.keywords):
                hit = pack.label
                break
        labels.append(hit)
    return _share_counts(labels, allowed)


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


def _style_avg_from_pmfs(
    likes: list[int],
    pmfs: list[dict[str, float]],
) -> list[tuple[str, float]]:
    """Soft-weighted average likes per style from SSR PMFs."""
    buckets: dict[str, float] = {lab: 0.0 for lab in STYLE_LABELS}
    weights: dict[str, float] = {lab: 0.0 for lab in STYLE_LABELS}
    buckets[STYLE_UNCLASSIFIED] = 0.0
    weights[STYLE_UNCLASSIFIED] = 0.0

    for like, pmf in zip(likes, pmfs, strict=True):
        total = sum(pmf.values()) or 0.0
        if total <= 0.0:
            buckets[STYLE_UNCLASSIFIED] += float(like)
            weights[STYLE_UNCLASSIFIED] += 1.0
            continue
        for lab, p in pmf.items():
            if lab not in buckets:
                continue
            buckets[lab] += float(like) * p
            weights[lab] += p

    scored = [
        (style, (buckets[style] / weights[style]) if weights[style] > 0 else 0.0)
        for style in [*STYLE_LABELS, STYLE_UNCLASSIFIED]
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _clip_for_embed(texts: list[str]) -> list[str]:
    return [t[:_TEXT_CHARS] if t.strip() else " " for t in texts]


async def classify_tones(
    texts: list[str],
    *,
    locale: ReportLocale = "sv",
    prompts: dict[str, str] | None = None,
    temperature: float = DEFAULT_SSR_TEMPERATURE,
    tone_anchor_set: AnchorSet | None = None,
) -> tuple[dict[str, float], ToneMode, list[str], list[dict[str, float]], float]:
    """SSR tone: embed reaction texts directly against 5 Likert anchors.

    ``prompts`` kept for call-site compatibility; unused (no LLM in SSR path).
    Returns (tone_shares, mode, rated_texts, per_text_pmfs, embed_seconds).
    """
    del prompts  # SSR path does not use DeepSeek
    labels_allowed = list(tone_labels(locale))
    empty = {lab: 0.0 for lab in labels_allowed}
    if not texts:
        return empty, "ssr", [], [], 0.0

    rated = _clip_for_embed(texts)
    t0 = time.perf_counter()
    anchors = tone_anchor_set or tone_anchors(locale=locale)
    result = await rate_texts(rated, anchors, temperature=temperature)
    embed_s = time.perf_counter() - t0
    return result.shares, "ssr", rated, result.per_text_pmfs, embed_s


async def classify_styles(
    texts: list[str],
    likes: list[int],
    *,
    locale: ReportLocale = "sv",
    prompts: dict[str, str] | None = None,
    temperature: float = DEFAULT_SSR_TEMPERATURE,
    style_anchor_set: AnchorSet | None = None,
) -> tuple[list[tuple[str, float]], list[str], list[dict[str, float]], float]:
    """SSR style: embed reaction texts directly → soft-weighted avg likes."""
    del prompts
    if not texts:
        return (
            [(lab, 0.0) for lab in [*STYLE_LABELS, STYLE_UNCLASSIFIED]],
            [],
            [],
            0.0,
        )
    if len(likes) != len(texts):
        raise ValueError("likes length must match texts")

    rated = _clip_for_embed(texts)
    t0 = time.perf_counter()
    anchors = style_anchor_set or style_anchors(locale=locale)
    result = await rate_texts(rated, anchors, temperature=temperature)
    embed_s = time.perf_counter() - t0
    style_avg = _style_avg_from_pmfs(likes, result.per_text_pmfs)
    return style_avg, rated, result.per_text_pmfs, embed_s


async def classify_bundle(
    bundle: RunBundle,
    *,
    locale: ReportLocale = "sv",
    prompts: dict[str, str],
    topic_mode: TopicMode = "llm",
    ssr_temperature: float = DEFAULT_SSR_TEMPERATURE,
    tone_anchor_set: AnchorSet | None = None,
    style_anchor_set: AnchorSet | None = None,
) -> BundleClassification:
    texts, likes, user_ids = _samples_for_classify(bundle)
    t_llm = 0.0
    t_embed = 0.0

    if topic_mode == "injection":
        packs = topic_packs_from_injections(bundle.injection_texts, locale=locale)
        topic_shares = classify_topics_by_keywords(texts, packs, locale=locale)
    else:
        t0 = time.perf_counter()
        packs = await derive_topic_packs(
            bundle.injection_texts, locale=locale, prompts=prompts
        )
        topic_shares = await classify_topics(
            texts, packs, locale=locale, prompts=prompts
        )
        t_llm += time.perf_counter() - t0

    tone_shares, tone_mode, tone_rated, tone_pmfs, tone_embed = await classify_tones(
        texts,
        locale=locale,
        temperature=ssr_temperature,
        tone_anchor_set=tone_anchor_set,
    )
    t_embed += tone_embed

    style_avg, style_rated, style_pmfs, style_embed = await classify_styles(
        texts,
        likes,
        locale=locale,
        temperature=ssr_temperature,
        style_anchor_set=style_anchor_set,
    )
    t_embed += style_embed

    return BundleClassification(
        topic_packs=packs,
        topic_shares=topic_shares,
        tone_shares=tone_shares,
        tone_mode=tone_mode,
        topic_mode=topic_mode,
        style_avg_likes=style_avg,
        tone_pmfs=tone_pmfs,
        style_pmfs=style_pmfs,
        classify_llm_seconds=t_llm,
        embed_seconds=t_embed,
        sample_texts=texts,
        sample_likes=likes,
        sample_user_ids=user_ids,
        tone_rated_texts=tone_rated,
        style_rated_texts=style_rated,
    )


async def classify_bundles(
    bundles: list[RunBundle],
    *,
    locale: ReportLocale = "sv",
    prompts: dict[str, str],
    topic_mode: TopicMode = "llm",
    ssr_temperature: float = DEFAULT_SSR_TEMPERATURE,
    tone_anchor_set: AnchorSet | None = None,
    style_anchor_set: AnchorSet | None = None,
) -> list[BundleClassification]:
    return [
        await classify_bundle(
            b,
            locale=locale,
            prompts=prompts,
            topic_mode=topic_mode,
            ssr_temperature=ssr_temperature,
            tone_anchor_set=tone_anchor_set,
            style_anchor_set=style_anchor_set,
        )
        for b in bundles
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
