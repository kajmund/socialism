"""Generation-prefixed PCM frames for live-speech downlink audio."""

from __future__ import annotations

import struct

_HEADER = struct.Struct(">I")


def frame_pcm(generation: int, pcm: bytes) -> bytes:
    return _HEADER.pack(generation) + pcm


def unframe_pcm(payload: bytes) -> tuple[int, bytes] | None:
    if len(payload) < _HEADER.size:
        return None
    generation = _HEADER.unpack_from(payload)[0]
    return generation, payload[_HEADER.size :]
