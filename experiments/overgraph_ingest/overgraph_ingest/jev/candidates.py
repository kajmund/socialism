"""Hydrate frozen hybrid candidates from OverGraph without changing retrieval."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.graph.schema import STRUCTURE
from overgraph_ingest.graph.writer import GraphWriter
from overgraph_ingest.retrieval.gold import RetrievalGold, matching_spans
from overgraph_ingest.retrieval.index import StoredUnit, load_published_units


@dataclass(frozen=True)
class FrozenHit:
    key: str
    rank: int
    score: float
    relative_path: str


@dataclass(frozen=True)
class ClassifiedCandidate:
    key: str
    rank: int
    score: float
    relative_path: str
    document_id: str
    text: str
    structure_title: str
    parent_title: str
    parent_text: str
    previous_text: str
    next_text: str
    gold_label: str


def load_frozen_hits(path: Path, *, strategy: str = "hybrid", k: int = 50) -> list[FrozenHit]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    hits = payload["strategies"][strategy]["at_k"][str(k)]["hits"]
    return [
        FrozenHit(
            key=str(item["key"]),
            rank=int(item["rank"]),
            score=float(item["score"]),
            relative_path=str(item["relative_path"]),
        )
        for item in hits
    ]


@dataclass
class GraphContext:
    units: list[StoredUnit]
    structures: dict[str, dict[str, object]]
    neighbors: dict[str, tuple[str, str]]
    parent_texts: dict[str, str]

    def by_key(self) -> dict[str, StoredUnit]:
        return {unit.key: unit for unit in self.units}

    def candidate(
        self,
        unit: StoredUnit,
        gold: RetrievalGold,
        *,
        rank: int,
        score: float,
    ) -> ClassifiedCandidate:
        structure = self.structures.get(unit.structure_id, {})
        parent_id = str(structure.get("parent_id") or "")
        parent = self.structures.get(parent_id, {})
        previous_text, next_text = self.neighbors.get(unit.key, ("", ""))
        return ClassifiedCandidate(
            key=unit.key,
            rank=rank,
            score=score,
            relative_path=unit.relative_path,
            document_id=unit.document_id,
            text=unit.text,
            structure_title=str(structure.get("title") or ""),
            parent_title=str(parent.get("title") or ""),
            parent_text=self.parent_texts.get(parent_id, ""),
            previous_text=previous_text,
            next_text=next_text,
            gold_label=_gold_label(unit, gold),
        )


def load_graph_context(writer: GraphWriter) -> GraphContext:
    units = load_published_units(writer)
    structures = _structures(writer)
    return GraphContext(
        units=units,
        structures=structures,
        neighbors=_neighbors(units),
        parent_texts=_parent_texts(units, structures),
    )


def hydrate_candidates(
    writer: GraphWriter,
    hits: list[FrozenHit],
    gold: RetrievalGold,
) -> list[ClassifiedCandidate]:
    units = load_published_units(writer)
    by_key = {unit.key: unit for unit in units}
    structures = _structures(writer)
    neighbors = _neighbors(units)
    parent_texts = _parent_texts(units, structures)
    hydrated: list[ClassifiedCandidate] = []
    for hit in hits:
        unit = by_key.get(hit.key)
        if unit is None:
            raise KeyError(f"frozen candidate {hit.key} is missing from the database")
        structure = structures.get(unit.structure_id, {})
        parent_id = str(structure.get("parent_id") or "")
        parent = structures.get(parent_id, {})
        previous_text, next_text = neighbors.get(unit.key, ("", ""))
        hydrated.append(
            ClassifiedCandidate(
                key=unit.key,
                rank=hit.rank,
                score=hit.score,
                relative_path=unit.relative_path,
                document_id=unit.document_id,
                text=unit.text,
                structure_title=str(structure.get("title") or ""),
                parent_title=str(parent.get("title") or ""),
                parent_text=parent_texts.get(parent_id, ""),
                previous_text=previous_text,
                next_text=next_text,
                gold_label=_gold_label(unit, gold),
            )
        )
    return hydrated


def _gold_label(unit: StoredUnit, gold: RetrievalGold) -> str:
    if matching_spans(unit.text, unit.relative_path, gold.relevant_units):
        return "relevant"
    if matching_spans(unit.text, unit.relative_path, gold.hard_negatives):
        return "hard_negative"
    if matching_spans(unit.text, unit.relative_path, gold.watch_negatives):
        return "watch_negative"
    return "other"


def _structures(writer: GraphWriter) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for node in writer.iter_nodes(STRUCTURE):
        props = dict(node.props)
        rows[str(node.key)] = props
    return rows


def _parent_texts(
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
) -> dict[str, str]:
    by_structure: dict[str, list[StoredUnit]] = {}
    for unit in units:
        by_structure.setdefault(unit.structure_id, []).append(unit)
    texts: dict[str, str] = {}
    for structure_id, props in structures.items():
        title = str(props.get("title") or "")
        body = "".join(
            item.text
            for item in sorted(
                by_structure.get(structure_id, []),
                key=lambda item: item.sequence or 0,
            )
        )
        texts[structure_id] = body or title
    return texts


def _neighbors(units: list[StoredUnit]) -> dict[str, tuple[str, str]]:
    by_document: dict[str, list[StoredUnit]] = {}
    for unit in units:
        by_document.setdefault(unit.document_id, []).append(unit)
    neighbors: dict[str, tuple[str, str]] = {}
    for group in by_document.values():
        ordered = sorted(group, key=lambda item: item.sequence or 0)
        for index, unit in enumerate(ordered):
            previous_text = ordered[index - 1].text if index else ""
            next_text = ordered[index + 1].text if index + 1 < len(ordered) else ""
            neighbors[unit.key] = (previous_text, next_text)
    return neighbors
