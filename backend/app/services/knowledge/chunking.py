"""Structure-preserving chunking for extracted knowledge documents."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from app.services.knowledge.extractors import ExtractedBlock, ExtractedDocument
from app.services.knowledge.models import KnowledgeChunk, KnowledgeDocument

DEFAULT_TARGET_CHARS = 1200
DEFAULT_OVERLAP_CHARS = 200
DEFAULT_MAX_CHARS = 2400


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_chunk_id(
    *,
    document_id: str,
    version: str | None,
    locator: str | None,
    content_hash: str,
) -> str:
    payload = f"{document_id}\0{version or ''}\0{locator or ''}\0{content_hash}".encode()
    return hashlib.sha256(payload).hexdigest()


def merge_locators(locators: Sequence[str | None]) -> str | None:
    values = [locator for locator in locators if locator]
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    parsed = [_parse_locator(value) for value in values]
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


class KnowledgeChunker:
    """Pack extracted blocks to a target size. Prefer block boundaries over char splits."""

    def __init__(
        self,
        *,
        target_chars: int = DEFAULT_TARGET_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        if target_chars < 1:
            raise ValueError("target_chars must be >= 1")
        if overlap_chars < 0:
            raise ValueError("overlap_chars must be >= 0")
        if max_chars < target_chars:
            raise ValueError("max_chars must be >= target_chars")
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars
        self.max_chars = max_chars

    def chunk(
        self,
        extracted: ExtractedDocument,
        document: KnowledgeDocument,
    ) -> list[KnowledgeChunk]:
        pieces = self._pack(extracted.blocks)
        chunks: list[KnowledgeChunk] = []
        previous_unique = ""
        for text, locator in pieces:
            combined = _apply_overlap(previous_unique, text, self.overlap_chars)
            chunks.append(self._to_chunk(document, combined, locator))
            previous_unique = text
        return chunks

    def _to_chunk(
        self,
        document: KnowledgeDocument,
        text: str,
        locator: str | None,
    ) -> KnowledgeChunk:
        customer_id = document.scope.customer_id
        if customer_id is None:
            raise ValueError("KnowledgeChunker requires document.scope.customer_id")
        digest = hash_text(text)
        chunk_id = make_chunk_id(
            document_id=document.document_id,
            version=document.version,
            locator=locator,
            content_hash=digest,
        )
        metadata: dict[str, object] = {
            "document_id": document.document_id,
            "provider": document.provider,
            "version": document.version,
            "customer_id": customer_id,
            "case_id": document.scope.case_id,
            "module": document.scope.module,
            "locator": locator,
            "content_hash": digest,
        }
        return KnowledgeChunk(
            document_id=document.document_id,
            chunk_id=chunk_id,
            text=text,
            customer_id=customer_id,
            case_id=document.scope.case_id,
            module=document.scope.module,
            title=document.title,
            locator=locator,
            provider=document.provider,
            version=document.version,
            content_hash=digest,
            metadata=metadata,
        )

    def _pack(self, blocks: Sequence[ExtractedBlock]) -> list[tuple[str, str | None]]:
        out: list[tuple[str, str | None]] = []
        group: list[ExtractedBlock] = []

        def flush() -> None:
            if not group:
                return
            texts = [block.text.strip() for block in group if block.text.strip()]
            if texts:
                out.append(("\n\n".join(texts), merge_locators([block.locator for block in group])))
            group.clear()

        def grouped_len() -> int:
            texts = [block.text.strip() for block in group if block.text.strip()]
            if not texts:
                return 0
            return sum(len(text) for text in texts) + 2 * (len(texts) - 1)

        for block in blocks:
            text = block.text.strip()
            if not text:
                continue
            if len(text) > self.target_chars:
                flush()
                out.extend(self._split_block(block))
                continue
            if group and grouped_len() + 2 + len(text) > self.target_chars:
                flush()
            group.append(block)
        flush()
        return out

    def _split_block(self, block: ExtractedBlock) -> list[tuple[str, str | None]]:
        parts = _split_structured(block.text.strip(), self.target_chars, self.max_chars)
        parsed = _parse_locator(block.locator) if block.locator else None
        if parsed is None or parsed[0] != "line":
            return [(part, block.locator) for part in parts]
        start = parsed[1]
        pieces: list[tuple[str, str | None]] = []
        cursor = start
        for part in parts:
            end = cursor + part.count("\n")
            locator = f"line:{cursor}" if end == cursor else f"line:{cursor}-{end}"
            pieces.append((part, locator))
            cursor = end + 1
        return pieces


def _apply_overlap(previous: str, current: str, overlap_chars: int) -> str:
    if not previous or overlap_chars <= 0:
        return current
    snippet = previous[-overlap_chars:]
    match = re.search(r"[\n\s]", snippet)
    if match and match.end() < len(snippet):
        snippet = snippet[match.end() :]
    snippet = snippet.strip()
    if not snippet or snippet == current:
        return current
    return f"{snippet}\n{current}"


def _split_structured(text: str, target: int, max_chars: int) -> list[str]:
    if len(text) <= target:
        return [text]
    paragraphs = [part for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) > 1:
        return _pack_parts(paragraphs, target, max_chars, sep="\n\n")
    lines = text.split("\n")
    if len(lines) > 1:
        return _pack_parts(lines, target, max_chars, sep="\n")
    return _split_words(text, target, max_chars)


def _pack_parts(parts: Sequence[str], target: int, max_chars: int, *, sep: str) -> list[str]:
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
                out.extend(_split_structured(stripped, target, max_chars))
            elif "\n" in stripped:
                out.extend(_pack_parts(stripped.split("\n"), target, max_chars, sep="\n"))
            else:
                out.extend(_split_words(stripped, target, max_chars))
            continue
        if buf and buffered_len() + len(sep) + len(stripped) > target:
            out.append(sep.join(buf))
            buf = [stripped]
        else:
            buf.append(stripped)
    if buf:
        out.append(sep.join(buf))
    return out


def _split_words(text: str, target: int, max_chars: int) -> list[str]:
    words = text.split(" ")
    out: list[str] = []
    buf: list[str] = []
    for word in words:
        if not buf:
            if len(word) > max_chars:
                out.extend(_hard_split(word, max_chars))
                continue
            buf = [word]
            continue
        candidate = " ".join([*buf, word])
        if len(candidate) > target:
            out.append(" ".join(buf))
            if len(word) > max_chars:
                out.extend(_hard_split(word, max_chars))
                buf = []
            else:
                buf = [word]
        else:
            buf.append(word)
    if buf:
        out.append(" ".join(buf))
    return out


def _hard_split(text: str, max_chars: int) -> list[str]:
    return [text[index : index + max_chars] for index in range(0, len(text), max_chars)]


def _parse_locator(locator: str) -> tuple[str, int, int] | None:
    match = re.fullmatch(r"(page|paragraph|line):(\d+)(?:-(\d+))?", locator)
    if match is None:
        return None
    start = int(match.group(2))
    end = int(match.group(3) or match.group(2))
    return match.group(1), start, end
