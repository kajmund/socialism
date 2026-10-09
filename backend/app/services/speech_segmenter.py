"""Deterministic conversion of streamed markdown text into speakable phrases."""

from __future__ import annotations

import re

_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_CODE = re.compile(r"`([^`]+)`")
_SYMBOLS = re.compile(r"[*_#>|]+")
_VOICE_TAG_NAMES = frozenset(
    {
        "clears throat",
        "crying",
        "curious",
        "laugh",
        "laughs",
        "mischievously",
        "shouts",
        "sighs",
        "whispers",
    }
)
_VOICE_TAG = re.compile(r"\[([a-z ]+)\]", re.IGNORECASE)
_REPEATED_HORIZONTAL_SPACE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"[ \t]+([,.;:!?])")


class VisibleSpeechText:
    """Remove supported v4 delivery tags from streamed display text."""

    def __init__(self) -> None:
        self._buffer = ""
        self._visible_ends_with_space = False

    def push(self, delta: str) -> str:
        self._buffer += delta
        visible: list[str] = []
        while self._buffer:
            start = self._buffer.find("[")
            if start < 0:
                visible.append(self._buffer)
                self._buffer = ""
                break
            visible.append(self._buffer[:start])
            close = self._buffer.find("]", start + 1)
            if close < 0:
                if len(self._buffer) - start <= 32:
                    self._buffer = self._buffer[start:]
                    break
                visible.append("[")
                self._buffer = self._buffer[start + 1 :]
                continue
            candidate = self._buffer[start : close + 1]
            if _is_voice_tag(candidate):
                if self._visible_ends_with_space or (
                    visible and visible[-1].endswith((" ", "\t"))
                ):
                    self._buffer = self._buffer[close + 1 :].lstrip(" \t")
                    continue
            else:
                visible.append(candidate)
            self._buffer = self._buffer[close + 1 :]
        result = "".join(visible)
        if result:
            self._visible_ends_with_space = result.endswith((" ", "\t"))
        return result

    def finish(self) -> str:
        visible = strip_voice_tags(self._buffer)
        self._buffer = ""
        return visible


class SpeechSegmenter:
    def __init__(self, *, first_target: int = 110, max_chars: int = 220) -> None:
        self._buffer = ""
        self._first_target = first_target
        self._max_chars = max_chars
        self._emitted = False
        self._cancelled = False

    def push(self, delta: str) -> list[str]:
        if self._cancelled:
            return []
        self._buffer += delta
        segments: list[str] = []
        while boundary := self._boundary():
            raw, self._buffer = self._buffer[:boundary], self._buffer[boundary:]
            if spoken := normalize_for_speech(raw):
                segments.append(spoken)
                self._emitted = True
        return segments

    def finish(self) -> list[str]:
        if self._cancelled:
            return []
        spoken = normalize_for_speech(self._buffer)
        self._buffer = ""
        return [spoken] if spoken else []

    def cancel(self) -> None:
        self._cancelled = True
        self._buffer = ""

    def _boundary(self) -> int | None:
        target = self._first_target if not self._emitted else self._max_chars
        protected = _protected_ranges(self._buffer)
        for index, character in enumerate(self._buffer):
            end = index + 1
            if _inside(index, protected):
                continue
            if character in ".?!" and end >= 24:
                return end
            if character in ";:" and end >= target:
                return end
        if len(self._buffer) < self._max_chars:
            return None
        for cut in range(min(self._max_chars, len(self._buffer) - 1), 0, -1):
            if self._buffer[cut] == " " and not _inside(cut, protected):
                return cut + 1
        return None


def normalize_for_speech(text: str) -> str:
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    text = _URL.sub(lambda match: match.group(0).rstrip(".,!?"), text)
    text = _SYMBOLS.sub(" ", text)
    return " ".join(text.split())


def strip_voice_tags(text: str) -> str:
    visible = _VOICE_TAG.sub(
        lambda match: "" if match.group(1).casefold() in _VOICE_TAG_NAMES else match.group(0),
        text,
    )
    visible = _REPEATED_HORIZONTAL_SPACE.sub(" ", visible)
    return _SPACE_BEFORE_PUNCTUATION.sub(r"\1", visible).strip()


def _is_voice_tag(text: str) -> bool:
    match = _VOICE_TAG.fullmatch(text)
    return match is not None and match.group(1).casefold() in _VOICE_TAG_NAMES


def _protected_ranges(text: str) -> list[tuple[int, int]]:
    return [
        *(match.span() for match in _MARKDOWN_LINK.finditer(text)),
        *(match.span() for match in _URL.finditer(text)),
        *(match.span() for match in _CODE.finditer(text)),
        *(match.span() for match in _VOICE_TAG.finditer(text) if _is_voice_tag(match.group(0))),
    ]


def _inside(index: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start <= index < stop for start, stop in ranges)
