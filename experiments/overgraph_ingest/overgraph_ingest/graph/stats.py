"""Write and document-structure counters collected during ingest."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BatchWrite:
    kind: str
    count: int
    seconds: float


@dataclass
class WriteStats:
    node_seconds: float = 0.0
    edge_seconds: float = 0.0
    nodes: int = 0
    edges: int = 0
    batches: list[BatchWrite] = field(default_factory=list)


@dataclass
class StructureStats:
    text_unit_sizes: list[int] = field(default_factory=list)
    structures: int = 0
    clauses: int = 0
    split_structures: int = 0
    split_text_units: int = 0
    oversized_units: int = 0
    exclusions: int = 0
    exclusion_reasons: list[str] = field(default_factory=list)
    nodes: int = 0
    edges: int = 0
    reconstructed: bool = False
    coverage: float = 0.0


def collect_structure_stats(
    extracted,
    segmented,
    draft,
    verification,
    *,
    max_chars: int,
) -> StructureStats:
    sizes = [len(unit.text) for unit in segmented.units]
    units_by_structure: dict[str, int] = {}
    for unit in segmented.units:
        units_by_structure[unit.structure_id] = units_by_structure.get(unit.structure_id, 0) + 1
    split_ids = {key for key, count in units_by_structure.items() if count > 1}
    clauses = sum(1 for item in segmented.structures if item.clause_number)
    reasons = [
        block.exclude_reason or "unspecified"
        for block in extracted.exclusions()
    ]
    return StructureStats(
        text_unit_sizes=sizes,
        structures=len(segmented.structures),
        clauses=clauses,
        split_structures=len(split_ids),
        split_text_units=sum(units_by_structure[key] for key in split_ids),
        oversized_units=sum(1 for size in sizes if size > max_chars),
        exclusions=len(extracted.exclusions()),
        exclusion_reasons=reasons,
        nodes=len(draft.nodes),
        edges=len(draft.edges),
        reconstructed=verification.reconstructed,
        coverage=verification.coverage,
    )
