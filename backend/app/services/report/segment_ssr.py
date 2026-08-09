"""SSR tone aggregation by persona bio segment (no DeepSeek)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification
from app.services.report.locale import ReportLocale, tone_labels
from app.services.report.persona_bio import (
    PRIMARY_SEGMENT_KEYS,
    build_agent_bio_by_index,
    segment_key_value,
    segment_value,
)

MIN_SEGMENT_TEXTS = 2


def _activity_for_agents(
    bundle: RunBundle,
    agent_ids: frozenset[int],
) -> tuple[int, int, int, int]:
    """Posts, comments, likes, shares for agents in segment."""
    ids = set(agent_ids)
    posts = comments = likes = shares = 0
    for post in bundle.posts:
        if int(post.get("user_id") or -1) not in ids:
            continue
        posts += 1
        likes += int(post.get("num_likes") or 0)
        shares += int(post.get("num_shares") or 0)
    for comment in bundle.comments:
        if int(comment.get("user_id") or -1) not in ids:
            continue
        comments += 1
        likes += int(comment.get("num_likes") or 0)
    return posts, comments, likes, shares


@dataclass
class SegmentToneRow:
    dimension: str
    label: str
    text_count: int
    agent_count: int
    positive_share: float
    critical_share: float
    engagement_score: int
    too_few: bool
    agent_ids: frozenset[int] = frozenset()
    tone_shares: dict[str, float] = field(default_factory=dict)
    post_count: int = 0
    comment_count: int = 0
    likes_total: int = 0
    shares_total: int = 0
    sample_texts: list[str] = field(default_factory=list)


def _positive_share(tone: dict[str, float], *, locale: ReportLocale) -> float:
    if locale == "en":
        return tone.get("Somewhat positive", 0.0) + tone.get("Strongly positive", 0.0)
    return tone.get("Något positiv", 0.0) + tone.get("Starkt positiv", 0.0)


def _critical_share(tone: dict[str, float], *, locale: ReportLocale) -> float:
    if locale == "en":
        return tone.get("Somewhat negative", 0.0) + tone.get("Strongly negative", 0.0)
    return tone.get("Något negativ", 0.0) + tone.get("Starkt negativ", 0.0)


def _mean_pmf_dicts(pmfs: list[dict[str, float]], labels: list[str]) -> dict[str, float]:
    if not pmfs:
        return {lab: 0.0 for lab in labels}
    acc = {lab: 0.0 for lab in labels}
    for pmf in pmfs:
        for lab in labels:
            acc[lab] += float(pmf.get(lab) or 0.0)
    n = len(pmfs)
    return {lab: acc[lab] / n for lab in labels}


def _engagement_for_user(bundle: RunBundle, user_id: int) -> int:
    score = 0
    for post in bundle.posts:
        if int(post.get("user_id") or -1) != user_id:
            continue
        score += int(post.get("num_likes") or 0)
        score += 2 * int(post.get("num_shares") or 0)
    for comment in bundle.comments:
        if int(comment.get("user_id") or -1) != user_id:
            continue
        score += int(comment.get("num_likes") or 0)
        score += 2
    return score


def segment_dimension_label(key: str, *, locale: ReportLocale) -> str:
    if locale == "en":
        return {
            "livssituation": "Life situation",
            "ort": "District",
            "lutning": "Political leaning",
            "yrke": "Occupation",
            "kön": "Gender",
            "age_band": "Age",
        }.get(key, key)
    return {
        "livssituation": "Livssituation",
        "ort": "Ort",
        "lutning": "Politisk lutning",
        "yrke": "Yrke",
        "kön": "Kön",
        "age_band": "Ålder",
    }.get(key, key)


def build_segment_tone_rows(
    bundle: RunBundle,
    classification: BundleClassification,
    *,
    locale: ReportLocale = "sv",
    segment_keys: tuple[str, ...] = PRIMARY_SEGMENT_KEYS,
) -> list[SegmentToneRow]:
    labels = list(tone_labels(locale))
    agent_bio = build_agent_bio_by_index(bundle)
    rated = classification.tone_rated_texts
    pmfs = classification.tone_pmfs
    user_ids = classification.sample_user_ids
    if len(rated) != len(pmfs) or len(rated) != len(user_ids):
        return []

    by_dim_val_pmfs: dict[tuple[str, str], list[dict[str, float]]] = {}
    by_dim_val_agents: dict[tuple[str, str], set[int]] = {}
    by_dim_val_engagement: dict[tuple[str, str], int] = {}
    by_dim_val_texts: dict[tuple[str, str], list[str]] = {}

    for pmf, uid, text in zip(pmfs, user_ids, rated, strict=True):
        bio = agent_bio.get(uid)
        if not bio:
            continue
        for dim in segment_keys:
            val = segment_key_value(bio, dim, locale=locale)
            if not val:
                continue
            key = (dim, val)
            by_dim_val_pmfs.setdefault(key, []).append(pmf)
            by_dim_val_agents.setdefault(key, set()).add(uid)
            by_dim_val_texts.setdefault(key, []).append(text)

    for uid, bio in agent_bio.items():
        for dim in segment_keys:
            val = segment_key_value(bio, dim, locale=locale)
            if not val:
                continue
            key = (dim, val)
            by_dim_val_engagement[key] = by_dim_val_engagement.get(key, 0) + _engagement_for_user(
                bundle, uid
            )

    rows: list[SegmentToneRow] = []
    for (dim, val), seg_pmfs in sorted(by_dim_val_pmfs.items()):
        count = len(seg_pmfs)
        tone = _mean_pmf_dicts(seg_pmfs, labels)
        agents = frozenset(by_dim_val_agents.get((dim, val), set()))
        post_n, comment_n, likes_n, shares_n = _activity_for_agents(bundle, agents)
        rows.append(
            SegmentToneRow(
                dimension=dim,
                label=val,
                text_count=count,
                agent_count=len(agents),
                positive_share=_positive_share(tone, locale=locale),
                critical_share=_critical_share(tone, locale=locale),
                engagement_score=by_dim_val_engagement.get((dim, val), 0),
                too_few=count < MIN_SEGMENT_TEXTS,
                agent_ids=agents,
                tone_shares=tone,
                post_count=post_n,
                comment_count=comment_n,
                likes_total=likes_n,
                shares_total=shares_n,
                sample_texts=list(by_dim_val_texts.get((dim, val), [])),
            )
        )
    return rows
