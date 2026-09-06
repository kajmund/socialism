import pytest

from lagen_nu_mcp.config import ConfigError, load_settings


def test_load_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("LAGEN_NU_FEED_MODE", raising=False)
    monkeypatch.delenv("LAGEN_NU_MIN_INTERVAL_SECONDS", raising=False)
    settings = load_settings()
    assert settings.feed_mode == "roots"
    assert settings.min_interval_seconds == 1.0
    assert settings.database_url is None


def test_require_database_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_settings(require_database=True)


def test_invalid_feed_mode_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAGEN_NU_FEED_MODE", "maybe")
    with pytest.raises(ConfigError, match="roots"):
        load_settings()
