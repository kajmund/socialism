"""OASIS environment prompts from the active prompt configuration.

Monkeypatches camel-oasis SocialEnvironment templates for the current process.
Call only when the oasis extra is installed.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from string import Template
from typing import Any

from app.services.prompt_catalog import render_prompt

# Per-task mapping so concurrent OASIS jobs / A/B variants do not clobber names.
_USER_DISPLAY_NAMES: ContextVar[dict[int, str] | None] = ContextVar(
    "oasis_user_display_names", default=None
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


def apply_swedish_social_environment_prompts(prompts: dict[str, str]) -> None:
    """Replace SocialEnvironment feed prompts with configured language templates."""
    from oasis.social_agent import agent_environment as mod

    se = mod.SocialEnvironment
    se.followers_env_template = Template(render_prompt(prompts, "oasis.env.followers"))
    se.follows_env_template = Template(render_prompt(prompts, "oasis.env.follows"))
    se.posts_env_template = Template(render_prompt(prompts, "oasis.env.posts"))
    se.groups_env_template = Template(render_prompt(prompts, "oasis.env.groups"))
    se.env_template = Template(render_prompt(prompts, "oasis.env.main"))

    empty_posts = render_prompt(prompts, "oasis.env.empty_posts")
    empty_groups = render_prompt(prompts, "oasis.env.empty_groups")
    empty_followers = render_prompt(prompts, "oasis.env.empty_followers")
    empty_follows = render_prompt(prompts, "oasis.env.empty_follows")

    async def get_posts_env_sv(self):
        posts = await self.action.refresh()
        if posts["success"]:
            feed = enrich_feed_posts(posts["posts"])
            posts_env = json.dumps(feed, indent=4, ensure_ascii=False)
            posts_env = self.posts_env_template.substitute(posts=posts_env)
        else:
            posts_env = empty_posts
        return posts_env

    async def get_group_env_sv(self):
        groups = await self.action.listen_from_group()
        if groups["success"]:
            all_groups = json.dumps(groups["all_groups"])
            joined_groups = json.dumps(groups["joined_groups"])
            messages = json.dumps(groups["messages"])
            groups_env = self.groups_env_template.substitute(
                all_groups=all_groups,
                joined_groups=joined_groups,
                messages=messages,
            )
        else:
            groups_env = empty_groups
        return groups_env

    async def to_text_prompt_sv(
        self,
        include_posts: bool = True,
        include_followers: bool = True,
        include_follows: bool = True,
    ) -> str:
        followers_env = (
            await self.get_followers_env()
            if include_follows
            else empty_followers
        )
        follows_env = (
            await self.get_follows_env()
            if include_followers
            else empty_follows
        )
        posts_env = await self.get_posts_env() if include_posts else ""

        return self.env_template.substitute(
            followers_env=followers_env,
            follows_env=follows_env,
            posts_env=posts_env,
            groups_env=await self.get_group_env(),
        )

    se.get_posts_env = get_posts_env_sv
    se.get_group_env = get_group_env_sv
    se.to_text_prompt = to_text_prompt_sv
