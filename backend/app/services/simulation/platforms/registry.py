"""Resolve platform name to driver implementation."""

from __future__ import annotations

from app.schemas.domain import OasisPlatform
from app.services.simulation.platforms.base import PlatformDriver
from app.services.simulation.platforms.reddit import RedditPlatformDriver
from app.services.simulation.platforms.twitter import TwitterPlatformDriver

_TWITTER = TwitterPlatformDriver()
_REDDIT = RedditPlatformDriver()


def get_platform_driver(platform: OasisPlatform) -> PlatformDriver:
    if platform == "reddit":
        return _REDDIT
    return _TWITTER
