"""Deterministic query expansion. No LLM. Same lexicon for every gold of a concept."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.retrieval.gold import RetrievalGold

DEFAULT_EXPANSIONS = Path(__file__).resolve().parents[2] / "retrieval_gold" / "expansions.json"
BASELINE = "baseline"
APPEND = "append"
FUSE = "fuse"
VARIANTS = (BASELINE, APPEND, FUSE)


@dataclass(frozen=True)
class Expansion:
    concept: str
    terms: tuple[str, ...]

    def append(self, query: str) -> str:
        extra = [term for term in self.terms if not _has_phrase(query, term)]
        if not extra:
            return query
        return f"{query} {' '.join(extra)}"


def _has_phrase(query: str, term: str) -> bool:
    stripped = "".join(char if char.isalnum() or char.isspace() else " " for char in query.casefold())
    return f" {term.casefold()} " in f" {stripped} "


def load_expansions(path: Path | None = None) -> dict[str, Expansion]:
    payload = json.loads((path or DEFAULT_EXPANSIONS).read_text(encoding="utf-8"))
    concepts = {
        name: tuple(str(term) for term in terms)
        for name, terms in (payload.get("concepts") or {}).items()
    }
    return {
        gold_id: Expansion(concept=concept, terms=concepts[concept])
        for gold_id, concept in (payload.get("golds") or {}).items()
    }


def expansion_for(gold: RetrievalGold, expansions: dict[str, Expansion] | None = None) -> Expansion:
    table = expansions if expansions is not None else load_expansions()
    return table[gold.id]


def query_for(gold: RetrievalGold, variant: str, expansions: dict[str, Expansion] | None = None) -> str:
    if variant == BASELINE:
        return gold.query
    if variant == APPEND:
        return expansion_for(gold, expansions).append(gold.query)
    raise ValueError(f"unsupported query variant {variant!r}")
