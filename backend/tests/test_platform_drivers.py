"""Unit tests for simulation platform drivers (no live camel-oasis)."""

from pathlib import Path

from app.services.oasis_profiles import OasisAgentProfile, write_reddit_profile_json
from app.services.simulation.platforms import get_platform_driver
from app.services.simulation.platforms.reddit import RedditPlatformDriver
from app.services.simulation.platforms.twitter import TwitterPlatformDriver


def _profile(**kwargs: object) -> OasisAgentProfile:
    defaults = {
        "username": "anna_a",
        "description": "Lärare, 42",
        "user_char": "persona text",
        "persona_id": None,
        "member_name": "Anna Andersson",
    }
    defaults.update(kwargs)
    return OasisAgentProfile(**defaults)  # type: ignore[arg-type]


def test_get_platform_driver_resolves_twitter_and_reddit():
    assert isinstance(get_platform_driver("twitter"), TwitterPlatformDriver)
    assert isinstance(get_platform_driver("reddit"), RedditPlatformDriver)


def test_twitter_driver_writes_csv(tmp_path: Path):
    profiles = [_profile()]
    path, csv_rel, json_rel = TwitterPlatformDriver().write_profiles(profiles, tmp_path)
    assert path.name == "profiles.csv"
    assert csv_rel == str(path)
    assert json_rel is None
    assert "username" in path.read_text(encoding="utf-8")


def test_reddit_driver_writes_json_without_default_mbti(tmp_path: Path):
    profiles = [_profile()]
    path, csv_rel, json_rel = RedditPlatformDriver().write_profiles(profiles, tmp_path)
    assert path.name == "profiles.json"
    assert csv_rel is None
    assert json_rel == str(path)
    text = path.read_text(encoding="utf-8")
    assert "ISFJ" not in text
    assert "mbti" not in text


def test_reddit_profile_json_includes_mbti_when_set(tmp_path: Path):
    profiles = [_profile(mbti="enfp")]
    path = write_reddit_profile_json(profiles, tmp_path / "profiles.json")
    import json

    rows = json.loads(path.read_text(encoding="utf-8"))
    assert rows[0]["mbti"] == "ENFP"
