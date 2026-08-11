"""Injection-keyword topics + tone/style via direct SSR embeddings.

Tone and style rate population reaction texts against anchors (OpenAI embeddings).
No DeepSeek free-text judgments in the SSR path.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from app.schemas.domain import DEFAULT_SSR_TEMPERATURE
from app.services.report.bundles import RunBundle
from app.services.report.locale import (
    ReportLocale,
    other_topic_label,
    tone_labels,
)
from app.services.ssr import (
    AnchorSet,
    STYLE_LABELS,
    STYLE_UNCLASSIFIED,
    rate_texts,
    style_anchors,
    tone_anchors,
)

ToneMode = Literal["ssr"]
TopicMode = Literal["injection"]

_TEXT_CHARS = 200
# Cap embed samples: highest-engagement texts (likes).
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
    topic_mode: TopicMode = "injection"
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
    # Pool anchors embed full text; reaction snippets stay clipped for report SSR.
    return [t[:_TEXT_CHARS] if t.strip() else " " for t in texts]


async def classify_tones(
    texts: list[str],
    *,
    locale: ReportLocale = "sv",
    temperature: float = DEFAULT_SSR_TEMPERATURE,
    tone_anchor_set: AnchorSet | None = None,
    tone_anchor_vectors: list[list[float]] | None = None,
) -> tuple[dict[str, float], ToneMode, list[str], list[dict[str, float]], float]:
    """SSR tone: embed reaction texts directly against 5 Likert anchors.

    Returns (tone_shares, mode, rated_texts, per_text_pmfs, embed_seconds).
    """
    labels_allowed = list(tone_labels(locale))
    empty = {lab: 0.0 for lab in labels_allowed}
    if not texts:
        return empty, "ssr", [], [], 0.0

    # Clip only for the embedding API; keep full texts for report quotes.
    # Pool anchors use full text at embed time; reaction snippets stay clipped here.
    embed_texts = _clip_for_embed(texts)
    t0 = time.perf_counter()
    anchors = tone_anchor_set or tone_anchors(locale=locale)
    result = await rate_texts(
        embed_texts,
        anchors,
        temperature=temperature,
        anchor_vectors=tone_anchor_vectors,
    )
    embed_s = time.perf_counter() - t0
    return result.shares, "ssr", list(texts), result.per_text_pmfs, embed_s


async def classify_styles(
    texts: list[str],
    likes: list[int],
    *,
    locale: ReportLocale = "sv",
    temperature: float = DEFAULT_SSR_TEMPERATURE,
    style_anchor_set: AnchorSet | None = None,
    style_anchor_vectors: list[list[float]] | None = None,
) -> tuple[list[tuple[str, float]], list[str], list[dict[str, float]], float]:
    """SSR style: embed reaction texts directly → soft-weighted avg likes."""
    if not texts:
        return (
            [(lab, 0.0) for lab in [*STYLE_LABELS, STYLE_UNCLASSIFIED]],
            [],
            [],
            0.0,
        )
    if len(likes) != len(texts):
        raise ValueError("likes length must match texts")

    embed_texts = _clip_for_embed(texts)
    t0 = time.perf_counter()
    anchors = style_anchor_set or style_anchors(locale=locale)
    result = await rate_texts(
        embed_texts,
        anchors,
        temperature=temperature,
        anchor_vectors=style_anchor_vectors,
    )
    embed_s = time.perf_counter() - t0
    style_avg = _style_avg_from_pmfs(likes, result.per_text_pmfs)
    return style_avg, list(texts), result.per_text_pmfs, embed_s


async def classify_bundle(
    bundle: RunBundle,
    *,
    locale: ReportLocale = "sv",
    ssr_temperature: float = DEFAULT_SSR_TEMPERATURE,
    tone_anchor_set: AnchorSet | None = None,
    style_anchor_set: AnchorSet | None = None,
    tone_anchor_vectors: list[list[float]] | None = None,
    style_anchor_vectors: list[list[float]] | None = None,
) -> BundleClassification:
    texts, likes, user_ids = _samples_for_classify(bundle)

    packs = topic_packs_from_injections(bundle.injection_texts, locale=locale)
    topic_shares = classify_topics_by_keywords(texts, packs, locale=locale)

    tone_shares, tone_mode, tone_rated, tone_pmfs, tone_embed = await classify_tones(
        texts,
        locale=locale,
        temperature=ssr_temperature,
        tone_anchor_set=tone_anchor_set,
        tone_anchor_vectors=tone_anchor_vectors,
    )

    style_avg, style_rated, style_pmfs, style_embed = await classify_styles(
        texts,
        likes,
        locale=locale,
        temperature=ssr_temperature,
        style_anchor_set=style_anchor_set,
        style_anchor_vectors=style_anchor_vectors,
    )

    return BundleClassification(
        topic_packs=packs,
        topic_shares=topic_shares,
        tone_shares=tone_shares,
        tone_mode=tone_mode,
        topic_mode="injection",
        style_avg_likes=style_avg,
        tone_pmfs=tone_pmfs,
        style_pmfs=style_pmfs,
        classify_llm_seconds=0.0,
        embed_seconds=tone_embed + style_embed,
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
    ssr_temperature: float = DEFAULT_SSR_TEMPERATURE,
    tone_anchor_set: AnchorSet | None = None,
    style_anchor_set: AnchorSet | None = None,
    tone_anchor_vectors: list[list[float]] | None = None,
    style_anchor_vectors: list[list[float]] | None = None,
) -> list[BundleClassification]:
    return [
        await classify_bundle(
            b,
            locale=locale,
            ssr_temperature=ssr_temperature,
            tone_anchor_set=tone_anchor_set,
            style_anchor_set=style_anchor_set,
            tone_anchor_vectors=tone_anchor_vectors,
            style_anchor_vectors=style_anchor_vectors,
        )
        for b in bundles
    ]
