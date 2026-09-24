"""Route current TextUnits before LegalInterpreter sees a lagen.nu document.

Deterministic rank and neighbour expand run first. Jev then keep/drops.
Production never silently interprets the whole judgment.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.config import settings
from app.database.models import TextUnitRecord
from app.jev.system import (
    HttpJevSystemOne,
    JevClientError,
    JevSystemOne,
    parse_noul,
)
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.vector_store import cosine_score
from app.services.research.failures import FailureCategory

MAX_PASSAGE_CANDIDATES = 8
PASSAGE_NEIGHBOR_SPAN = 1
PASSAGE_KEEP_THRESHOLD = 0.5

_RELEVANCE_QUESTION = {
    "type": "noul",
    "instructions": "Is this passage relevant to the research question?",
    "criteria": {
        "true": "It bears on the question.",
        "false": "It is off-topic.",
    },
}


class PassageRoutingError(Exception):
    """Rank, expand, or Jev could not produce a passage set for the interpreter."""

    def __init__(self, message: str, *, category: FailureCategory) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class RoutedPassages:
    units: list[TextUnitRecord]
    candidate_ids: tuple[str, ...]
    kept_ids: tuple[str, ...]
    router: Literal["jev", "keep_all"]


class LagenNuPassageRouter(Protocol):
    async def route(
        self,
        *,
        question: str,
        units: Sequence[TextUnitRecord],
        embeddings: EmbeddingProvider,
    ) -> RoutedPassages: ...


class KeepAllPassageRouter:
    """Test double. Production must use JevPassageRouter."""

    async def route(
        self,
        *,
        question: str,
        units: Sequence[TextUnitRecord],
        embeddings: EmbeddingProvider,
    ) -> RoutedPassages:
        del question, embeddings
        ids = tuple(unit.id for unit in units)
        return RoutedPassages(
            units=list(units),
            candidate_ids=ids,
            kept_ids=ids,
            router="keep_all",
        )


class JevPassageRouter:
    """Embed-rank current units, expand neighbours, Jev keep/drop. Fail loud."""

    def __init__(
        self,
        jev: JevSystemOne | None = None,
        *,
        top_k: int = MAX_PASSAGE_CANDIDATES,
        adjacent: int = PASSAGE_NEIGHBOR_SPAN,
        keep_threshold: float = PASSAGE_KEEP_THRESHOLD,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        if adjacent < 0:
            raise ValueError("adjacent must be >= 0")
        if not 0.0 <= keep_threshold <= 1.0:
            raise ValueError("keep_threshold must be in [0, 1]")
        self._jev = jev or HttpJevSystemOne()
        self._top_k = top_k
        self._adjacent = adjacent
        self._keep_threshold = keep_threshold

    async def route(
        self,
        *,
        question: str,
        units: Sequence[TextUnitRecord],
        embeddings: EmbeddingProvider,
    ) -> RoutedPassages:
        if not units:
            raise PassageRoutingError(
                "no current TextUnits to route",
                category="unsupported_source_shape",
            )
        try:
            ranked = await rank_text_units(question, units, embeddings)
            selected = [unit for _score, unit in ranked[: self._top_k]]
            candidates = expand_selected_neighbors(
                selected,
                units,
                adjacent=self._adjacent,
            )
            kept_ids = await self._keep_ids(question, candidates)
        except PassageRoutingError:
            raise
        except JevClientError as exc:
            raise PassageRoutingError(str(exc), category="selection_failed") from exc
        except Exception as exc:
            raise PassageRoutingError(str(exc), category="selection_failed") from exc
        if not kept_ids:
            raise PassageRoutingError(
                "Jev kept no passage for this question",
                category="irrelevant_relation",
            )
        keep = set(kept_ids)
        ordered = [unit for unit in units if unit.id in keep]
        return RoutedPassages(
            units=ordered,
            candidate_ids=tuple(unit.id for unit in candidates),
            kept_ids=tuple(unit.id for unit in ordered),
            router="jev",
        )

    async def _keep_ids(
        self,
        question: str,
        candidates: Sequence[TextUnitRecord],
    ) -> list[str]:
        questions = {
            f"relevant_{index}": {
                **_RELEVANCE_QUESTION,
                "instructions": (
                    f"{_RELEVANCE_QUESTION['instructions']} Passage {unit.id}."
                ),
            }
            for index, unit in enumerate(candidates)
        }
        result = await self._jev.ask(
            state={
                "question": question,
                "passages": [
                    {
                        "id": unit.id,
                        "ordinal": unit.ordinal,
                        "section_id": unit.section_id,
                        "text": unit.text,
                    }
                    for unit in candidates
                ],
            },
            questions=questions,
            model=settings.jev_model,
            timeout_seconds=settings.jev_timeout_seconds,
        )
        kept: list[str] = []
        for index, unit in enumerate(candidates):
            noul = parse_noul(result.answers, f"relevant_{index}")
            if noul >= self._keep_threshold:
                kept.append(unit.id)
        return kept


async def rank_text_units(
    question: str,
    units: Sequence[TextUnitRecord],
    embeddings: EmbeddingProvider,
) -> list[tuple[float, TextUnitRecord]]:
    """In-process cosine rank. Do not search the vector store by case scope."""
    vectors = await embeddings.embed([question, *[unit.text for unit in units]])
    query = vectors[0]
    scored = [
        (cosine_score(query, vector), unit)
        for vector, unit in zip(vectors[1:], units, strict=True)
    ]
    scored.sort(key=lambda item: (-item[0], item[1].ordinal, item[1].id))
    return scored


def expand_selected_neighbors(
    selected: Sequence[TextUnitRecord],
    units: Sequence[TextUnitRecord],
    *,
    adjacent: int = PASSAGE_NEIGHBOR_SPAN,
) -> list[TextUnitRecord]:
    """Same-section neighbours of the ranked set. Preserves document order."""
    if adjacent < 0:
        raise ValueError("adjacent must be >= 0")
    chosen: dict[str, TextUnitRecord] = {}
    for unit in selected:
        same = [item for item in units if item.section_id == unit.section_id]
        same.sort(key=lambda item: (item.ordinal, item.id))
        index = next((i for i, item in enumerate(same) if item.id == unit.id), None)
        if index is None:
            chosen[unit.id] = unit
            continue
        start = max(0, index - adjacent)
        end = min(len(same), index + adjacent + 1)
        for item in same[start:end]:
            chosen[item.id] = item
    order = {unit.id: i for i, unit in enumerate(units)}
    return sorted(chosen.values(), key=lambda item: order.get(item.id, len(order)))
