"""Stratified reaction sampling for report SSR classification."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Literal

from app.services.report.bundles import RunBundle

TopicStatus = Literal["on_topic", "drifted"]

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
class ReceptionDiscussionSplit:
    reception: tuple[ReactionRow, ...]
    discussion: tuple[ReactionRow, ...]
    injection_post_ids: frozenset[int]
    discussion_post_ids: frozenset[int]
    post_topic_status: dict[int, TopicStatus]


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


def _post_id(item: dict) -> int | None:
    raw = item.get("post_id")
    if raw is None:
        return None
    return int(raw)


def post_body_text(item: dict) -> str:
    """Visible post body: quote line plus content (matches run_measurements / OASIS readback)."""
    quote = str(item.get("quote_content") or "").strip()
    content = str(item.get("content") or item.get("text") or "").strip()
    return f"{quote}\n{content}".strip()


def _reaction_row(item: dict) -> ReactionRow | None:
    text = post_body_text(item)
    if not text:
        return None
    return ReactionRow(text=text, likes=_item_likes(item), user_id=_user_id(item))


def injection_post_ids(bundle: RunBundle) -> frozenset[int]:
    """Posts authored by injectors plus repost/quote posts targeting them."""
    injectors = _injector_user_ids(bundle)
    ids: set[int] = set()
    for post in bundle.posts:
        post_id = _post_id(post)
        if post_id is None:
            continue
        if _user_id(post) in injectors:
            ids.add(post_id)
    for post in bundle.posts:
        post_id = _post_id(post)
        original_id = post.get("original_post_id")
        if post_id is None or original_id is None:
            continue
        if int(original_id) in ids:
            ids.add(post_id)
    return frozenset(ids)


def discussion_post_ids(bundle: RunBundle) -> frozenset[int]:
    """Citizen-authored posts that are not reposts/quotes of injection posts."""
    injectors = _injector_user_ids(bundle)
    injection_ids = injection_post_ids(bundle)
    ids: set[int] = set()
    for post in bundle.posts:
        post_id = _post_id(post)
        if post_id is None:
            continue
        if _user_id(post) in injectors:
            continue
        original_id = post.get("original_post_id")
        if original_id is not None and int(original_id) in injection_ids:
            continue
        ids.add(post_id)
    return frozenset(ids)


def _comment_topic_status(
    parent_id: int,
    post_topic_status: dict[int, TopicStatus],
    injection_ids: frozenset[int],
) -> TopicStatus | None:
    if parent_id in injection_ids:
        return "on_topic"
    return post_topic_status.get(parent_id)


def reception_vs_discussion_rows(
    bundle: RunBundle,
    *,
    post_topic_status: dict[int, TopicStatus] | None = None,
    locale: str = "sv",
) -> ReceptionDiscussionSplit:
    """Split reactions by per-post topic status (comments inherit parent post)."""
    injection_ids = injection_post_ids(bundle)
    if post_topic_status is None:
        from app.services.report.classify import classify_post_topics, topic_packs_from_injections

        packs = topic_packs_from_injections(bundle.injection_texts, locale=locale)  # type: ignore[arg-type]
        post_topic_status = classify_post_topics(bundle, packs, locale=locale)  # type: ignore[arg-type]

    blocked = _injector_user_ids(bundle)
    discussion_ids = discussion_post_ids(bundle)
    reception: list[ReactionRow] = []
    discussion: list[ReactionRow] = []

    for post in bundle.posts:
        if _user_id(post) in blocked:
            continue
        post_id = _post_id(post)
        if post_id is None or post_id not in post_topic_status:
            continue
        row = _reaction_row(post)
        if row is None:
            continue
        if post_topic_status[post_id] == "on_topic":
            reception.append(row)
        else:
            discussion.append(row)

    for comment in bundle.comments:
        if _user_id(comment) in blocked:
            continue
        parent_id = _post_id(comment)
        if parent_id is None:
            continue
        row = _reaction_row(comment)
        if row is None:
            continue
        status = _comment_topic_status(parent_id, post_topic_status, injection_ids)
        if status is None:
            continue
        if status == "on_topic":
            reception.append(row)
        else:
            discussion.append(row)

    return ReceptionDiscussionSplit(
        reception=tuple(reception),
        discussion=tuple(discussion),
        injection_post_ids=injection_ids,
        discussion_post_ids=discussion_ids,
        post_topic_status=dict(post_topic_status),
    )


def _collect_reactions(bundle: RunBundle) -> list[ReactionRow]:
    split = reception_vs_discussion_rows(bundle)
    return list(split.reception) + list(split.discussion)


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


def _sampling_scope_meta(split: ReceptionDiscussionSplit) -> dict[str, Any]:
    return {
        "reception_eligible_count": len(split.reception),
        "discussion_eligible_count": len(split.discussion),
        "injection_post_count": len(split.injection_post_ids),
        "discussion_post_count": len(split.discussion_post_ids),
    }


def collect_all_reactions_for_ssr(
    bundle: RunBundle,
    *,
    post_topic_status: dict[int, TopicStatus] | None = None,
    locale: str = "sv",
) -> SamplingResult:
    """Return every eligible reception reaction text (no stratified cap)."""
    split = reception_vs_discussion_rows(
        bundle,
        post_topic_status=post_topic_status,
        locale=locale,
    )
    rows = list(split.reception)
    agent_count = len({row.user_id for row in rows})
    meta = {
        "method": "all",
        "version": SAMPLING_VERSION,
        "scope": "reception",
        "max_texts": None,
        "max_per_agent": None,
        "seed": None,
        "eligible_count": len(rows),
        "selected_count": len(rows),
        "agent_count": agent_count,
        **_sampling_scope_meta(split),
    }
    return SamplingResult(
        texts=[row.text for row in rows],
        likes=[row.likes for row in rows],
        user_ids=[row.user_id for row in rows],
        meta=meta,
    )


def sample_reactions_for_ssr(
    bundle: RunBundle,
    *,
    limit: int = MAX_CLASSIFY_TEXTS,
    max_per_agent: int = MAX_TEXTS_PER_AGENT,
    seed: str | None = None,
    post_topic_status: dict[int, TopicStatus] | None = None,
    locale: str = "sv",
) -> SamplingResult:
    """Pick reception reaction texts stratified by agent (seeded), capped for embed cost."""
    split = reception_vs_discussion_rows(
        bundle,
        post_topic_status=post_topic_status,
        locale=locale,
    )
    rows = list(split.reception)
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
        "scope": "reception",
        "max_texts": limit,
        "max_per_agent": max_per_agent,
        "seed": seed_text,
        "eligible_count": eligible_count,
        "selected_count": len(selected),
        "agent_count": agent_count,
        **_sampling_scope_meta(split),
    }
    return SamplingResult(
        texts=[row.text for row in selected],
        likes=[row.likes for row in selected],
        user_ids=[row.user_id for row in selected],
        meta=meta,
    )
