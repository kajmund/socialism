"""Retrieval gold: relevant TextUnits and hard negatives, matched by document + snippet."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GoldSpan:
    relative_path: str
    contains: str
    reason: str | None = None


@dataclass(frozen=True)
class CoverageGroup:
    relative_path: str
    contains: tuple[str, ...]


@dataclass(frozen=True)
class RetrievalGold:
    id: str
    query: str
    relevant_units: list[GoldSpan]
    hard_negatives: list[GoldSpan]
    watch_negatives: list[GoldSpan] = field(default_factory=list)
    notes: str = ""
    classify_question: str = ""
    kind: str = "unit"
    proof_kind: str = "EXISTS"
    coverage_groups: list[CoverageGroup] = field(default_factory=list)
    document_gold: tuple[str, ...] = ()

    @property
    def passage_documents(self) -> list[str]:
        return list(dict.fromkeys(span.relative_path for span in self.relevant_units))

    @property
    def relevant_documents(self) -> list[str]:
        if self.document_gold:
            return list(self.document_gold)
        return self.passage_documents


def load_retrieval_gold(path: Path) -> RetrievalGold:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RetrievalGold(
        id=str(payload["id"]),
        query=str(payload["query"]),
        notes=str(payload.get("notes") or ""),
        classify_question=str(payload.get("classify_question") or ""),
        kind=str(payload.get("kind") or "unit"),
        proof_kind=str(
            payload.get("proof_kind")
            or ("COMPOSITE" if payload.get("kind") == "multi_clause" else "EXISTS")
        ),
        relevant_units=[_span(item) for item in payload.get("relevant_units") or []],
        hard_negatives=[_span(item) for item in payload.get("hard_negatives") or []],
        watch_negatives=[_span(item) for item in payload.get("watch_negatives") or []],
        coverage_groups=[
            CoverageGroup(
                relative_path=str(item["relative_path"]),
                contains=tuple(str(part) for part in item["contains"]),
            )
            for item in payload.get("coverage_groups") or []
        ],
        document_gold=tuple(
            str(path) for path in payload.get("relevant_documents") or []
        ),
    )


def load_gold_suite(directory: Path) -> list[RetrievalGold]:
    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    return [load_retrieval_gold(directory / str(item["path"])) for item in index["golds"]]


def span_matches(text: str, span: GoldSpan) -> bool:
    return span.contains in text


def matching_spans(text: str, relative_path: str, spans: list[GoldSpan]) -> list[GoldSpan]:
    return [
        span
        for span in spans
        if span.relative_path == relative_path and span_matches(text, span)
    ]


def _span(raw: dict[str, object]) -> GoldSpan:
    reason = raw.get("reason")
    return GoldSpan(
        relative_path=str(raw["relative_path"]),
        contains=str(raw["contains"]),
        reason=str(reason) if reason else None,
    )
