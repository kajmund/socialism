"""Stratified per-round sampling and budskag engagement rules for OASIS runs.

See knowledge/manual/reaktionsmodell-i-simulering.md for operator-facing docs.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.simulation.action_catalog import (
    comment_engage_trace_actions,
    passive_trace_actions,
    post_engage_trace_actions,
)
from app.services.simulation.artifact.reader import OasisArtifactReader

PASSIVE_ACTIONS = passive_trace_actions()
POST_ENGAGE_ACTIONS = post_engage_trace_actions()
COMMENT_ENGAGE_ACTIONS = comment_engage_trace_actions()

FIRST_ROUND_SAMPLE_FRACTION = 0.6
LATER_ROUND_SAMPLE_FRACTION = 0.35


def sample_fraction(round_index: int) -> float:
    if round_index <= 0:
        return FIRST_ROUND_SAMPLE_FRACTION
    return LATER_ROUND_SAMPLE_FRACTION


def stratified_agent_sample(
    eligible: set[int],
    *,
    strata: dict[int, str],
    fraction: float,
    rng: random.Random,
) -> set[int]:
    """Pick ~fraction of eligible agents, at least one per non-empty stratum when possible."""
    if not eligible or fraction <= 0:
        return set()
    if fraction >= 1:
        return set(eligible)

    by_stratum: dict[str, list[int]] = {}
    for agent_id in eligible:
        key = strata.get(agent_id) or "unknown"
        by_stratum.setdefault(key, []).append(agent_id)

    chosen: set[int] = set()
    for stratum_agents in by_stratum.values():
        stratum_agents = sorted(stratum_agents)
        n = len(stratum_agents)
        target = max(1, int(round(n * fraction)))
        target = min(n, target)
        picked = rng.sample(stratum_agents, target)
        chosen.update(picked)

    cap = max(1, int(round(len(eligible) * fraction)))
    if len(chosen) > cap:
        chosen = set(rng.sample(sorted(chosen), cap))
    return chosen


def build_agent_strata_from_members(
    members: list[Any],
    population_indices: set[int],
) -> dict[int, str]:
    """Stratify population agents by PopulationMember.district."""
    out: dict[int, str] = {}
    pop_list = sorted(population_indices)
    for pop_pos, agent_id in enumerate(pop_list):
        district = "unknown"
        if 0 <= pop_pos < len(members):
            district = (members[pop_pos].district or "").strip() or "unknown"
        out[agent_id] = district
    return out


@dataclass
class StimulusEngagement:
    """Engagement state for the current budskag (injection post thread)."""

    stimulus_post_ids: frozenset[int] = frozenset()
    passive: set[int] = field(default_factory=set)
    engaged: set[int] = field(default_factory=set)

    @property
    def active(self) -> bool:
        return bool(self.stimulus_post_ids)

    def reset_for_stimulus(self, post_ids: set[int] | frozenset[int]) -> None:
        self.stimulus_post_ids = frozenset(int(p) for p in post_ids)
        self.passive = set()
        self.engaged = set()

    def eligible_agents(self, population_indices: set[int]) -> set[int]:
        if not self.active:
            return set(population_indices)
        return {i for i in population_indices if i not in self.passive}

    def may_comment(self, agent_id: int) -> bool:
        if not self.active:
            return True
        return agent_id in self.engaged

    def record_trace_rows(
        self,
        rows: list[dict[str, Any]],
        *,
        comment_to_post: dict[int, int],
    ) -> None:
        for row in rows:
            agent_id = int(row["user_id"])
            action = str(row.get("action") or "").strip().lower()
            info = _parse_info(row.get("info"))

            if action in PASSIVE_ACTIONS:
                if not self.active:
                    continue
                if agent_id not in self.engaged:
                    self.passive.add(agent_id)
                continue

            if self._action_engages(action, info, comment_to_post):
                self.engaged.add(agent_id)
                self.passive.discard(agent_id)

    def _action_engages(
        self,
        action: str,
        info: dict[str, Any],
        comment_to_post: dict[int, int],
    ) -> bool:
        if not self.active:
            return False
        posts = self.stimulus_post_ids
        if action in POST_ENGAGE_ACTIONS:
            post_id = info.get("post_id")
            if post_id is None:
                return False
            return int(post_id) in posts
        if action == "create_comment":
            comment_id = info.get("comment_id")
            if comment_id is None:
                return False
            post_id = comment_to_post.get(int(comment_id))
            return post_id is not None and int(post_id) in posts
        if action in {"like_comment", "dislike_comment"}:
            comment_id = info.get("comment_id")
            if comment_id is None:
                return False
            post_id = comment_to_post.get(int(comment_id))
            return post_id is not None and int(post_id) in posts
        return False


def _parse_info(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    text = str(raw).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _reader(db_path: Path) -> OasisArtifactReader:
    return OasisArtifactReader(db_path)


def max_post_id(db_path: Path) -> int:
    return _reader(db_path).max_post_id()


def injector_post_ids_after(
    db_path: Path,
    *,
    injector_indices: set[int],
    after_post_id: int,
) -> frozenset[int]:
    return _reader(db_path).injector_post_ids_after(
        injector_indices=injector_indices,
        after_post_id=after_post_id,
    )


def trace_row_count(db_path: Path) -> int:
    return _reader(db_path).trace_row_count()


def read_trace_since(db_path: Path, after_count: int) -> list[dict[str, Any]]:
    return _reader(db_path).read_trace_since(after_count)


def comment_post_ids(db_path: Path, comment_ids: set[int]) -> dict[int, int]:
    return _reader(db_path).comment_post_ids(comment_ids)


def comment_ids_from_trace(rows: list[dict[str, Any]]) -> set[int]:
    ids: set[int] = set()
    for row in rows:
        action = str(row.get("action") or "").strip().lower()
        if action not in COMMENT_ENGAGE_ACTIONS:
            continue
        info = _parse_info(row.get("info"))
        cid = info.get("comment_id")
        if cid is not None:
            ids.add(int(cid))
    return ids


def make_round_rng(seed: str, tick_index: int, round_index: int) -> random.Random:
    token = f"{seed}:tick{tick_index}:round{round_index}"
    return random.Random(token)
