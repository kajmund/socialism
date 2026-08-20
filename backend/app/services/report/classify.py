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
from app.services.report.sampling import (
    TopicStatus,
    injection_post_ids,
    discussion_post_ids,
    sample_reactions_for_ssr,
)
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
    style_shares: list[tuple[str, float]] = field(default_factory=list)
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
    sampling: dict[str, object] = field(default_factory=dict)
    post_topic_status: dict[int, TopicStatus] = field(default_factory=dict)


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


_STYLE_CRITICAL = frozenset(
    {
        "Sarkastisk + konkret kritik",
        "Provocerande / konfronterande",
    }
)
_STYLE_RESIGNED = "Uppgiven + vardagsmetafor"
_STYLE_DOMINANCE_MARGIN = 0.10


def dominant_style_label(
    style_shares: list[tuple[str, float]],
    *,
    margin: float = _STYLE_DOMINANCE_MARGIN,
) -> str:
    """Highest-share style label when it leads the runner-up by at least ``margin``."""
    ranked = [
        (style, share)
        for style, share in style_shares
        if style != STYLE_UNCLASSIFIED and share > 0.0
    ]
    if not ranked:
        return ""
    ranked.sort(key=lambda item: item[1], reverse=True)
    top_style, top_share = ranked[0]
    if len(ranked) == 1:
        return top_style
    if top_share - ranked[1][1] >= margin:
        return top_style
    return ""


def honest_negative_tone_phrase(
    style_shares: list[tuple[str, float]],
    *,
    locale: ReportLocale,
) -> str:
    """Map negative tone mass to reader-facing wording via dominant style."""
    dominant = dominant_style_label(style_shares)
    if dominant in _STYLE_CRITICAL:
        return "critical" if locale == "en" else "kritisk"
    if dominant == _STYLE_RESIGNED:
        return "dissatisfied and resigned" if locale == "en" else "missnöjd/uppgiven"
    return "negative tone" if locale == "en" else "negativ ton"


def _style_shares_from_pmfs(pmfs: list[dict[str, float]]) -> list[tuple[str, float]]:
    """Share of rated reactions per style label (mean SSR mass, unit weight per text)."""
    buckets: dict[str, float] = {lab: 0.0 for lab in [*STYLE_LABELS, STYLE_UNCLASSIFIED]}
    rated = 0

    for pmf in pmfs:
        rated += 1
        total = sum(pmf.values()) or 0.0
        if total <= 0.0:
            buckets[STYLE_UNCLASSIFIED] += 1.0
            continue
        for lab, p in pmf.items():
            if lab not in buckets:
                continue
            buckets[lab] += p / total

    scored = [
        (style, (buckets[style] / rated) if rated > 0 else 0.0)
        for style in [*STYLE_LABELS, STYLE_UNCLASSIFIED]
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


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


def classify_post_topics(
    bundle: RunBundle,
    packs: list[TopicPack],
    *,
    locale: ReportLocale = "sv",
) -> dict[int, TopicStatus]:
    """Per-post topic status: injection posts on_topic; citizen posts via keywords."""
    injection_ids = injection_post_ids(bundle)
    discussion_ids = discussion_post_ids(bundle)
    other = other_topic_label(locale)
    out: dict[int, TopicStatus] = {}

    for post in bundle.posts:
        raw_id = post.get("post_id")
        if raw_id is None:
            continue
        post_id = int(raw_id)
        if post_id in injection_ids:
            out[post_id] = "on_topic"
        elif post_id in discussion_ids:
            text = str(post.get("content") or post.get("text") or "").strip()
            if not text:
                continue
            shares = classify_topics_by_keywords([text], packs, locale=locale)
            top_label = max(shares, key=shares.get)
            out[post_id] = "drifted" if top_label == other else "on_topic"
    return out


def topic_status_for_comment(
    comment: dict,
    *,
    post_topic_status: dict[int, TopicStatus],
    injection_post_ids_set: frozenset[int],
) -> TopicStatus | None:
    """Comments inherit parent post topic status; injection-thread comments are on_topic."""
    raw_parent = comment.get("post_id")
    if raw_parent is None:
        return None
    parent_id = int(raw_parent)
    if parent_id in injection_post_ids_set:
        return "on_topic"
    return post_topic_status.get(parent_id)


def all_post_texts_for_topic_shares(bundle: RunBundle) -> list[str]:
    """Non-injector post bodies for aggregate topic keyword shares."""
    injectors: set[int] = set()
    for agent in bundle.agents:
        if str(agent.get("role") or "") != "injector":
            continue
        try:
            injectors.add(int(agent.get("index")))
        except (TypeError, ValueError):
            continue
    texts: list[str] = []
    for post in bundle.posts:
        uid = post.get("user_id")
        if uid is not None and int(uid) in injectors:
            continue
        text = str(post.get("content") or post.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def lookup_text_topic_status(
    bundle: RunBundle,
    post_topic_status: dict[int, TopicStatus],
    text: str,
) -> TopicStatus | None:
    """Resolve topic status for a post/comment body (exact match)."""
    needle = text.strip()
    if not needle:
        return None
    injection_ids = injection_post_ids(bundle)
    for post in bundle.posts:
        body = str(post.get("content") or post.get("text") or "").strip()
        if body != needle:
            continue
        raw_id = post.get("post_id")
        if raw_id is None:
            return None
        return post_topic_status.get(int(raw_id))
    for comment in bundle.comments:
        body = str(comment.get("content") or comment.get("text") or "").strip()
        if body != needle:
            continue
        return topic_status_for_comment(
            comment,
            post_topic_status=post_topic_status,
            injection_post_ids_set=injection_ids,
        )
    return None


def clip_texts_for_embed(texts: list[str]) -> list[str]:
    """Clip reaction snippets to the embed limit used in report SSR."""
    return _clip_for_embed(texts)


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
    *,
    locale: ReportLocale = "sv",
    temperature: float = DEFAULT_SSR_TEMPERATURE,
    style_anchor_set: AnchorSet | None = None,
    style_anchor_vectors: list[list[float]] | None = None,
) -> tuple[list[tuple[str, float]], list[str], list[dict[str, float]], float]:
    """SSR style: embed reaction texts directly → share of reactions per style."""
    if not texts:
        return (
            [(lab, 0.0) for lab in [*STYLE_LABELS, STYLE_UNCLASSIFIED]],
            [],
            [],
            0.0,
        )

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
    style_shares = _style_shares_from_pmfs(result.per_text_pmfs)
    return style_shares, list(texts), result.per_text_pmfs, embed_s


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
    packs = topic_packs_from_injections(bundle.injection_texts, locale=locale)
    post_topic_status = classify_post_topics(bundle, packs, locale=locale)
    topic_texts = all_post_texts_for_topic_shares(bundle)
    topic_shares = classify_topics_by_keywords(topic_texts, packs, locale=locale)

    sampled = sample_reactions_for_ssr(
        bundle,
        post_topic_status=post_topic_status,
        locale=locale,
    )
    texts = sampled.texts
    likes = sampled.likes
    user_ids = sampled.user_ids

    tone_shares, tone_mode, tone_rated, tone_pmfs, tone_embed = await classify_tones(
        texts,
        locale=locale,
        temperature=ssr_temperature,
        tone_anchor_set=tone_anchor_set,
        tone_anchor_vectors=tone_anchor_vectors,
    )

    style_shares, style_rated, style_pmfs, style_embed = await classify_styles(
        texts,
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
        style_shares=style_shares,
        tone_pmfs=tone_pmfs,
        style_pmfs=style_pmfs,
        classify_llm_seconds=0.0,
        embed_seconds=tone_embed + style_embed,
        sample_texts=texts,
        sample_likes=likes,
        sample_user_ids=user_ids,
        tone_rated_texts=tone_rated,
        style_rated_texts=style_rated,
        sampling=dict(sampled.meta),
        post_topic_status=post_topic_status,
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
