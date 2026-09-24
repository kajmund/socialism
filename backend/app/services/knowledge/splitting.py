"""Sentence-safe size splitting inside an already chosen structural unit."""

from __future__ import annotations

import re
from collections.abc import Sequence

_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?…])\s+")


def split_structured(text: str, target: int, max_chars: int) -> list[str]:
    if len(text) <= target:
        return [text]
    paragraphs = [part for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) > 1:
        return pack_parts(paragraphs, target, max_chars, sep="\n\n")
    sentences = [part.strip() for part in _SENTENCE_BOUNDARY.split(text) if part.strip()]
    if len(sentences) > 1:
        return pack_parts(sentences, target, max_chars, sep=" ")
    lines = text.split("\n")
    if len(lines) > 1:
        return pack_parts(lines, target, max_chars, sep="\n")
    return split_words(text, target, max_chars)


def pack_parts(parts: Sequence[str], target: int, max_chars: int, *, sep: str) -> list[str]:
    out: list[str] = []
    buf: list[str] = []

    def buffered_len() -> int:
        if not buf:
            return 0
        return sum(len(part) for part in buf) + len(sep) * (len(buf) - 1)

    for part in parts:
        stripped = part.strip() if sep == "\n\n" else part
        if not stripped:
            continue
        if len(stripped) > target and not buf:
            if sep == "\n\n":
                out.extend(split_structured(stripped, target, max_chars))
            elif "\n" in stripped:
                out.extend(pack_parts(stripped.split("\n"), target, max_chars, sep="\n"))
            else:
                out.extend(split_words(stripped, target, max_chars))
            continue
        if buf and buffered_len() + len(sep) + len(stripped) > target:
            out.append(sep.join(buf))
            buf = [stripped]
        else:
            buf.append(stripped)
    if buf:
        out.append(sep.join(buf))
    return out


def split_words(text: str, target: int, max_chars: int) -> list[str]:
    words = text.split(" ")
    out: list[str] = []
    buf: list[str] = []
    for word in words:
        if not buf:
            if len(word) > max_chars:
                out.extend(hard_split(word, max_chars))
                continue
            buf = [word]
            continue
        candidate = " ".join([*buf, word])
        if len(candidate) > target:
            out.append(" ".join(buf))
            if len(word) > max_chars:
                out.extend(hard_split(word, max_chars))
                buf = []
            else:
                buf = [word]
        else:
            buf.append(word)
    if buf:
        out.append(" ".join(buf))
    return out


def hard_split(text: str, max_chars: int) -> list[str]:
    return [text[index : index + max_chars] for index in range(0, len(text), max_chars)]
