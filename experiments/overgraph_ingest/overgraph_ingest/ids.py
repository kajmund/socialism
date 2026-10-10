"""Deterministic node identities. Content hash is stored separately from ids."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_hex(*parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> str:
    return hash_bytes(path.read_bytes())


def normalize_text(text: str) -> str:
    return " ".join(text.split())


def content_hash(text: str) -> str:
    return hash_bytes(normalize_text(text).encode("utf-8"))


def document_id(collection_id: str, relative_path: str) -> str:
    return sha256_hex(collection_id, relative_path)


def document_version_id(doc_id: str, source_hash: str) -> str:
    return sha256_hex(doc_id, source_hash)


def structure_id(version_id: str, structure_path: str) -> str:
    return sha256_hex(version_id, structure_path)


def text_unit_id(
    version_id: str,
    segmentation_version: str,
    char_start: int,
    char_end: int,
) -> str:
    return sha256_hex(
        version_id,
        segmentation_version,
        str(char_start),
        str(char_end),
    )
