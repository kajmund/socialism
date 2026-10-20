"""Canonical JSON bytes and SHA-256 for SWD definitions and Jev cache keys.

PR 1 uses this Python encoder as the test oracle. A later Rust crate must
match these bytes; Rust then becomes the normative encoder.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from typing import Any

from app.swe.errors import SwdParseError

CANONICAL_SCHEMA_VERSION = "swd-canonical-json-v1"


def canonical_json_bytes(value: object) -> bytes:
    normalized = _normalize(value)
    text = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return text.encode("utf-8")


def sha256_hex(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _normalize(value: object) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return _normalize_leaf(value)


def _normalize_leaf(value: object) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return _normalize_float(value)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    raise SwdParseError(f"unsupported JSON type {type(value).__name__}")


def _normalize_float(value: float) -> int | float:
    if not math.isfinite(value):
        raise SwdParseError("NaN and Infinity are not allowed in canonical JSON")
    if value.is_integer():
        return int(value)
    return value
