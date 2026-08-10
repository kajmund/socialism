"""Tick-by-tick stats and planned interview Q&A for snabbrapport."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.services.report.bundles import RunBundle
from app.services.run_measurements import _bucket_posts, _comments_for_posts, _engagement


@dataclass
class TickStatsRow:
    tick_index: int
    day: int
    silent: bool
    key: str
    rounds: int
    window_posts: int
    window_comments: int
    window_likes: int
    window_shares: int
    window_dislikes: int
    window_engagement_score: int
    cumulative_posts: int
    cumulative_comments: int
    cumulative_likes: int
    cumulative_engagement_score: int
    measurement_points: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class InterviewQA:
    tick_index: int
    day: int
    user_id: int
    agent_name: str
    question: str
    answer: str


def _sort_key_from_created_at(value: Any) -> int:
    if value is None or value == "":
        return 2**62
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    text = str(value).strip()
    if not text:
        return 2**62
    if text.replace(".", "", 1).isdigit() and "-" not in text and "T" not in text:
        return int(float(text))
    # ISO-ish fallback — not used in most OASIS runs
    try:
        from datetime import datetime

        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return 2**62


def tick_index_for_time(t: int, markers: list[dict[str, Any]]) -> int:
    for m in markers:
        start = int(m.get("time_start") or 0)
        end = int(m.get("time_end") or start)
        if start <= t <= end:
            return int(m.get("tick_index") or 0)
    if not markers:
        return 0
    if t < int(markers[0].get("time_start") or 0):
        return -1
    return int(markers[-1].get("tick_index") or 0)


def _tick_index_for_item(
    item: dict[str, Any],
    markers: list[dict[str, Any]],
    *,
    fallback: int,
) -> int:
    if not markers:
        return fallback
    t = _sort_key_from_created_at(item.get("created_at"))
    idx = tick_index_for_time(t, markers)
    return fallback if idx < 0 else idx


def _agent_name(bundle: RunBundle, user_id: int) -> str:
    for a in bundle.agents:
        if a.get("index") == user_id:
            return str(a.get("member_name") or a.get("username") or f"agent {user_id}")
    return f"agent {user_id}"


def _parse_trace_info(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def build_tick_stats(bundle: RunBundle) -> list[TickStatsRow]:
    markers = list(bundle.tick_markers or [])
    posts = list(bundle.posts or [])
    comments = list(bundle.comments or [])
    measurements_by_index = {
        int(row.get("tick_index") or 0): row for row in (bundle.measurements or [])
    }

    if markers:
        tick_count = len(markers)
        posts_by_tick: dict[int, list[dict[str, Any]]] = {i: [] for i in range(tick_count)}
        for post in posts:
            idx = _tick_index_for_item(post, markers, fallback=0)
            if 0 <= idx < tick_count:
                posts_by_tick[idx].append(post)
        comments_by_tick: dict[int, list[dict[str, Any]]] = {i: [] for i in range(tick_count)}
        for comment in comments:
            idx = _tick_index_for_item(comment, markers, fallback=0)
            if 0 <= idx < tick_count:
                comments_by_tick[idx].append(comment)
    else:
        tick_count = max(1, int(bundle.ticks_run or 0))
        buckets = _bucket_posts(posts, tick_count) if posts else [[] for _ in range(tick_count)]
        posts_by_tick = {i: buckets[i] if i < len(buckets) else [] for i in range(tick_count)}
        comments_by_tick = {
            i: _comments_for_posts(comments, posts_by_tick[i]) for i in range(tick_count)
        }
        markers = [
            {
                "tick_index": i,
                "day": i + 1,
                "silent": False,
                "key": f"tick-{i}",
                "rounds": 1,
            }
            for i in range(tick_count)
        ]

    rows: list[TickStatsRow] = []
    cumulative_posts: list[dict[str, Any]] = []
    cumulative_comments: list[dict[str, Any]] = []

    for i, marker in enumerate(markers):
        tick_posts = posts_by_tick.get(i, [])
        tick_comments = comments_by_tick.get(i, [])
        cumulative_posts.extend(tick_posts)
        cumulative_comments.extend(tick_comments)

        window_eng = _engagement(tick_posts, tick_comments)
        cumulative_eng = _engagement(cumulative_posts, cumulative_comments)
        meas = measurements_by_index.get(i) or {}
        points = list(meas.get("points") or [])

        rows.append(
            TickStatsRow(
                tick_index=int(marker.get("tick_index") if marker.get("tick_index") is not None else i),
                day=int(marker.get("day") or i + 1),
                silent=bool(marker.get("silent")),
                key=str(marker.get("key") or f"tick-{i}"),
                rounds=int(marker.get("rounds") or 1),
                window_posts=window_eng["posts"],
                window_comments=window_eng["comments"],
                window_likes=window_eng["likes"],
                window_shares=window_eng["shares"],
                window_dislikes=window_eng["dislikes"],
                window_engagement_score=window_eng["engagement_score"],
                cumulative_posts=cumulative_eng["posts"],
                cumulative_comments=cumulative_eng["comments"],
                cumulative_likes=cumulative_eng["likes"],
                cumulative_engagement_score=cumulative_eng["engagement_score"],
                measurement_points=points,
            )
        )
    return rows


def extract_interview_qa(bundle: RunBundle) -> list[InterviewQA]:
    markers = list(bundle.tick_markers or [])
    out: list[InterviewQA] = []
    for row in bundle.trace or []:
        if str(row.get("action") or "").strip().lower() != "interview":
            continue
        info = _parse_trace_info(row.get("info"))
        prompt = str(info.get("prompt") or info.get("question") or "").strip()
        response = str(info.get("response") or info.get("answer") or "").strip()
        if not prompt and not response:
            continue
        user_id = int(row.get("user_id") or -1)
        t = _sort_key_from_created_at(row.get("created_at"))
        tick_index = tick_index_for_time(t, markers) if markers else 0
        if tick_index < 0:
            tick_index = 0
        day = 1
        if markers and 0 <= tick_index < len(markers):
            day = int(markers[tick_index].get("day") or tick_index + 1)
        out.append(
            InterviewQA(
                tick_index=tick_index,
                day=day,
                user_id=user_id,
                agent_name=_agent_name(bundle, user_id),
                question=prompt or "—",
                answer=response or "—",
            )
        )
    out.sort(key=lambda q: (q.tick_index, q.agent_name, q.question))
    return out
