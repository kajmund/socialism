"""Deterministic report metrics from RunBundles."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, TONE_LABELS
from app.services.report.persona_bio import build_agent_bio_by_index
from app.services.ssr import STYLE_LABELS, STYLE_UNCLASSIFIED

# Re-export for callers/tests that imported from metrics.
__all__ = [
    "STYLE_LABELS",
    "STYLE_UNCLASSIFIED",
    "BundleMetrics",
    "ReportMetrics",
    "compute_bundle_metrics",
    "compute_report_metrics",
    "fmt_num",
    "pct",
    "population_agent_ids",
]


@dataclass
class BundleMetrics:
    label: str
    agent_count: int
    injector_count: int
    post_count: int
    comment_count: int
    ticks_run: int
    gini: float
    zero_like_agents: int
    mid_agents: int
    top_agents: int
    post_likes: int
    comment_likes: int
    likes_total: int
    shares: int
    dislikes: int
    follow_edges: int
    engagement_score: int
    injection_likes: int
    topic_shares: dict[str, float]
    tone_shares: dict[str, float]
    style_shares: list[tuple[str, float]]
    top_actors: list[dict[str, Any]]
    topic_by_tick: list[dict[str, Any]] = field(default_factory=list)
    action_histogram: list[dict[str, str | int]] = field(default_factory=list)


@dataclass
class ReportMetrics:
    n_runs: int
    bundles: list[BundleMetrics]
    aggregate: BundleMetrics
    cross_table: list[dict[str, Any]]
    tone_mode: str = "ssr"


def _likes(item: dict[str, Any]) -> int:
    for key in ("num_likes", "likes", "like_count"):
        v = item.get(key)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def _user_id(item: dict[str, Any]) -> int | None:
    for key in ("user_id", "agent_id", "author_id"):
        v = item.get(key)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def _agent_name(bundle: RunBundle, user_id: int) -> str:
    for a in bundle.agents:
        if a.get("index") == user_id:
            return str(a.get("member_name") or a.get("name") or f"agent {user_id}")
    return f"agent {user_id}"


def injector_count(bundle: RunBundle) -> int:
    """Institutional accounts (party, news outlet) — not simulated citizens."""
    return sum(1 for a in bundle.agents if a.get("role") == "injector")


def population_agent_ids(bundle: RunBundle) -> set[int]:
    """Indices for population citizens — exclude institutional injectors."""
    ids: set[int] = set()
    for a in bundle.agents:
        idx = a.get("index")
        if not isinstance(idx, int):
            continue
        if a.get("role") == "injector":
            continue
        ids.add(idx)
    return ids


def _gini(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    total = sum(sorted_v)
    if total <= 0:
        return 0.0
    cum = 0.0
    for i, v in enumerate(sorted_v, 1):
        cum += v * i
    return max(0.0, min(1.0, (2 * cum) / (n * total) - (n + 1) / n))


def _empty_style_shares() -> list[tuple[str, float]]:
    return [(lab, 0.0) for lab in [*STYLE_LABELS, STYLE_UNCLASSIFIED]]


def _round_half_up(value: float) -> int:
    """Counts shown to readers round .5 upwards — round() would round to even."""
    return math.floor(value + 0.5)


def _apportion(values: list[float], total: int) -> list[int]:
    """Largest-remainder split of `total` across `values` (sum stays exact)."""
    floors = [math.floor(v) for v in values]
    order = sorted(range(len(values)), key=lambda i: values[i] - floors[i], reverse=True)
    for i in order[: total - sum(floors)]:
        floors[i] += 1
    return floors


def _mean_engagement_tiers(per: list[BundleMetrics]) -> tuple[int, int, int, int]:
    """Cross-run average population and tier split, with tiers summing to it.

    Rounding each tier on its own let the donut divide by a different number than
    the agent count printed next to it (17 citizens, 16 in the chart).
    """
    n = len(per)
    agents = _round_half_up(sum(m.agent_count for m in per) / n)
    top, mid, zero = _apportion(
        [
            sum(m.top_agents for m in per) / n,
            sum(m.mid_agents for m in per) / n,
            sum(m.zero_like_agents for m in per) / n,
        ],
        agents,
    )
    return agents, top, mid, zero


def injection_likes(bundle: RunBundle) -> int:
    """Likes on posts whose content overlaps an injection text (best-effort)."""
    if not bundle.injection_texts:
        return sum(
            int(p.get("num_likes") or p.get("likes") or 0)
            for p in bundle.posts
            if p.get("role") == "injector" or p.get("is_injection")
        )
    total = 0
    needles = [t[:80].lower() for t in bundle.injection_texts if t.strip()]
    for p in bundle.posts:
        content = str(p.get("content") or p.get("text") or "").lower()
        likes = _likes(p)
        if any(n and n in content for n in needles):
            total += likes
            continue
        uid = p.get("user_id")
        for a in bundle.agents:
            if a.get("index") == uid and a.get("role") == "injector":
                total += likes
                break
    return total


def _post_comment_engagement(bundle: RunBundle) -> dict[str, int]:
    post_likes = sum(_likes(p) for p in bundle.posts)
    comment_likes = sum(_likes(c) for c in bundle.comments)
    shares = sum(int(p.get("num_shares") or 0) for p in bundle.posts)
    dislikes = sum(int(p.get("num_dislikes") or 0) for p in bundle.posts)
    dislikes += sum(int(c.get("num_dislikes") or 0) for c in bundle.comments)
    likes_total = post_likes + comment_likes
    score = likes_total + 2 * len(bundle.comments) + 3 * shares
    return {
        "post_likes": post_likes,
        "comment_likes": comment_likes,
        "likes_total": likes_total,
        "shares": shares,
        "dislikes": dislikes,
        "engagement_score": score,
    }


def _top_actors(bundle: RunBundle, *, limit: int = 4) -> list[dict[str, Any]]:
    pop_ids = population_agent_ids(bundle)
    agent_bio = build_agent_bio_by_index(bundle)
    by_user: dict[int, dict[str, Any]] = defaultdict(
        lambda: {"likes": 0, "items": 0, "sample": ""}
    )
    for item in [*bundle.posts, *bundle.comments]:
        uid = _user_id(item)
        if uid is None:
            continue
        if pop_ids and uid not in pop_ids:
            continue
        row = by_user[uid]
        row["likes"] += _likes(item)
        row["items"] += 1
        text = str(item.get("content") or item.get("text") or "").strip()
        if text and (not row["sample"] or len(text) < len(str(row["sample"]))):
            row["sample"] = text

    actors: list[dict[str, Any]] = []
    for uid, row in by_user.items():
        items = max(1, int(row["items"]))
        bio = agent_bio.get(uid) or {}
        actors.append(
            {
                "user_id": uid,
                "name": _agent_name(bundle, uid),
                "bio": dict(bio),
                "likes_total": int(row["likes"]),
                "likes_per_item": round(float(row["likes"]) / items, 2),
                "items": items,
                "sample": row["sample"],
            }
        )
    actors.sort(key=lambda a: (a["likes_total"], a["likes_per_item"]), reverse=True)
    return actors[:limit]


def _engagement_tiers(bundle: RunBundle) -> tuple[int, int, int, float]:
    likes_by_user: dict[int, int] = defaultdict(int)
    agent_ids = population_agent_ids(bundle)
    for item in [*bundle.posts, *bundle.comments]:
        uid = _user_id(item)
        if uid is None:
            continue
        if agent_ids and uid not in agent_ids:
            continue
        likes_by_user[uid] += _likes(item)
        if not agent_ids:
            agent_ids.add(uid)
    if not agent_ids and likes_by_user:
        agent_ids = set(likes_by_user)
    values = [float(likes_by_user.get(uid, 0)) for uid in agent_ids] or [0.0]
    zero = sum(1 for v in values if v <= 0)
    positive = sorted((v for v in values if v > 0), reverse=True)
    top = min(3, len(positive)) if positive else 0
    mid = max(0, len(positive) - top)
    return top, mid, zero, _gini(values)


def _empty_classification() -> BundleClassification:
    return BundleClassification(
        topic_shares={"Övrigt": 1.0},
        tone_shares={lab: 0.0 for lab in TONE_LABELS},
        tone_mode="ssr",
        style_shares=_empty_style_shares(),
    )


def compute_bundle_metrics(
    bundle: RunBundle,
    classification: BundleClassification | None = None,
) -> BundleMetrics:
    clf = classification or _empty_classification()
    top, mid, zero, gini = _engagement_tiers(bundle)
    pop_ids = population_agent_ids(bundle)
    n_agents = len(pop_ids) or (top + mid + zero)
    style = clf.style_shares or _empty_style_shares()
    eng = _post_comment_engagement(bundle)
    hist = [
        {"action": str(h.get("action") or ""), "count": int(h.get("count") or 0)}
        for h in bundle.action_histogram
        if h.get("action")
    ]
    return BundleMetrics(
        label=bundle.label,
        agent_count=n_agents,
        injector_count=injector_count(bundle),
        post_count=len(bundle.posts),
        comment_count=len(bundle.comments),
        ticks_run=bundle.ticks_run,
        gini=round(gini, 3),
        zero_like_agents=zero,
        mid_agents=mid,
        top_agents=top,
        post_likes=eng["post_likes"],
        comment_likes=eng["comment_likes"],
        likes_total=eng["likes_total"],
        shares=eng["shares"],
        dislikes=eng["dislikes"],
        follow_edges=len(bundle.follows),
        engagement_score=eng["engagement_score"],
        injection_likes=injection_likes(bundle),
        topic_shares=dict(clf.topic_shares),
        tone_shares=dict(clf.tone_shares),
        style_shares=list(style),
        top_actors=_top_actors(bundle),
        action_histogram=hist,
    )


def compute_report_metrics(
    bundles: list[RunBundle],
    classifications: list[BundleClassification] | None = None,
) -> ReportMetrics:
    if classifications is not None and len(classifications) != len(bundles):
        raise ValueError("classifications length must match bundles")
    clfs = classifications or [_empty_classification() for _ in bundles]
    per = [compute_bundle_metrics(b, c) for b, c in zip(bundles, clfs, strict=True)]
    tone_mode = clfs[0].tone_mode if clfs else "ssr"

    if len(per) == 1:
        agg = per[0]
    else:
        topic: dict[str, float] = defaultdict(float)
        tone: dict[str, float] = defaultdict(float)
        for m in per:
            for k, v in m.topic_shares.items():
                topic[k] += v
            for k, v in m.tone_shares.items():
                tone[k] += v
        n = len(per)
        style_map: dict[str, list[float]] = defaultdict(list)
        for m in per:
            for style, share in m.style_shares:
                style_map[style].append(share)
        style_shares = sorted(
            ((s, sum(vs) / len(vs)) for s, vs in style_map.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        agents, top, mid, zero = _mean_engagement_tiers(per)
        agg = BundleMetrics(
            label="Alla körningar",
            agent_count=agents,
            injector_count=_round_half_up(sum(m.injector_count for m in per) / n),
            post_count=sum(m.post_count for m in per),
            comment_count=sum(m.comment_count for m in per),
            ticks_run=max(m.ticks_run for m in per),
            gini=round(sum(m.gini for m in per) / n, 3),
            zero_like_agents=zero,
            mid_agents=mid,
            top_agents=top,
            post_likes=sum(m.post_likes for m in per),
            comment_likes=sum(m.comment_likes for m in per),
            likes_total=sum(m.likes_total for m in per),
            shares=sum(m.shares for m in per),
            dislikes=sum(m.dislikes for m in per),
            follow_edges=sum(m.follow_edges for m in per),
            engagement_score=sum(m.engagement_score for m in per),
            injection_likes=sum(m.injection_likes for m in per),
            topic_shares={k: topic[k] / n for k in topic},
            tone_shares={k: tone[k] / n for k in tone},
            style_shares=style_shares,
            top_actors=per[0].top_actors,
            action_histogram=per[0].action_histogram,
        )

    cross = [
        {
            "label": m.label,
            "gini": m.gini,
            "zero_likes": m.zero_like_agents,
            "agents": m.agent_count,
            "posts": m.post_count,
            "comments": m.comment_count,
            "likes_total": m.likes_total,
            "post_likes": m.post_likes,
            "comment_likes": m.comment_likes,
            "shares": m.shares,
            "dislikes": m.dislikes,
            "follow_edges": m.follow_edges,
            "engagement_score": m.engagement_score,
            "injection_likes": m.injection_likes,
            "top_topic": max(m.topic_shares, key=m.topic_shares.get) if m.topic_shares else "—",
        }
        for m in per
    ]
    return ReportMetrics(
        n_runs=len(bundles),
        bundles=per,
        aggregate=agg,
        cross_table=cross,
        tone_mode=tone_mode,
    )


def pct(value: float) -> str:
    return f"{round(value * 100)}%"


def tone_shares_sorted(tone_shares: dict[str, float]) -> list[tuple[str, float]]:
    """Tone labels ordered by share descending (then label for stability)."""
    return sorted(tone_shares.items(), key=lambda kv: (-kv[1], kv[0]))


def fmt_num(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(round(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
