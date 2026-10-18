"""Stable internal ID scheme for the truth model.

Every entity gets a stable, deterministic ID. IDs are never reused and are
independent of document file names (which may not leak the answer).
"""
from __future__ import annotations


def _seq_id(prefix: str, n: int, width: int = 3) -> str:
    return f"{prefix}-{n:0{width}d}"


class IdCounter:
    def __init__(self, prefix: str, start: int = 1, width: int = 3):
        self.prefix = prefix
        self.n = start
        self.width = width

    def next(self) -> str:
        out = _seq_id(self.prefix, self.n, self.width)
        self.n += 1
        return out
