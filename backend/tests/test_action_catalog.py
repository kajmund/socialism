"""Tests for the OASIS action catalog (single source of truth)."""

from app.services.prompt_catalog import default_prompts
from app.services.simulation.action_catalog import (
    OASIS_ACTION_SPECS,
    comment_engage_trace_actions,
    is_external_tool,
    is_social_tool,
    passive_trace_actions,
    population_action_names,
    population_trace_names,
    post_engage_trace_actions,
    social_tool_trace_names,
    validate_action_rules_cover_population,
)
from app.services.oasis_profiles import population_action_rules


def test_catalog_enum_and_trace_names_unique():
    enum_names = [s.enum_name for s in OASIS_ACTION_SPECS]
    trace_names = [s.trace_name for s in OASIS_ACTION_SPECS]
    assert len(enum_names) == len(set(enum_names))
    assert len(trace_names) == len(set(trace_names))


def test_population_action_names_default_excludes_create_post():
    names = population_action_names()
    assert "CREATE_POST" not in names
    assert "LIKE_POST" in names
    assert "INTERVIEW" not in names
    assert names[0] != "CREATE_POST"


def test_population_action_names_reddit_omits_repost_quote():
    names = population_action_names(platform="reddit")
    assert "REPOST" not in names
    assert "QUOTE_POST" not in names
    assert "LIKE_POST" in names


def test_population_action_names_with_create_post_first():
    names = population_action_names(allow_population_create_post=True)
    assert names[0] == "CREATE_POST"
    reddit = population_action_names(
        allow_population_create_post=True, platform="reddit"
    )
    assert reddit[0] == "CREATE_POST"
    assert "REPOST" not in reddit


def test_engagement_trace_sets_match_legacy():
    assert passive_trace_actions() == frozenset({"do_nothing", "refresh"})
    assert post_engage_trace_actions() == frozenset({"like_post", "dislike_post"})
    assert comment_engage_trace_actions() == frozenset(
        {"like_comment", "dislike_comment", "create_comment"}
    )


def test_social_tool_detection():
    assert is_social_tool("like_post") is True
    assert is_social_tool("CREATE_POST") is True
    assert is_social_tool("interview") is True
    assert is_external_tool("search_duckduckgo") is True
    assert is_external_tool("like_post") is False


def test_social_tool_trace_names_includes_interview():
    names = social_tool_trace_names()
    assert "interview" in names
    assert "like_post" in names


def test_population_trace_names_follow_enum_names():
    twitter = population_trace_names(platform="twitter")
    assert "repost" in twitter
    reddit = population_trace_names(platform="reddit")
    assert "repost" not in reddit


def test_default_sv_action_rules_mention_population_trace_names():
    prompts = default_prompts("sv")
    rules = population_action_rules(prompts=prompts, allow_create_post=False)
    missing = validate_action_rules_cover_population(
        rules, allow_population_create_post=False, platform="twitter"
    )
    # Prompt text uses grouped mentions (like_post / like_comment) — not every
    # optional action appears verbatim; core engagement actions must be present.
    assert "like_post" not in missing
    assert "dislike_post" not in missing
    assert "do_nothing" not in missing
    assert "follow" not in missing
