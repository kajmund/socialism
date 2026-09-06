"""Single settings module. All environment reads happen here."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

FeedMode = Literal["roots", "all"]

DEFAULT_USER_AGENT = (
    "lagen-nu-mcp/0.1 (+https://github.com/kajmund/lagen-nu-mcp; erik@devbrains.se)"
)


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    user_agent: str
    min_interval_seconds: float
    feed_mode: FeedMode
    log_level: str


def load_settings(*, require_database: bool = False) -> Settings:
    raw_mode = os.getenv("LAGEN_NU_FEED_MODE", "roots").strip().lower()
    if raw_mode not in ("roots", "all"):
        raise ConfigError(
            f"LAGEN_NU_FEED_MODE must be 'roots' or 'all', got {raw_mode!r}"
        )

    interval_raw = os.getenv("LAGEN_NU_MIN_INTERVAL_SECONDS", "1.0")
    try:
        interval = float(interval_raw)
    except ValueError as exc:
        raise ConfigError(
            f"LAGEN_NU_MIN_INTERVAL_SECONDS must be a number, got {interval_raw!r}"
        ) from exc
    if interval <= 0:
        raise ConfigError("LAGEN_NU_MIN_INTERVAL_SECONDS must be > 0")

    database_url = os.getenv("DATABASE_URL")
    if require_database and not database_url:
        raise ConfigError("DATABASE_URL is required for postgres store")

    mode: FeedMode = "all" if raw_mode == "all" else "roots"
    return Settings(
        database_url=database_url,
        user_agent=os.getenv("LAGEN_NU_USER_AGENT", DEFAULT_USER_AGENT),
        min_interval_seconds=interval,
        feed_mode=mode,
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
