"""Generic source locators (page / paragraph / line). No domain vocabulary."""

from __future__ import annotations

import re
from collections.abc import Sequence

_LOCATOR = re.compile(r"(page|paragraph|line):(\d+)(?:-(\d+))?")


def parse_locator(locator: str) -> tuple[str, int, int] | None:
    match = _LOCATOR.fullmatch(locator)
    if match is None:
        return None
    start = int(match.group(2))
    end = int(match.group(3) or match.group(2))
    return match.group(1), start, end


def page_from_locator(locator: str | None) -> int | None:
    parsed = parse_locator(locator) if locator else None
    if parsed is None or parsed[0] != "page":
        return None
    return parsed[1]


def merge_locators(locators: Sequence[str | None]) -> str | None:
    values = [locator for locator in locators if locator]
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    parsed = [parse_locator(value) for value in values]
    if any(item is None for item in parsed):
        return values[0]
    kinds = {item[0] for item in parsed if item is not None}
    if len(kinds) != 1:
        return values[0]
    kind = next(iter(kinds))
    starts = [item[1] for item in parsed if item is not None]
    ends = [item[2] for item in parsed if item is not None]
    low, high = min(starts), max(ends)
    if low == high:
        return f"{kind}:{low}"
    return f"{kind}:{low}-{high}"
