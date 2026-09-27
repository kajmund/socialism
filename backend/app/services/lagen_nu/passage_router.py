"""Route current TextUnits before LegalInterpreter sees a lagen.nu document.

Rank top-K seeds, Jev keep/drops those seeds, then expand same-section
neighbours. Neighbours are added after Jev so low-score context is not
dropped. Production never silently interprets the whole judgment.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from app.config import settings
from app.jev.evaluation import (
    EVALUATION_POLICY_V1,
    EVALUATOR_PASSAGE_RELEVANCE,
    EVALUATOR_VERSION_V1,
    threshold_config,
)
from app.jev.service import evaluate_system_one
from app.jev.system import (
    HttpJevSystemOne,
    JevClientError,
    JevSystemOne,
    parse_noul,
)
from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.vector_store import TextUnitEmbeddingReader, cosine_score
from app.services.research.failures import FailureCategory

MAX_PASSAGE_CANDIDATES = 8
PASSAGE_NEIGHBOR_SPAN = 1
PASSAGE_KEEP_THRESHOLD = 0.5
PASSAGE_JEV_CHAR_BUDGET = 8000
PASSAGE_INTERPRETER_CHAR_BUDGET = 16_000

logger = logging.getLogger(__name__)

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

    def __init__(
        self,
        message: str,
        *,
        category: FailureCategory,
        seed_ids: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.category = category
        self.seed_ids = seed_ids


class PassageView(Protocol):
    """Fields the router reads. Callers may pass an ORM row or a frozen copy."""

    id: str
    document_id: str
    document_version_id: str
    section_id: str | None
    ordinal: int
    text: str
    content_hash: str


@dataclass(frozen=True)
class PassageUnit:
    """Immutable passage input. Compute must not keep a TextUnit row."""

    id: str
    document_id: str
    document_version_id: str
    section_id: str | None
    ordinal: int
    text: str
    content_hash: str


def freeze_passages(units: Sequence[PassageView]) -> tuple[PassageUnit, ...]:
    return tuple(
        PassageUnit(
            id=unit.id,
            document_id=unit.document_id,
            document_version_id=unit.document_version_id,
            section_id=unit.section_id,
            ordinal=unit.ordinal,
            text=unit.text,
            content_hash=unit.content_hash,
        )
        for unit in units
    )


@dataclass(frozen=True)
class RoutedPassages:
    units: list[PassageUnit]
    interpreter_text: str
    candidate_ids: tuple[str, ...]
    kept_ids: tuple[str, ...]
    expanded_ids: tuple[str, ...]
    router: Literal["jev", "keep_all"]
    jev_clipped: bool
    interpreter_clipped: bool


class LagenNuPassageRouter(Protocol):
    async def route(
        self,
        *,
        question: str,
        units: Sequence[PassageView],
        embeddings: EmbeddingProvider,
        stored: TextUnitEmbeddingReader,
    ) -> RoutedPassages: ...


class KeepAllPassageRouter:
    """Test double. Production must use JevPassageRouter."""

    async def route(
        self,
        *,
        question: str,
        units: Sequence[PassageView],
        embeddings: EmbeddingProvider,
        stored: TextUnitEmbeddingReader,
    ) -> RoutedPassages:
        del question, embeddings, stored
        frozen = list(freeze_passages(units))
        ids = tuple(unit.id for unit in frozen)
        text = "\n\n".join(unit.text for unit in frozen)
        return RoutedPassages(
            units=frozen,
            interpreter_text=text,
            candidate_ids=ids,
            kept_ids=ids,
            expanded_ids=ids,
            router="keep_all",
            jev_clipped=False,
            interpreter_clipped=False,
        )


class JevPassageRouter:
    """Embed-rank seeds, Jev keep/drop, then expand neighbours. Fail loud."""

    def __init__(
        self,
        jev: JevSystemOne | None = None,
        *,
        top_k: int = MAX_PASSAGE_CANDIDATES,
        adjacent: int = PASSAGE_NEIGHBOR_SPAN,
        keep_threshold: float = PASSAGE_KEEP_THRESHOLD,
        jev_char_budget: int = PASSAGE_JEV_CHAR_BUDGET,
        interpreter_char_budget: int = PASSAGE_INTERPRETER_CHAR_BUDGET,
    ) -> None:
        if top_k < 1:
            raise ValueError("top_k must be >= 1")
        if adjacent < 0:
            raise ValueError("adjacent must be >= 0")
        if not 0.0 <= keep_threshold <= 1.0:
            raise ValueError("keep_threshold must be in [0, 1]")
        if jev_char_budget < 1:
            raise ValueError("jev_char_budget must be >= 1")
        if interpreter_char_budget < 1:
            raise ValueError("interpreter_char_budget must be >= 1")
        self._jev = jev or HttpJevSystemOne()
        self._top_k = top_k
        self._adjacent = adjacent
        self._keep_threshold = keep_threshold
        self._jev_char_budget = jev_char_budget
        self._interpreter_char_budget = interpreter_char_budget

    async def route(
        self,
        *,
        question: str,
        units: Sequence[PassageView],
        embeddings: EmbeddingProvider,
        stored: TextUnitEmbeddingReader,
    ) -> RoutedPassages:
        frozen = freeze_passages(units)
        if not frozen:
            raise PassageRoutingError(
                "no current TextUnits to route",
                category="unsupported_source_shape",
            )
        seed_ids: tuple[str, ...] = ()
        jev_clipped = False
        try:
            ranked = await rank_text_units(question, frozen, embeddings, stored)
            seeds = [unit for _score, unit in ranked[: self._top_k]]
            seed_ids = tuple(unit.id for unit in seeds)
            kept_ids, jev_clipped = await self._keep_ids(question, seeds)
        except PassageRoutingError:
            raise
        except JevClientError as exc:
            raise PassageRoutingError(
                str(exc),
                category="selection_failed",
                seed_ids=seed_ids,
            ) from exc
        except Exception as exc:
            raise PassageRoutingError(
                str(exc),
                category="selection_failed",
                seed_ids=seed_ids,
            ) from exc
        if not kept_ids:
            raise PassageRoutingError(
                "Jev kept no passage for this question",
                category="irrelevant_relation",
                seed_ids=seed_ids,
            )
        keep = set(kept_ids)
        kept_seeds = [unit for unit in frozen if unit.id in keep]
        expanded = expand_selected_neighbors(
            kept_seeds,
            frozen,
            adjacent=self._adjacent,
        )
        interpreter_text, interpreter_clipped = clip_text_to_budget(
            "\n\n".join(unit.text for unit in expanded),
            self._interpreter_char_budget,
        )
        if interpreter_clipped:
            logger.info(
                "passage_router_clipped stage=interpreter chars=%s budget=%s expanded_ids=%s",
                len(interpreter_text),
                self._interpreter_char_budget,
                [unit.id for unit in expanded],
            )
        return RoutedPassages(
            units=expanded,
            interpreter_text=interpreter_text,
            candidate_ids=seed_ids,
            kept_ids=tuple(unit.id for unit in kept_seeds),
            expanded_ids=tuple(unit.id for unit in expanded),
            router="jev",
            jev_clipped=jev_clipped,
            interpreter_clipped=interpreter_clipped,
        )

    async def _keep_ids(
        self,
        question: str,
        seeds: Sequence[PassageUnit],
    ) -> tuple[list[str], bool]:
        questions = {
            f"relevant_{index}": {
                **_RELEVANCE_QUESTION,
                "instructions": (f"{_RELEVANCE_QUESTION['instructions']} Passage {unit.id}."),
            }
            for index, unit in enumerate(seeds)
        }
        passages, jev_clipped = clip_passage_texts(
            [
                {
                    "id": unit.id,
                    "ordinal": unit.ordinal,
                    "section_id": unit.section_id,
                    "text": unit.text,
                }
                for unit in seeds
            ],
            budget=self._jev_char_budget,
        )
        if jev_clipped:
            logger.info(
                "passage_router_clipped stage=jev chars=%s budget=%s seed_ids=%s",
                sum(len(str(row["text"])) for row in passages),
                self._jev_char_budget,
                [unit.id for unit in seeds],
            )
        result = await evaluate_system_one(
            self._jev,
            evaluator_id=EVALUATOR_PASSAGE_RELEVANCE,
            evaluator_version=EVALUATOR_VERSION_V1,
            state={"question": question, "passages": passages},
            questions=questions,
            model=settings.jev_model,
            timeout_seconds=settings.jev_timeout_seconds,
            required_signals=tuple(questions),
            policy_version=EVALUATION_POLICY_V1,
            content_hashes={unit.id: unit.content_hash for unit in seeds},
            model_config=threshold_config(keep_threshold=self._keep_threshold),
        )
        kept: list[str] = []
        for index, unit in enumerate(seeds):
            noul = parse_noul(result.answers, f"relevant_{index}")
            if noul >= self._keep_threshold:
                kept.append(unit.id)
        return kept, jev_clipped


async def rank_text_units(
    question: str,
    units: Sequence[PassageView],
    embeddings: EmbeddingProvider,
    stored: TextUnitEmbeddingReader,
) -> list[tuple[float, PassageUnit]]:
    """Cosine-rank current units with ingest embeddings. Embed the question only."""
    frozen = freeze_passages(units)
    document_ids = {unit.document_id for unit in frozen}
    version_ids = {unit.document_version_id for unit in frozen}
    if len(document_ids) != 1 or len(version_ids) != 1:
        raise PassageRoutingError(
            "passage ranking requires one current document_version",
            category="unsupported_source_shape",
        )
    query_vectors = await embeddings.embed([question])
    if len(query_vectors) != 1:
        raise PassageRoutingError(
            f"EmbeddingProvider returned {len(query_vectors)} vectors for the question",
            category="selection_failed",
        )
    stored_vectors = await stored.get_text_unit_embeddings(
        document_id=next(iter(document_ids)),
        document_version_id=next(iter(version_ids)),
        text_unit_ids=[unit.id for unit in frozen],
    )
    scored = [(cosine_score(query_vectors[0], stored_vectors[unit.id]), unit) for unit in frozen]
    scored.sort(key=lambda item: (-item[0], item[1].ordinal, item[1].id))
    return scored


def expand_selected_neighbors(
    selected: Sequence[PassageView],
    units: Sequence[PassageView],
    *,
    adjacent: int = PASSAGE_NEIGHBOR_SPAN,
) -> list[PassageUnit]:
    """Same-section neighbours of the kept seeds. Preserves document order."""
    frozen_selected = freeze_passages(selected)
    frozen_units = freeze_passages(units)
    if adjacent < 0:
        raise ValueError("adjacent must be >= 0")
    chosen: dict[str, PassageUnit] = {}
    for unit in frozen_selected:
        same = [item for item in frozen_units if item.section_id == unit.section_id]
        same.sort(key=lambda item: (item.ordinal, item.id))
        index = next((i for i, item in enumerate(same) if item.id == unit.id), None)
        if index is None:
            chosen[unit.id] = unit
            continue
        start = max(0, index - adjacent)
        end = min(len(same), index + adjacent + 1)
        for item in same[start:end]:
            chosen[item.id] = item
    order = {unit.id: i for i, unit in enumerate(frozen_units)}
    return sorted(chosen.values(), key=lambda item: order.get(item.id, len(order)))


def clip_text_to_budget(text: str, budget: int) -> tuple[str, bool]:
    """Deterministic prefix clip. Never expands to the full document."""
    if budget < 1:
        raise ValueError("budget must be >= 1")
    if len(text) <= budget:
        return text, False
    return text[:budget], True


def clip_passage_texts(
    passages: Sequence[dict[str, object]],
    *,
    budget: int,
) -> tuple[list[dict[str, object]], bool]:
    """Clip passage texts in document order until the char budget is spent."""
    if budget < 1:
        raise ValueError("budget must be >= 1")
    remaining = budget
    clipped = False
    out: list[dict[str, object]] = []
    for row in passages:
        text = str(row["text"])
        if len(text) <= remaining:
            out.append(dict(row))
            remaining -= len(text)
            continue
        clipped_row = dict(row)
        clipped_row["text"] = text[:remaining]
        out.append(clipped_row)
        remaining = 0
        clipped = True
    return out, clipped
