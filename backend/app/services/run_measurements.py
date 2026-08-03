"""Derive measurement-point summaries from a variant's ticks + feed."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.schemas.domain import Tick

MEASUREMENT_LABELS: dict[str, str] = {
    "opinion_snapshot": "Opinionsmätning",
    "sentiment_baseline": "Sentiment-baslinje",
    "phrase_propagation": "Frasspridning",
    "sentiment_recovery": "Sentiment-återhämtning",
    "engagement_decay": "Engagemangsavklingning",
}

_POS = {
    "bra",
    "bättre",
    "positiv",
    "glädje",
    "stödjer",
    "håller",
    "viktigt",
    "tack",
    "hopp",
    "stark",
    "rätt",
    "bra!",
}
_NEG = {
    "dåligt",
    "sämre",
    "negativ",
    "arg",
    "sorgligt",
    "fel",
    "skandal",
    "rasar",
    "uselt",
    "hatar",
    "stopp",
    "nej",
}
_STOP = {
    "och",
    "att",
    "det",
    "som",
    "en",
    "ett",
    "på",
    "är",
    "av",
    "för",
    "med",
    "till",
    "den",
    "de",
    "i",
    "om",
    "har",
    "inte",
    "jag",
    "vi",
    "du",
    "ni",
    "han",
    "hon",
    "eller",
    "men",
    "så",
    "var",
    "när",
    "från",
    "ska",
    "kan",
    "man",
    "sig",
    "the",
    "a",
    "an",
}


def _tokens(text: str) -> list[str]:
    return [
        t
        for t in re.findall(r"[A-Za-zÅÄÖåäö]{3,}", (text or "").casefold())
        if t not in _STOP
    ]


def _post_text(post: dict[str, Any]) -> str:
    quote = (post.get("quote_content") or "").strip()
    content = (post.get("content") or "").strip()
    return f"{quote}\n{content}".strip()


def _engagement(posts: list[dict[str, Any]], comments: list[dict[str, Any]]) -> dict[str, Any]:
    likes = sum(int(p.get("num_likes") or 0) for p in posts)
    shares = sum(int(p.get("num_shares") or 0) for p in posts)
    dislikes = sum(int(p.get("num_dislikes") or 0) for p in posts)
    comment_likes = sum(int(c.get("num_likes") or 0) for c in comments)
    score = likes + comment_likes + 2 * len(comments) + 3 * shares
    return {
        "posts": len(posts),
        "comments": len(comments),
        "likes": likes + comment_likes,
        "shares": shares,
        "dislikes": dislikes,
        "engagement_score": score,
    }


def _sentiment(texts: list[str]) -> dict[str, float]:
    pos = neg = neu = 0
    for text in texts:
        toks = set(_tokens(text))
        p = len(toks & _POS)
        n = len(toks & _NEG)
        if p > n:
            pos += 1
        elif n > p:
            neg += 1
        else:
            neu += 1
    total = max(pos + neg + neu, 1)
    return {
        "positive": round(pos / total, 3),
        "neutral": round(neu / total, 3),
        "negative": round(neg / total, 3),
    }


def _top_phrases(texts: list[str], *, limit: int = 5) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for text in texts:
        counts.update(_tokens(text))
    return [{"phrase": w, "count": c} for w, c in counts.most_common(limit)]


def _bucket_posts(
    posts: list[dict[str, Any]], ticks_run: int
) -> list[list[dict[str, Any]]]:
    if ticks_run <= 0:
        return []
    ordered = sorted(
        posts,
        key=lambda p: (str(p.get("created_at") or ""), int(p.get("post_id") or 0)),
    )
    n = len(ordered)
    buckets: list[list[dict[str, Any]]] = []
    for i in range(ticks_run):
        start = i * n // ticks_run
        end = (i + 1) * n // ticks_run
        buckets.append(ordered[start:end])
    return buckets


def _comments_for_posts(
    comments: list[dict[str, Any]], posts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    ids = {p.get("post_id") for p in posts}
    return [c for c in comments if c.get("post_id") in ids]


def _by_district(
    posts: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    district_by_agent: dict[int, str],
) -> list[dict[str, Any]]:
    agg: dict[str, dict[str, int]] = {}
    for post in posts:
        uid = int(post.get("user_id") or -1)
        district = district_by_agent.get(uid) or "Okänd"
        row = agg.setdefault(district, {"posts": 0, "comments": 0, "likes": 0, "shares": 0})
        row["posts"] += 1
        row["likes"] += int(post.get("num_likes") or 0)
        row["shares"] += int(post.get("num_shares") or 0)
    for comment in comments:
        uid = int(comment.get("user_id") or -1)
        district = district_by_agent.get(uid) or "Okänd"
        row = agg.setdefault(district, {"posts": 0, "comments": 0, "likes": 0, "shares": 0})
        row["comments"] += 1
        row["likes"] += int(comment.get("num_likes") or 0)
    out = [
        {
            "label": label,
            "posts": vals["posts"],
            "comments": vals["comments"],
            "engagement_score": vals["likes"] + 2 * vals["comments"] + 3 * vals["shares"],
        }
        for label, vals in agg.items()
    ]
    out.sort(key=lambda r: r["engagement_score"], reverse=True)
    return out


def _district_by_agent_index(
    agents: list[dict[str, Any]],
    member_districts: dict[str, str],
) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for agent in agents:
        idx = agent.get("index")
        if idx is None:
            continue
        persona_id = agent.get("persona_id")
        name = agent.get("member_name") or ""
        district = ""
        if persona_id and persona_id in member_districts:
            district = member_districts[persona_id]
        elif name in member_districts:
            district = member_districts[name]
        if district:
            mapping[int(idx)] = district
    return mapping


def _summary_for(kind: str, metrics: dict[str, Any]) -> str:
    eng = metrics.get("engagement") or {}
    posts = eng.get("posts", 0)
    comments = eng.get("comments", 0)
    score = eng.get("engagement_score", 0)
    if kind in {"opinion_snapshot", "sentiment_baseline", "sentiment_recovery"}:
        sent = metrics.get("sentiment") or {}
        return (
            f"{posts} inlägg · {comments} kommentarer · "
            f"pos {int(round((sent.get('positive') or 0) * 100))}% · "
            f"engagemang {score}"
        )
    if kind == "phrase_propagation":
        top = metrics.get("top_phrases") or []
        if not top:
            return f"{posts} inlägg · inga fraser ännu"
        lead = ", ".join(f"«{p['phrase']}»" for p in top[:3])
        return f"{lead}"
    if kind == "engagement_decay":
        delta = metrics.get("engagement_delta")
        if delta is None:
            return f"engagemang {score}"
        arrow = "+" if delta >= 0 else ""
        return f"engagemang {score} ({arrow}{delta} vs föregående)"
    return f"{posts} inlägg · {comments} kommentarer"


def _point_metrics(
    kind: str,
    *,
    window_posts: list[dict[str, Any]],
    window_comments: list[dict[str, Any]],
    prev_posts: list[dict[str, Any]] | None,
    prev_comments: list[dict[str, Any]] | None,
    agents: list[dict[str, Any]],
    district_by_agent: dict[int, str],
) -> dict[str, Any]:
    texts = [_post_text(p) for p in window_posts] + [
        (c.get("content") or "") for c in window_comments
    ]
    engagement = _engagement(window_posts, window_comments)
    metrics: dict[str, Any] = {
        "engagement": engagement,
        "sentiment": _sentiment(texts),
        "top_phrases": _top_phrases(texts),
        "by_district": _by_district(
            window_posts, window_comments, agents, district_by_agent
        ),
    }
    if kind == "engagement_decay" and prev_posts is not None:
        prev_eng = _engagement(prev_posts, prev_comments or [])
        metrics["engagement_delta"] = (
            engagement["engagement_score"] - prev_eng["engagement_score"]
        )
        metrics["previous_engagement_score"] = prev_eng["engagement_score"]
    return metrics


def build_measurements(
    ticks: list[Tick],
    *,
    posts: list[dict[str, Any]] | None = None,
    comments: list[dict[str, Any]] | None = None,
    agents: list[dict[str, Any]] | None = None,
    member_districts: dict[str, str] | None = None,
    ticks_run: int | None = None,
) -> list[dict[str, Any]]:
    """Build measurement rows for ticks that requested measurements.

    Feed activity is split across executed non-silent ticks (by post order).
    Snapshot-style metrics use the cumulative feed through that tick;
    engagement_decay compares the tick window to the previous tick window.
    """
    posts = list(posts or [])
    comments = list(comments or [])
    agents = list(agents or [])
    member_districts = member_districts or {}
    district_by_agent = _district_by_agent_index(agents, member_districts)

    active = [t for t in ticks if not t.silent]
    if ticks_run is not None and ticks_run > 0:
        active = active[:ticks_run]
    elif ticks_run == 0:
        # No feed yet — still expose configured measurement points with empty metrics.
        active = [t for t in active if t.measurements]
    buckets = _bucket_posts(posts, len(active)) if active and posts else [[] for _ in active]

    rows: list[dict[str, Any]] = []
    for i, tick in enumerate(active):
        kinds = [k for k in (tick.measurements or []) if k in MEASUREMENT_LABELS]
        if not kinds:
            continue
        cumulative_posts = [p for b in buckets[: i + 1] for p in b]
        cumulative_comments = _comments_for_posts(comments, cumulative_posts)
        tick_posts = buckets[i] if i < len(buckets) else []
        tick_comments = _comments_for_posts(comments, tick_posts)
        prev_posts = buckets[i - 1] if i > 0 else []
        prev_comments = _comments_for_posts(comments, prev_posts) if i > 0 else []

        points: list[dict[str, Any]] = []
        for kind in kinds:
            if kind == "engagement_decay":
                window_posts, window_comments = tick_posts, tick_comments
                prev_p, prev_c = prev_posts, prev_comments
            else:
                window_posts, window_comments = cumulative_posts, cumulative_comments
                prev_p, prev_c = None, None
            metrics = _point_metrics(
                kind,
                window_posts=window_posts,
                window_comments=window_comments,
                prev_posts=prev_p,
                prev_comments=prev_c,
                agents=agents,
                district_by_agent=district_by_agent,
            )
            points.append(
                {
                    "id": kind,
                    "label": MEASUREMENT_LABELS[kind],
                    "summary": _summary_for(kind, metrics),
                    "metrics": metrics,
                }
            )

        rows.append(
            {
                "tick_key": tick.key,
                "day": tick.day,
                "tick_index": i,
                "kinds": kinds,
                "points": points,
            }
        )
    return rows
