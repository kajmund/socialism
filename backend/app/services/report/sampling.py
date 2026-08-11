"""Stratified reaction sampling for report SSR classification."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from app.services.report.bundles import RunBundle

MAX_CLASSIFY_TEXTS = 16
MAX_TEXTS_PER_AGENT = 2
SAMPLING_METHOD = "stratified_per_agent_v1"
SAMPLING_VERSION = "v1"


@dataclass(frozen=True)
class ReactionRow:
    text: str
    likes: int
    user_id: int


@dataclass(frozen=True)
class SamplingResult:
    texts: list[str]
    likes: list[int]
    user_ids: list[int]
    meta: dict[str, Any]


def _item_likes(item: dict) -> int:
    for key in ("num_likes", "likes", "like_count"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def _injector_user_ids(bundle: RunBundle) -> set[int]:
    out: set[int] = set()
    for agent in bundle.agents:
        if str(agent.get("role") or "") != "injector":
            continue
        try:
            out.add(int(agent.get("index")))
        except (TypeError, ValueError):
            continue
    return out


def _user_id(item: dict) -> int:
    raw = item.get("user_id")
    if raw is None:
        return -1
    return int(raw)


def _collect_reactions(bundle: RunBundle) -> list[ReactionRow]:
    blocked = _injector_user_ids(bundle)
    rows: list[ReactionRow] = []
    for post in bundle.posts:
        text = str(post.get("content") or post.get("text") or "").strip()
        if not text:
            continue
        user_id = _user_id(post)
        if user_id in blocked:
            continue
        rows.append(ReactionRow(text=text, likes=_item_likes(post), user_id=user_id))
    for comment in bundle.comments:
        text = str(comment.get("content") or comment.get("text") or "").strip()
        if not text:
            continue
        user_id = _user_id(comment)
        if user_id in blocked:
            continue
        rows.append(ReactionRow(text=text, likes=_item_likes(comment), user_id=user_id))
    return rows


def sampling_seed(bundle: RunBundle) -> str:
    return "|".join(
        [
            str(bundle.seed or ""),
            str(bundle.attempt_id or ""),
            str(bundle.variant_id or "main"),
        ]
    )


def _cap_round_robin(
    by_agent: dict[int, list[ReactionRow]],
    *,
    limit: int,
    rng: random.Random,
) -> list[ReactionRow]:
    if not by_agent:
        return []
    agents = list(by_agent.keys())
    rng.shuffle(agents)
    selected: list[ReactionRow] = []
    max_rounds = max(len(items) for items in by_agent.values())
    for round_idx in range(max_rounds):
        if len(selected) >= limit:
            break
        round_agents = agents[:]
        rng.shuffle(round_agents)
        for user_id in round_agents:
            if len(selected) >= limit:
                break
            items = by_agent[user_id]
            if round_idx < len(items):
                selected.append(items[round_idx])
    return selected


def sample_reactions_for_ssr(
    bundle: RunBundle,
    *,
    limit: int = MAX_CLASSIFY_TEXTS,
    max_per_agent: int = MAX_TEXTS_PER_AGENT,
    seed: str | None = None,
) -> SamplingResult:
    """Pick reaction texts stratified by agent (seeded), capped for embed cost."""
    rows = _collect_reactions(bundle)
    eligible_count = len(rows)
    seed_text = seed if seed is not None else sampling_seed(bundle)
    rng = random.Random(seed_text)

    if eligible_count <= limit:
        selected = rows
    else:
        by_agent: dict[int, list[ReactionRow]] = {}
        for row in rows:
            by_agent.setdefault(row.user_id, []).append(row)
        for user_id in by_agent:
            items = by_agent[user_id][:]
            rng.shuffle(items)
            by_agent[user_id] = items[:max_per_agent]
        selected = _cap_round_robin(by_agent, limit=limit, rng=rng)

    agent_count = len({row.user_id for row in rows})
    meta = {
        "method": SAMPLING_METHOD,
        "version": SAMPLING_VERSION,
        "max_texts": limit,
        "max_per_agent": max_per_agent,
        "seed": seed_text,
        "eligible_count": eligible_count,
        "selected_count": len(selected),
        "agent_count": agent_count,
    }
    return SamplingResult(
        texts=[row.text for row in selected],
        likes=[row.likes for row in selected],
        user_ids=[row.user_id for row in selected],
        meta=meta,
    )
