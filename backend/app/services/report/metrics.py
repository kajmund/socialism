"""Deterministic report metrics from RunBundles."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.services.report.bundles import RunBundle
from app.services.report.classify import BundleClassification, TONE_LABELS

STYLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Sarkastisk + konkret kritik": ("statistik", "%", "siffra", "visar att", "ironiskt"),
    "Uppgiven + vardagsmetafor": ("som att", "läckande", "hink", "uppgiven", "trött"),
    "Fakta + yrkesauktoritet": ("enligt", "källa", "forskning", "rapport", "data"),
    "Personlig + hjärtlig berättelse": ("min mamma", "jag själv", "känner", "hjärta"),
    "Optimistisk / lösningsfokuserad": ("lösning", "tillsammans", "framåt", "möjligt"),
    "Provocerande / konfronterande": ("skäms", "lögn", "idiot", "korkat", "absolut noll"),
}

STYLE_UNCLASSIFIED = "Oklassad"


@dataclass
class BundleMetrics:
    label: str
    agent_count: int
    post_count: int
    comment_count: int
    ticks_run: int
    gini: float
    zero_like_agents: int
    mid_agents: int
    top_agents: int
    topic_shares: dict[str, float]
    tone_shares: dict[str, float]
    style_avg_likes: list[tuple[str, float]]
    top_actors: list[dict[str, Any]]
    topic_by_tick: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReportMetrics:
    n_runs: int
    bundles: list[BundleMetrics]
    aggregate: BundleMetrics
    cross_table: list[dict[str, Any]]
    tone_mode: str = "llm"


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


def _style_avg_likes(bundle: RunBundle) -> list[tuple[str, float]]:
    buckets: dict[str, list[float]] = {k: [] for k in STYLE_KEYWORDS}
    buckets[STYLE_UNCLASSIFIED] = []
    for item in [*bundle.posts, *bundle.comments]:
        text = str(item.get("content") or item.get("text") or "").lower()
        likes = float(_likes(item))
        matched = False
        for style, keys in STYLE_KEYWORDS.items():
            if any(k in text for k in keys):
                buckets[style].append(likes)
                matched = True
                break
        if not matched:
            buckets[STYLE_UNCLASSIFIED].append(likes)
    scored = [
        (style, (sum(vals) / len(vals)) if vals else 0.0) for style, vals in buckets.items()
    ]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _top_actors(bundle: RunBundle, *, limit: int = 4) -> list[dict[str, Any]]:
    pop_ids = population_agent_ids(bundle)
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
            row["sample"] = text[:180]

    actors: list[dict[str, Any]] = []
    for uid, row in by_user.items():
        items = max(1, int(row["items"]))
        actors.append(
            {
                "user_id": uid,
                "name": _agent_name(bundle, uid),
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
        tone_mode="llm",
    )


def compute_bundle_metrics(
    bundle: RunBundle,
    classification: BundleClassification | None = None,
) -> BundleMetrics:
    clf = classification or _empty_classification()
    top, mid, zero, gini = _engagement_tiers(bundle)
    pop_ids = population_agent_ids(bundle)
    n_agents = len(pop_ids) or (top + mid + zero)
    return BundleMetrics(
        label=bundle.label,
        agent_count=n_agents,
        post_count=len(bundle.posts),
        comment_count=len(bundle.comments),
        ticks_run=bundle.ticks_run,
        gini=round(gini, 3),
        zero_like_agents=zero,
        mid_agents=mid,
        top_agents=top,
        topic_shares=dict(clf.topic_shares),
        tone_shares=dict(clf.tone_shares),
        style_avg_likes=_style_avg_likes(bundle),
        top_actors=_top_actors(bundle),
    )


def compute_report_metrics(
    bundles: list[RunBundle],
    classifications: list[BundleClassification] | None = None,
) -> ReportMetrics:
    if classifications is not None and len(classifications) != len(bundles):
        raise ValueError("classifications length must match bundles")
    clfs = classifications or [_empty_classification() for _ in bundles]
    per = [compute_bundle_metrics(b, c) for b, c in zip(bundles, clfs, strict=True)]
    tone_mode = "llm"

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
            for style, avg in m.style_avg_likes:
                style_map[style].append(avg)
        style_avg = sorted(
            ((s, sum(vs) / len(vs)) for s, vs in style_map.items()),
            key=lambda x: x[1],
            reverse=True,
        )
        agg = BundleMetrics(
            label="Alla körningar",
            agent_count=round(sum(m.agent_count for m in per) / n),
            post_count=sum(m.post_count for m in per),
            comment_count=sum(m.comment_count for m in per),
            ticks_run=max(m.ticks_run for m in per),
            gini=round(sum(m.gini for m in per) / n, 3),
            zero_like_agents=round(sum(m.zero_like_agents for m in per) / n),
            mid_agents=round(sum(m.mid_agents for m in per) / n),
            top_agents=round(sum(m.top_agents for m in per) / n),
            topic_shares={k: topic[k] / n for k in topic},
            tone_shares={k: tone[k] / n for k in tone},
            style_avg_likes=style_avg,
            top_actors=per[0].top_actors,
        )

    cross = [
        {
            "label": m.label,
            "gini": m.gini,
            "zero_likes": m.zero_like_agents,
            "agents": m.agent_count,
            "posts": m.post_count,
            "comments": m.comment_count,
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


def confidence_badge(n_runs: int, *, all_agree: bool = True) -> str:
    if n_runs <= 1:
        return "observation"
    if all_agree:
        return "confirmed"
    return "indicated"


def pct(value: float) -> str:
    return f"{round(value * 100)}%"


def fmt_num(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(round(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")
