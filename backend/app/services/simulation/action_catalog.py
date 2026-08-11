"""Single source of truth for OASIS ActionType names and trace.action strings.

Every population action, trace label, and social-vs-external tool distinction
must derive from this module — not duplicated in oasis_run, oasis_tool_trace,
or oasis_engagement.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.schemas.domain import OasisPlatform


class EngagementKind(Enum):
    NONE = "none"
    PASSIVE = "passive"
    POST_ENGAGE = "post_engage"
    COMMENT_ENGAGE = "comment_engage"


@dataclass(frozen=True, slots=True)
class OasisActionSpec:
    """One OASIS social action as used by camel-oasis and our trace readback."""

    enum_name: str
    trace_name: str
    twitter: bool
    reddit: bool
    population: bool
    create_post_optional: bool = False
    manual_only: bool = False
    engagement: EngagementKind = EngagementKind.NONE


# Order preserved for stable population_action_names() output (Twitter base list).
OASIS_ACTION_SPECS: tuple[OasisActionSpec, ...] = (
    OasisActionSpec(
        "CREATE_POST",
        "create_post",
        twitter=True,
        reddit=True,
        population=False,
        create_post_optional=True,
    ),
    OasisActionSpec("LIKE_POST", "like_post", True, True, True, engagement=EngagementKind.POST_ENGAGE),
    OasisActionSpec(
        "DISLIKE_POST",
        "dislike_post",
        True,
        True,
        True,
        engagement=EngagementKind.POST_ENGAGE,
    ),
    OasisActionSpec("UNLIKE_POST", "unlike_post", True, True, True),
    OasisActionSpec("UNDO_DISLIKE_POST", "undo_dislike_post", True, True, True),
    OasisActionSpec(
        "CREATE_COMMENT",
        "create_comment",
        True,
        True,
        True,
        engagement=EngagementKind.COMMENT_ENGAGE,
    ),
    OasisActionSpec(
        "LIKE_COMMENT",
        "like_comment",
        True,
        True,
        True,
        engagement=EngagementKind.COMMENT_ENGAGE,
    ),
    OasisActionSpec(
        "DISLIKE_COMMENT",
        "dislike_comment",
        True,
        True,
        True,
        engagement=EngagementKind.COMMENT_ENGAGE,
    ),
    OasisActionSpec("UNLIKE_COMMENT", "unlike_comment", True, True, True),
    OasisActionSpec("UNDO_DISLIKE_COMMENT", "undo_dislike_comment", True, True, True),
    OasisActionSpec("REPOST", "repost", True, False, True),
    OasisActionSpec("QUOTE_POST", "quote_post", True, False, True),
    OasisActionSpec("FOLLOW", "follow", True, True, True),
    OasisActionSpec("UNFOLLOW", "unfollow", True, True, True),
    OasisActionSpec("MUTE", "mute", True, True, True),
    OasisActionSpec("UNMUTE", "unmute", True, True, True),
    OasisActionSpec("SEARCH_USER", "search_user", True, True, True),
    OasisActionSpec("SEARCH_POSTS", "search_posts", True, True, True),
    OasisActionSpec("REPORT_POST", "report_post", True, True, True),
    OasisActionSpec("TREND", "trend", True, True, True),
    OasisActionSpec(
        "DO_NOTHING",
        "do_nothing",
        True,
        True,
        True,
        engagement=EngagementKind.PASSIVE,
    ),
    OasisActionSpec("REFRESH", "refresh", True, True, True, engagement=EngagementKind.PASSIVE),
    OasisActionSpec(
        "INTERVIEW",
        "interview",
        True,
        True,
        population=False,
        manual_only=True,
    ),
)

_ENUM_BY_NAME: dict[str, OasisActionSpec] = {s.enum_name: s for s in OASIS_ACTION_SPECS}
_TRACE_BY_NAME: dict[str, OasisActionSpec] = {s.trace_name: s for s in OASIS_ACTION_SPECS}
_SOCIAL_TRACE_NAMES: frozenset[str] = frozenset(s.trace_name for s in OASIS_ACTION_SPECS)


def _platform_enabled(spec: OasisActionSpec, platform: OasisPlatform) -> bool:
    return spec.reddit if platform == "reddit" else spec.twitter


def population_action_names(
    *,
    allow_population_create_post: bool = False,
    platform: OasisPlatform = "twitter",
) -> list[str]:
    """Return ActionType names available to population agents.

    INTERVIEW is intentionally omitted — interviews use ManualAction only.
    """
    names: list[str] = []
    for spec in OASIS_ACTION_SPECS:
        if spec.manual_only:
            continue
        if spec.create_post_optional:
            if allow_population_create_post and _platform_enabled(spec, platform):
                names.append(spec.enum_name)
            continue
        if not spec.population or not _platform_enabled(spec, platform):
            continue
        names.append(spec.enum_name)
    return names


def social_tool_trace_names() -> frozenset[str]:
    """Lowercase trace/action names for OASIS social tools (not external CAMEL tools)."""
    return _SOCIAL_TRACE_NAMES


def is_social_tool(tool_name: str) -> bool:
    return tool_name.strip().lower() in _SOCIAL_TRACE_NAMES


def is_external_tool(tool_name: str) -> bool:
    return not is_social_tool(tool_name)


def passive_trace_actions() -> frozenset[str]:
    return frozenset(
        s.trace_name for s in OASIS_ACTION_SPECS if s.engagement is EngagementKind.PASSIVE
    )


def post_engage_trace_actions() -> frozenset[str]:
    return frozenset(
        s.trace_name
        for s in OASIS_ACTION_SPECS
        if s.engagement is EngagementKind.POST_ENGAGE
    )


def comment_engage_trace_actions() -> frozenset[str]:
    return frozenset(
        s.trace_name
        for s in OASIS_ACTION_SPECS
        if s.engagement is EngagementKind.COMMENT_ENGAGE
    )


def population_trace_names(
    *,
    allow_population_create_post: bool = False,
    platform: OasisPlatform = "twitter",
) -> frozenset[str]:
    """Trace names for actions exposed to population agents on a platform."""
    enum_names = population_action_names(
        allow_population_create_post=allow_population_create_post,
        platform=platform,
    )
    return frozenset(_ENUM_BY_NAME[name].trace_name for name in enum_names)


def validate_action_rules_cover_population(
    action_rules_text: str,
    *,
    allow_population_create_post: bool = False,
    platform: OasisPlatform = "twitter",
) -> list[str]:
    """Return trace names missing from prompt action_rules (for admin/seed checks)."""
    text = action_rules_text.casefold()
    missing: list[str] = []
    for trace_name in sorted(
        population_trace_names(
            allow_population_create_post=allow_population_create_post,
            platform=platform,
        )
    ):
        if trace_name not in text:
            missing.append(trace_name)
    return missing
