"""Coverage-preserving splits: slices concatenate back to the original text."""

from __future__ import annotations

import re

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+")


def covering_ranges(text: str, target: int, max_chars: int) -> list[tuple[int, int]]:
    if not text:
        return []
    if target < 1:
        raise ValueError("target must be >= 1")
    if max_chars < target:
        raise ValueError("max_chars must be >= target")
    ranges = _split_span(text, 0, len(text), target, max_chars)
    _assert_cover(text, ranges)
    return ranges


def _split_span(text: str, lo: int, hi: int, target: int, max_chars: int) -> list[tuple[int, int]]:
    if hi <= lo:
        return []
    if hi - lo <= target:
        return [(lo, hi)]
    starts = _paragraph_starts(text, lo, hi)
    if len(starts) > 1:
        packed = _pack(text, starts + [hi], target, max_chars, "paragraph")
        if packed:
            return packed
    starts = _regex_starts(text, lo, hi, _SENTENCE_BOUNDARY)
    if len(starts) > 1:
        packed = _pack(text, starts + [hi], target, max_chars, "sentence")
        if packed:
            return packed
    starts = _char_starts(text, lo, hi, "\n")
    if len(starts) > 1:
        packed = _pack(text, starts + [hi], target, max_chars, "line")
        if packed:
            return packed
    starts = _char_starts(text, lo, hi, " ")
    if len(starts) > 1:
        packed = _pack(text, starts + [hi], target, max_chars, "word")
        if packed:
            return packed
    return _hard_split(lo, hi, max_chars)


def _pack(
    text: str,
    points: list[int],
    target: int,
    max_chars: int,
    kind: str,
) -> list[tuple[int, int]]:
    del kind
    out: list[tuple[int, int]] = []
    start = points[0]
    last = points[0]
    for end in points[1:]:
        if end - start <= target:
            last = end
            continue
        if last > start:
            out.append((start, last))
            start = last
        if end - start > target:
            out.extend(_subdivide(text, start, end, target, max_chars))
            start = end
            last = end
        else:
            last = end
    if start < points[-1]:
        out.append((start, points[-1]))
    return out


def _subdivide(text: str, lo: int, hi: int, target: int, max_chars: int) -> list[tuple[int, int]]:
    if hi - lo <= target:
        return [(lo, hi)]
    return _split_span(text, lo, hi, target, max_chars)


def _paragraph_starts(text: str, lo: int, hi: int) -> list[int]:
    starts = [lo]
    for match in re.finditer(r"\n[ \t]*\n+", text[lo:hi]):
        pos = lo + match.end()
        if lo < pos < hi:
            starts.append(pos)
    return starts


def _regex_starts(text: str, lo: int, hi: int, pattern: re.Pattern[str]) -> list[int]:
    starts = [lo]
    for match in pattern.finditer(text, lo, hi):
        if lo < match.end() < hi:
            starts.append(match.end())
    return starts


def _char_starts(text: str, lo: int, hi: int, separator: str) -> list[int]:
    starts = [lo]
    idx = text.find(separator, lo, hi)
    while idx != -1 and idx + 1 < hi:
        starts.append(idx + 1)
        idx = text.find(separator, idx + 1, hi)
    return starts


def _hard_split(lo: int, hi: int, max_chars: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    pos = lo
    while pos < hi:
        end = min(pos + max_chars, hi)
        ranges.append((pos, end))
        pos = end
    return ranges


def _assert_cover(text: str, ranges: list[tuple[int, int]]) -> None:
    if not ranges:
        raise ValueError("split produced no ranges")
    if ranges[0][0] != 0 or ranges[-1][1] != len(text):
        raise ValueError("split does not cover the full text")
    for index, (start, end) in enumerate(ranges):
        if start >= end:
            raise ValueError("empty split range")
        if index and start != ranges[index - 1][1]:
            raise ValueError("split ranges have a gap or overlap")
