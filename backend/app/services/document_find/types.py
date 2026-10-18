"""Result and metric types for document find."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Strategy = Literal["category", "hybrid", "category_hybrid", "relation"]
Completeness = Literal["complete", "partial", "uncertain"]
ScopedMode = Literal["scoped_from_category", "scoped_per_document", "global_post_filter"]


@dataclass
class OpCounters:
    embedding_calls: int = 0
    jev_calls: int = 0
    llm_calls: int = 0
    text_unit_reads: int = 0
    category_lookups: int = 0
    vector_searches: int = 0
    neighbor_lookups: int = 0

    def add(self, other: OpCounters) -> OpCounters:
        return OpCounters(
            embedding_calls=self.embedding_calls + other.embedding_calls,
            jev_calls=self.jev_calls + other.jev_calls,
            llm_calls=self.llm_calls + other.llm_calls,
            text_unit_reads=self.text_unit_reads + other.text_unit_reads,
            category_lookups=self.category_lookups + other.category_lookups,
            vector_searches=self.vector_searches + other.vector_searches,
            neighbor_lookups=self.neighbor_lookups + other.neighbor_lookups,
        )


@dataclass(frozen=True)
class FindResult:
    document_ids: tuple[str, ...]
    strategy: Strategy
    completeness: Completeness
    counters: OpCounters = field(default_factory=OpCounters)
    db_ms: float = 0.0
    total_ms: float = 0.0
    notes: tuple[str, ...] = ()
