"""OASIS environment prompts from the active prompt configuration.

Monkeypatches camel-oasis SocialEnvironment templates for the current process.
Prompt templates are stored per asyncio task (ContextVar) so concurrent OASIS
jobs and A/B variants do not clobber each other.
Call only when the oasis extra is installed.
"""

from __future__ import annotations

import json
import sqlite3
from contextvars import ContextVar
from dataclasses import dataclass
from string import Template
from typing import Any

from app.services.prompt_catalog import render_prompt

# Per-task mapping so concurrent OASIS jobs / A/B variants do not clobber names.
_USER_DISPLAY_NAMES: ContextVar[dict[int, str] | None] = ContextVar(
    "oasis_user_display_names", default=None
)

_SOCIAL_ENV_PATCHED = False


@dataclass(frozen=True)
class _OasisEnvPromptState:
    followers_env_template: Template
    follows_env_template: Template
    posts_env_template: Template
    groups_env_template: Template
    env_template: Template
    empty_posts: str
    empty_groups: str
    empty_followers: str
    empty_follows: str


_OASIS_ENV_PROMPTS: ContextVar[_OasisEnvPromptState | None] = ContextVar(
    "oasis_env_prompts", default=None
)


def set_oasis_user_display_names(mapping: dict[int, str]) -> None:
    """Map OASIS user_id to human-readable names shown in the agent feed."""
    _USER_DISPLAY_NAMES.set({int(k): v for k, v in mapping.items()})


def _display_names() -> dict[int, str]:
    return _USER_DISPLAY_NAMES.get() or {}


def _first_name(display_name: str) -> str:
    token = display_name.strip().split()[0] if display_name.strip() else display_name
    return token


def enrich_feed_posts(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add author_name to posts/comments so agents can attribute speech correctly."""
    names = _display_names()
    if not names:
        return posts
    enriched: list[dict[str, Any]] = []
    for post in posts:
        row = dict(post)
        uid = row.get("user_id")
        if uid is not None:
            display = names.get(int(uid))
            if display:
                row["author_name"] = display
                row["author_first_name"] = _first_name(display)
        comments = row.get("comments")
        if isinstance(comments, list):
            row["comments"] = [
                _enrich_comment(comment, names) for comment in comments
            ]
        enriched.append(row)
    return enriched


def _enrich_comment(comment: dict[str, Any], names: dict[int, str]) -> dict[str, Any]:
    row = dict(comment)
    uid = row.get("user_id")
    if uid is not None:
        display = names.get(int(uid))
        if display:
            row["author_name"] = display
            row["author_first_name"] = _first_name(display)
    return row


def _build_env_prompt_state(prompts: dict[str, str]) -> _OasisEnvPromptState:
    return _OasisEnvPromptState(
        followers_env_template=Template(render_prompt(prompts, "oasis.env.followers")),
        follows_env_template=Template(render_prompt(prompts, "oasis.env.follows")),
        posts_env_template=Template(render_prompt(prompts, "oasis.env.posts")),
        groups_env_template=Template(render_prompt(prompts, "oasis.env.groups")),
        env_template=Template(render_prompt(prompts, "oasis.env.main")),
        empty_posts=render_prompt(prompts, "oasis.env.empty_posts"),
        empty_groups=render_prompt(prompts, "oasis.env.empty_groups"),
        empty_followers=render_prompt(prompts, "oasis.env.empty_followers"),
        empty_follows=render_prompt(prompts, "oasis.env.empty_follows"),
    )


def _env_prompt_state() -> _OasisEnvPromptState:
    state = _OASIS_ENV_PROMPTS.get()
    if state is None:
        raise RuntimeError("OASIS env prompts not set for this task")
    return state


def _ensure_social_environment_patched() -> None:
    global _SOCIAL_ENV_PATCHED
    if _SOCIAL_ENV_PATCHED:
        return

    from oasis.social_agent import agent_environment as mod

    se = mod.SocialEnvironment

    async def get_followers_env_sv(self) -> str:
        from oasis.social_agent.agent_environment import get_db_path

        state = _env_prompt_state()
        agent_id = self.action.agent_id
        try:
            db_path = get_db_path()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT num_followers FROM user WHERE agent_id = ?",
                (agent_id,),
            )
            result = cursor.fetchone()
            num_followers = result[0] if result else 0
            conn.close()
        except Exception:
            num_followers = 0
        return state.followers_env_template.substitute(num_followers=num_followers)

    async def get_follows_env_sv(self) -> str:
        from oasis.social_agent.agent_environment import get_db_path

        state = _env_prompt_state()
        agent_id = self.action.agent_id
        try:
            db_path = get_db_path()
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT num_followings FROM user WHERE agent_id = ?",
                (agent_id,),
            )
            result = cursor.fetchone()
            num_followings = result[0] if result else 0
            conn.close()
        except Exception:
            num_followings = 0
        return state.follows_env_template.substitute(num_follows=num_followings)

    async def get_posts_env_sv(self):
        state = _env_prompt_state()
        posts = await self.action.refresh()
        if posts["success"]:
            feed = enrich_feed_posts(posts["posts"])
            posts_env = json.dumps(feed, indent=4, ensure_ascii=False)
            posts_env = state.posts_env_template.substitute(posts=posts_env)
        else:
            posts_env = state.empty_posts
        return posts_env

    async def get_group_env_sv(self):
        state = _env_prompt_state()
        groups = await self.action.listen_from_group()
        if groups["success"]:
            all_groups = json.dumps(groups["all_groups"])
            joined_groups = json.dumps(groups["joined_groups"])
            messages = json.dumps(groups["messages"])
            groups_env = state.groups_env_template.substitute(
                all_groups=all_groups,
                joined_groups=joined_groups,
                messages=messages,
            )
        else:
            groups_env = state.empty_groups
        return groups_env

    async def to_text_prompt_sv(
        self,
        include_posts: bool = True,
        include_followers: bool = True,
        include_follows: bool = True,
    ) -> str:
        state = _env_prompt_state()
        followers_env = (
            await self.get_followers_env()
            if include_follows
            else state.empty_followers
        )
        follows_env = (
            await self.get_follows_env()
            if include_followers
            else state.empty_follows
        )
        posts_env = await self.get_posts_env() if include_posts else ""

        return state.env_template.substitute(
            followers_env=followers_env,
            follows_env=follows_env,
            posts_env=posts_env,
            groups_env=await self.get_group_env(),
        )

    se.get_followers_env = get_followers_env_sv
    se.get_follows_env = get_follows_env_sv
    se.get_posts_env = get_posts_env_sv
    se.get_group_env = get_group_env_sv
    se.to_text_prompt = to_text_prompt_sv
    _SOCIAL_ENV_PATCHED = True


def apply_swedish_social_environment_prompts(prompts: dict[str, str]) -> None:
    """Bind feed prompt templates for the current asyncio task."""
    _OASIS_ENV_PROMPTS.set(_build_env_prompt_state(prompts))
    _ensure_social_environment_patched()
