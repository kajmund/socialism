"""Application cursor over a frozen BM25 candidate list.

This is a replay of an already-computed ranking, not a streaming database
latency test. It exists to prove incremental consumption, cancellation, and
resume without duplicating TextUnits.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

PAGE_SIZE = 20
CANDIDATE_BUDGET_EXHAUSTED = "candidate_budget_exhausted"
LEXICAL_MATCHES_EXHAUSTED = "lexical_matches_exhausted"
CANCELLED = "cancelled"
ERROR = "error"
STOP_REASONS = (
    CANDIDATE_BUDGET_EXHAUSTED,
    LEXICAL_MATCHES_EXHAUSTED,
    CANCELLED,
    ERROR,
)


@dataclass(frozen=True)
class FrozenCandidateList:
    experiment_id: str
    query_id: str
    query: str
    strategy: str
    index_snapshot_hash: str
    strategy_config_hash: str
    entries: tuple[dict[str, object], ...]
    scope: str = "global"

    @property
    def query_hash(self) -> str:
        return _hash_text(self.query)

    @property
    def ranking_hash(self) -> str:
        rows = [
            f"{entry.get('rank')}\0{entry.get('key')}\0{entry.get('score')}"
            for entry in self.entries
        ]
        return _hash_text("\n".join(rows))

    def cursor(self, *, page_size: int = PAGE_SIZE) -> Cursor:
        return Cursor(
            experiment_id=self.experiment_id,
            query_hash=self.query_hash,
            index_snapshot_hash=self.index_snapshot_hash,
            strategy_config_hash=self.strategy_config_hash,
            ranking_hash=self.ranking_hash,
            next_position=0,
            page_size=page_size,
        )


@dataclass(frozen=True)
class Cursor:
    experiment_id: str
    query_hash: str
    index_snapshot_hash: str
    strategy_config_hash: str
    ranking_hash: str
    next_position: int
    page_size: int = PAGE_SIZE

    def validate(self, frozen: FrozenCandidateList) -> None:
        if self.experiment_id != frozen.experiment_id:
            raise ValueError("cursor experiment mismatch")
        if self.query_hash != frozen.query_hash:
            raise ValueError("cursor query mismatch")
        if self.index_snapshot_hash != frozen.index_snapshot_hash:
            raise ValueError("cursor index snapshot mismatch")
        if self.strategy_config_hash != frozen.strategy_config_hash:
            raise ValueError("cursor strategy configuration mismatch")
        if self.ranking_hash != frozen.ranking_hash:
            raise ValueError("cursor ranking hash mismatch")
        if self.next_position < 0 or self.next_position > len(frozen.entries):
            raise ValueError("cursor position is outside the frozen list")
        if self.page_size < 1:
            raise ValueError("cursor page size must be >= 1")


@dataclass(frozen=True)
class Page:
    entries: tuple[dict[str, object], ...]
    cursor: Cursor
    returned: int
    unique_documents: int
    new_documents: int
    relevant_documents: int
    stop_reason: str | None
    replay: bool = True


@dataclass(frozen=True)
class PageStats:
    page: int
    returned: int
    unique_documents: int
    new_documents: int
    relevant_documents: int
    next_position: int
    stop_reason: str | None


def consume_page(
    frozen: FrozenCandidateList,
    cursor: Cursor,
    *,
    relevant_paths: Iterable[str] = (),
    seen_documents: Iterable[str] = (),
) -> Page:
    cursor.validate(frozen)
    start = cursor.next_position
    end = min(start + cursor.page_size, len(frozen.entries))
    entries = frozen.entries[start:end]
    paths = {str(entry.get("relative_path") or "") for entry in entries}
    known = set(seen_documents)
    relevant = set(relevant_paths)
    next_cursor = Cursor(
        experiment_id=cursor.experiment_id,
        query_hash=cursor.query_hash,
        index_snapshot_hash=cursor.index_snapshot_hash,
        strategy_config_hash=cursor.strategy_config_hash,
        ranking_hash=cursor.ranking_hash,
        next_position=end,
        page_size=cursor.page_size,
    )
    stop = _stop_reason(frozen, next_cursor, cursor)
    return Page(
        entries=entries,
        cursor=next_cursor,
        returned=len(entries),
        unique_documents=len(paths),
        new_documents=len(paths - known),
        relevant_documents=len(paths & relevant),
        stop_reason=stop,
    )


def consume_all(
    frozen: FrozenCandidateList,
    *,
    page_size: int = PAGE_SIZE,
    relevant_paths: Iterable[str] = (),
    cancel_after_pages: int | None = None,
) -> tuple[list[PageStats], set[str], str | None]:
    cursor = frozen.cursor(page_size=page_size)
    seen: set[str] = set()
    processed: set[str] = set()
    stats: list[PageStats] = []
    reason: str | None = None
    page_number = 0
    while True:
        page = consume_page(
            frozen,
            cursor,
            relevant_paths=relevant_paths,
            seen_documents=seen,
        )
        for entry in page.entries:
            key = str(entry.get("key") or "")
            if key in processed:
                raise RuntimeError(f"duplicate TextUnit in paging replay: {key}")
            processed.add(key)
        seen.update(str(entry.get("relative_path") or "") for entry in page.entries)
        if page.returned == 0:
            reason = page.stop_reason
            break
        stats.append(
            PageStats(
                page=page_number,
                returned=page.returned,
                unique_documents=page.unique_documents,
                new_documents=page.new_documents,
                relevant_documents=page.relevant_documents,
                next_position=page.cursor.next_position,
                stop_reason=page.stop_reason,
            )
        )
        page_number += 1
        reason = page.stop_reason
        cursor = page.cursor
        if cancel_after_pages is not None and page_number >= cancel_after_pages:
            reason = CANCELLED
            break
    return stats, processed, reason


def candidate_list_from_arm(
    *,
    experiment_id: str,
    query_id: str,
    query: str,
    strategy: str,
    index_snapshot_hash: str,
    strategy_config: dict[str, object],
    hits: list[dict[str, object]],
    scope: str = "global",
) -> FrozenCandidateList:
    entries = tuple(
        {
            "rank": int(hit.get("rank") or index + 1),
            "key": str(hit.get("key") or ""),
            "relative_path": str(hit.get("relative_path") or ""),
            "document_id": str(hit.get("document_id") or ""),
            "score": float(hit.get("score") or 0.0),
            "branch": hit.get("branch") or {},
            "label": hit.get("label") or "",
        }
        for index, hit in enumerate(hits)
    )
    return FrozenCandidateList(
        experiment_id=experiment_id,
        query_id=query_id,
        query=query,
        strategy=strategy,
        index_snapshot_hash=index_snapshot_hash,
        strategy_config_hash=_hash_json(strategy_config),
        entries=entries,
        scope=scope,
    )


def _stop_reason(
    frozen: FrozenCandidateList,
    next_cursor: Cursor,
    previous: Cursor,
) -> str | None:
    if next_cursor.next_position >= len(frozen.entries):
        if frozen.strategy == "bm25":
            return LEXICAL_MATCHES_EXHAUSTED
        return CANDIDATE_BUDGET_EXHAUSTED
    if next_cursor.next_position == previous.next_position:
        return ERROR
    return None


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_json(value: object) -> str:
    return _hash_text(json.dumps(value, ensure_ascii=False, sort_keys=True))
