"""Question-oriented evidence groups for the BM25 experiment.

Passage gold stays in `retrieval_gold/*.json` and is reused unchanged. This
module adds the missing answer-bearing layer: mandatory groups whose
alternatives are acceptable source quotes. Missing, unknown, and unevaluated
cells stay explicit instead of being inferred from keywords.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from overgraph_ingest.retrieval.gold import RetrievalGold
from overgraph_ingest.retrieval.gold_map import locate_contains
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.tabular.holdout_gold import HOLD_OUT_CELLS
from overgraph_ingest.tabular.user_gold import (
    NO,
    SILENT,
    UNTIL_NOTICE,
    USER_CELLS,
    YES,
    UserCellGold,
)

ANSWERABLE = "answerable"
NEGATIVE = "negative"
NO_KNOWN_ANSWER = "no_known_answer"
NOT_EVALUATED = "not_evaluated"
ANSWERABILITIES = (ANSWERABLE, NEGATIVE, NO_KNOWN_ANSWER, NOT_EVALUATED)

DEVELOPMENT = "development"
LOCKED_HOLDOUT = "locked_holdout"
SPLITS = (DEVELOPMENT, LOCKED_HOLDOUT)


@dataclass(frozen=True)
class EvidenceAlternative:
    relative_path: str
    contains: str
    reason: str = ""


@dataclass(frozen=True)
class EvidenceGroup:
    id: str
    alternatives: tuple[EvidenceAlternative, ...]


@dataclass(frozen=True)
class CellEvidenceGold:
    question_id: str
    relative_path: str
    split: str
    answerability: str
    positive_property: bool | None
    groups: tuple[EvidenceGroup, ...]
    notes: str = ""


@dataclass(frozen=True)
class InventoryEvidence:
    relative_path: str
    groups: tuple[EvidenceGroup, ...]
    positive_property: bool = True


@dataclass(frozen=True)
class CellSource:
    cell: UserCellGold
    split: str


def load_question_gold(
    overlay_path: Path | None = None,
    *,
    cells: tuple[UserCellGold, ...] | None = None,
) -> list[CellEvidenceGold]:
    sources = _cell_sources(cells)
    overlay = _load_overlay(overlay_path) if overlay_path is not None else {}
    rows: list[CellEvidenceGold] = []
    for source in sources:
        key = (source.cell.question_id, source.cell.relative_path)
        if key in overlay:
            rows.append(_from_overlay(source, overlay[key]))
            continue
        rows.append(_from_user_cell(source))
    return rows


def inventory_groups(gold: RetrievalGold) -> dict[str, tuple[EvidenceGroup, ...]]:
    coverage = {group.relative_path: group.contains for group in gold.coverage_groups}
    by_path: dict[str, list[EvidenceGroup]] = {}
    for path, contains in coverage.items():
        by_path[path] = [
            EvidenceGroup(
                id=f"coverage:{path}:{index}",
                alternatives=(
                    EvidenceAlternative(relative_path=path, contains=snippet),
                ),
            )
            for index, snippet in enumerate(contains)
        ]
    for index, span in enumerate(gold.relevant_units):
        if span.relative_path in coverage:
            continue
        by_path.setdefault(span.relative_path, []).append(
            EvidenceGroup(
                id=f"unit:{span.relative_path}:{index}",
                alternatives=(
                    EvidenceAlternative(
                        relative_path=span.relative_path,
                        contains=span.contains,
                        reason=span.reason or "",
                    ),
                ),
            )
        )
    return {path: tuple(groups) for path, groups in by_path.items()}


def document_gold_without_evidence(gold: RetrievalGold) -> tuple[str, ...]:
    mapped = inventory_groups(gold)
    return tuple(path for path in gold.relevant_documents if path not in mapped)


def validate_groups_against_units(
    groups: tuple[EvidenceGroup, ...],
    units: list[StoredUnit],
) -> None:
    for group in groups:
        if not group.alternatives:
            raise ValueError(f"evidence group {group.id!r} has no alternatives")
        for alternative in group.alternatives:
            if not alternative.relative_path or not alternative.contains:
                raise ValueError(f"evidence group {group.id!r} has an empty alternative")
            if not any(
                unit.relative_path == alternative.relative_path
                and locate_contains(unit.text, alternative.contains)
                for unit in units
            ):
                raise ValueError(
                    "evidence gold does not map to a TextUnit: "
                    f"{alternative.relative_path} :: {alternative.contains!r}"
                )


def validate_cell_gold(
    rows: list[CellEvidenceGold],
    units: list[StoredUnit] | None = None,
) -> None:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.question_id, row.relative_path)
        if key in seen:
            raise ValueError(f"duplicate question gold cell {key}")
        seen.add(key)
        if row.answerability not in ANSWERABILITIES:
            raise ValueError(f"invalid answerability {row.answerability!r}")
        if row.split not in SPLITS:
            raise ValueError(f"invalid split {row.split!r}")
        if row.answerability == ANSWERABLE and not row.groups:
            raise ValueError(f"answerable cell {key} has no evidence group")
        if row.answerability == NOT_EVALUATED and row.groups:
            raise ValueError(f"not_evaluated cell {key} must not have evidence groups")
        if units is not None:
            validate_groups_against_units(row.groups, units)


def first_group_ranks(
    groups: tuple[EvidenceGroup, ...],
    hits: list[SearchHit],
) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for group in groups:
        for hit in hits:
            if group.id in ranks:
                break
            if any(_hit_matches(hit, alternative) for alternative in group.alternatives):
                ranks[group.id] = hit.rank
    return ranks


def covered_groups(
    groups: tuple[EvidenceGroup, ...],
    hits: list[SearchHit],
    *,
    k: int | None = None,
) -> set[str]:
    top = hits if k is None else hits[:k]
    return set(first_group_ranks(groups, top))


def group_evidence_keys(
    groups: tuple[EvidenceGroup, ...],
    units: list[StoredUnit],
) -> set[str]:
    keys: set[str] = set()
    for unit in units:
        for group in groups:
            if any(_unit_matches(unit, alternative) for alternative in group.alternatives):
                keys.add(unit.key)
    return keys


def required_group_count(groups_by_path: dict[str, tuple[EvidenceGroup, ...]]) -> int:
    return sum(len(groups) for groups in groups_by_path.values())


def ceiling_at(k: int, required: int) -> int:
    return min(k, required)


def split_of_cell(cell: UserCellGold) -> str:
    if any(item is cell or _same_cell(item, cell) for item in HOLD_OUT_CELLS):
        return LOCKED_HOLDOUT
    return DEVELOPMENT


def _cell_sources(cells: tuple[UserCellGold, ...] | None) -> list[CellSource]:
    if cells is not None:
        return [CellSource(cell=cell, split=split_of_cell(cell)) for cell in cells]
    return [CellSource(cell=cell, split=DEVELOPMENT) for cell in USER_CELLS] + [
        CellSource(cell=cell, split=LOCKED_HOLDOUT) for cell in HOLD_OUT_CELLS
    ]


def _from_user_cell(source: CellSource) -> CellEvidenceGold:
    cell = source.cell
    if cell.polarity in {YES, UNTIL_NOTICE}:
        answerability = ANSWERABLE
        positive: bool | None = True
    elif cell.polarity == NO or cell.polarity == SILENT:
        answerability = NEGATIVE
        positive = False
    else:
        answerability = NOT_EVALUATED
        positive = None
    groups: tuple[EvidenceGroup, ...] = ()
    if cell.answers:
        groups = (
            EvidenceGroup(
                id=f"answer:{cell.question_id}:{cell.relative_path}",
                alternatives=tuple(
                    EvidenceAlternative(
                        relative_path=cell.relative_path,
                        contains=answer.contains,
                        reason=answer.applies_to,
                    )
                    for answer in cell.answers
                ),
            ),
        )
    return CellEvidenceGold(
        question_id=cell.question_id,
        relative_path=cell.relative_path,
        split=source.split,
        answerability=answerability,
        positive_property=positive,
        groups=groups,
        notes=cell.notes,
    )


def _from_overlay(source: CellSource, row: dict[str, object]) -> CellEvidenceGold:
    groups = tuple(
        EvidenceGroup(
            id=str(group["id"]),
            alternatives=tuple(
                EvidenceAlternative(
                    relative_path=str(
                        alternative.get("relative_path") or source.cell.relative_path
                    ),
                    contains=str(alternative["contains"]),
                    reason=str(alternative.get("reason") or ""),
                )
                for alternative in (group.get("alternatives") or [])
            ),
        )
        for group in (row.get("required_groups") or [])
    )
    raw_answerability = str(row.get("answerability") or "")
    if raw_answerability not in ANSWERABILITIES:
        raise ValueError(
            f"overlay cell {source.cell.question_id}/{source.cell.relative_path} "
            f"has invalid answerability {raw_answerability!r}"
        )
    raw_positive = row.get("positive_property")
    positive = None if raw_positive is None else bool(raw_positive)
    return CellEvidenceGold(
        question_id=source.cell.question_id,
        relative_path=source.cell.relative_path,
        split=str(row.get("split") or source.split),
        answerability=raw_answerability,
        positive_property=positive,
        groups=groups,
        notes=str(row.get("notes") or source.cell.notes),
    )


def _load_overlay(path: Path) -> dict[tuple[str, str], dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cells = payload.get("cells")
    if not isinstance(cells, list):
        raise TypeError(f"{path} has no cells list")
    overlay: dict[tuple[str, str], dict[str, object]] = {}
    for row in cells:
        question_id = str(row["question_id"])
        relative_path = str(row["relative_path"])
        key = (question_id, relative_path)
        if key in overlay:
            raise ValueError(f"duplicate overlay cell {key}")
        overlay[key] = row
    return overlay


def _hit_matches(hit: SearchHit, alternative: EvidenceAlternative) -> bool:
    if hit.relative_path != alternative.relative_path:
        return False
    return bool(locate_contains(hit.text, alternative.contains))


def _unit_matches(unit: StoredUnit, alternative: EvidenceAlternative) -> bool:
    if unit.relative_path != alternative.relative_path:
        return False
    return bool(locate_contains(unit.text, alternative.contains))


def _same_cell(left: UserCellGold, right: UserCellGold) -> bool:
    return (
        left.relative_path == right.relative_path
        and left.question_id == right.question_id
    )
