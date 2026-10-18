"""Synchronous cell runners for variants A, B, and C."""

from __future__ import annotations

import time

from overgraph_ingest.cerebras.client import Completer
from overgraph_ingest.jev.candidates import ClassifiedCandidate, GraphContext
from overgraph_ingest.jev.classify import Judgment
from overgraph_ingest.jev.client import JevClient, JevError
from overgraph_ingest.retrieval.index import StoredUnit
from overgraph_ingest.retrieval.search import SearchHit
from overgraph_ingest.tabular.cerebras_io import answer_with_cerebras
from overgraph_ingest.tabular.contract import (
    ANSWERED,
    NOT_FOUND,
    UNCERTAIN,
    CellResult,
    SourceRef,
    require_status,
    source_ref,
)
from overgraph_ingest.tabular.gold import document_short_id
from overgraph_ingest.tabular.jev_io import (
    ANSWER,
    CountingJev,
    answer_cell,
    answer_cell_multi,
    classify_units,
    decide,
)
from overgraph_ingest.tabular.navigate import (
    MAX_NAV_STEPS,
    MAX_UNITS,
    option_by_choice,
    valid_operations,
)
from overgraph_ingest.tabular.search import DEFAULT_K, document_local_rank, recall_at

VARIANT_A = "A"
VARIANT_B = "B"
VARIANT_C = "C"
VARIANT_K = "K"
VARIANT_D = "D"
VARIANT_E = "E"


def run_cell(
    *,
    variant: str,
    relative_path: str,
    question_id: str,
    user_question: str,
    classify_question: str,
    units: list[StoredUnit],
    context: GraphContext,
    dense_query: list[float],
    sparse_query: list[tuple[int, float]],
    relevant_keys: set[str],
    jev: JevClient | None,
    cerebras: Completer | None,
    jev_model: str,
    timeout_seconds: float,
    top_k: int = DEFAULT_K,
    max_nav_steps: int = MAX_NAV_STEPS,
    max_units: int = MAX_UNITS,
) -> CellResult:
    started = time.perf_counter()
    retrieve_started = time.perf_counter()
    ranked = document_local_rank(
        units,
        relative_path,
        dense_query=dense_query,
        sparse_query=sparse_query,
    )
    seeds = ranked[:top_k]
    retrieve_seconds = time.perf_counter() - retrieve_started
    retrieval = {
        "k": top_k,
        "candidate_keys": [hit.key for hit in seeds],
        **recall_at(ranked, relevant_keys),
    }
    if variant == VARIANT_C:
        if cerebras is None:
            raise ValueError("variant C requires a Cerebras client")
        result = _variant_c(
            relative_path=relative_path,
            question_id=question_id,
            user_question=user_question,
            units=units,
            structures=context.structures,
            seeds=seeds,
            cerebras=cerebras,
            retrieve_seconds=retrieve_seconds,
            retrieval=retrieval,
        )
    elif variant in {VARIANT_B, VARIANT_K, VARIANT_D}:
        if jev is None:
            raise ValueError(f"variant {variant} requires a Jev client")
        result = _variant_b(
            relative_path=relative_path,
            question_id=question_id,
            user_question=user_question,
            classify_question=classify_question,
            context=context,
            seeds=seeds,
            jev=jev,
            jev_model=jev_model,
            timeout_seconds=timeout_seconds,
            retrieve_seconds=retrieve_seconds,
            retrieval=retrieval,
            variant=variant,
            classify=variant != VARIANT_D,
        )
    elif variant == VARIANT_A:
        if jev is None:
            raise ValueError("variant A requires a Jev client")
        result = _variant_a(
            relative_path=relative_path,
            question_id=question_id,
            user_question=user_question,
            classify_question=classify_question,
            units=units,
            context=context,
            seeds=seeds,
            jev=jev,
            jev_model=jev_model,
            timeout_seconds=timeout_seconds,
            retrieve_seconds=retrieve_seconds,
            retrieval=retrieval,
            max_nav_steps=max_nav_steps,
            max_units=max_units,
        )
    else:
        raise ValueError(f"unsupported tabular variant: {variant}")
    result.cell_seconds = time.perf_counter() - started
    return result


def answer_without_classify(
    *,
    relative_path: str,
    question_id: str,
    user_question: str,
    context: GraphContext,
    seeds: list[SearchHit],
    jev: JevClient,
    jev_model: str,
    timeout_seconds: float,
    retrieve_seconds: float,
    retrieval: dict[str, object],
    variant: str = VARIANT_D,
    instructions: str | None = None,
    status_criteria: dict[str, str] | None = None,
    present_structure: bool = False,
    multi_answers: bool = False,
) -> CellResult:
    started = time.perf_counter()
    result = _variant_b(
        relative_path=relative_path,
        question_id=question_id,
        user_question=user_question,
        classify_question="",
        context=context,
        seeds=seeds,
        jev=jev,
        jev_model=jev_model,
        timeout_seconds=timeout_seconds,
        retrieve_seconds=retrieve_seconds,
        retrieval=retrieval,
        variant=variant,
        classify=False,
        instructions=instructions,
        status_criteria=status_criteria,
        present_structure=present_structure,
        multi_answers=multi_answers,
    )
    result.cell_seconds = time.perf_counter() - started
    return result


def _variant_b(
    *,
    relative_path: str,
    question_id: str,
    user_question: str,
    classify_question: str,
    context: GraphContext,
    seeds: list[SearchHit],
    jev: JevClient,
    jev_model: str,
    timeout_seconds: float,
    retrieve_seconds: float,
    retrieval: dict[str, object],
    variant: str = VARIANT_B,
    classify: bool = True,
    instructions: str | None = None,
    status_criteria: dict[str, str] | None = None,
    present_structure: bool = False,
    multi_answers: bool = False,
) -> CellResult:
    counter = _fresh_jev(jev)
    by_key = context.by_key()
    examined = [by_key[hit.key] for hit in seeds if hit.key in by_key]
    classify_seconds = 0.0
    judgments: list[Judgment] = []
    if classify and examined:
        judgments, classify_seconds = classify_units(
            counter,
            [_candidate(context, unit, rank=index, score=0.0) for index, unit in enumerate(examined, start=1)],
            question=classify_question,
            model=jev_model,
            timeout_seconds=timeout_seconds,
        )
    return _finish_jev_answer(
        relative_path=relative_path,
        question_id=question_id,
        user_question=user_question,
        variant=variant,
        examined=examined,
        context=context,
        jev=counter,
        jev_model=jev_model,
        timeout_seconds=timeout_seconds,
        retrieve_seconds=retrieve_seconds,
        classify_seconds=classify_seconds,
        navigate_seconds=0.0,
        retrieval=retrieval,
        navigation=[],
        navigation_steps=0,
        judgments=judgments,
        budget_exhausted=False,
        instructions=instructions,
        status_criteria=status_criteria,
        present_structure=present_structure,
        multi_answers=multi_answers,
    )


def _variant_c(
    *,
    relative_path: str,
    question_id: str,
    user_question: str,
    units: list[StoredUnit],
    structures: dict[str, dict[str, object]],
    seeds: list[SearchHit],
    cerebras: Completer,
    retrieve_seconds: float,
    retrieval: dict[str, object],
) -> CellResult:
    by_key = {unit.key: unit for unit in units}
    if not seeds:
        return _empty_cell(
            relative_path,
            question_id,
            user_question,
            VARIANT_C,
            retrieve_seconds,
            retrieval,
            NOT_FOUND,
            "no_candidates",
        )
    parsed = answer_with_cerebras(cerebras, user_question=user_question, hits=seeds)
    status = require_status(parsed["status"])
    sources: list[SourceRef] = []
    notes = ""
    answer = parsed["answer"]
    source_ids: list[str] = []
    if status == ANSWERED:
        unit = by_key.get(parsed["source_unit_id"])
        if unit is None or unit.key not in {hit.key for hit in seeds}:
            status = UNCERTAIN
            notes = "citation_failed"
            answer = ""
        else:
            ref = source_ref(
                unit,
                parsed["excerpt"],
                clause_number=_clause_number(unit, structures),
            )
            if not ref.validated:
                status = UNCERTAIN
                notes = "citation_failed"
                answer = ""
            else:
                sources = [ref]
                source_ids = [unit.key]
    return CellResult(
        document_id=document_short_id(relative_path),
        relative_path=relative_path,
        question_id=question_id,
        question=user_question,
        variant=VARIANT_C,
        status=status,
        answer=answer,
        source_unit_ids=source_ids,
        sources=sources,
        units_examined=len(seeds),
        cerebras_calls=1,
        prompt_tokens=_as_int(parsed.get("prompt_tokens")),
        completion_tokens=_as_int(parsed.get("completion_tokens")),
        retrieve_seconds=retrieve_seconds,
        answer_seconds=float(parsed.get("seconds") or 0.0),
        retrieval=retrieval,
        notes=notes,
    )


def _variant_a(
    *,
    relative_path: str,
    question_id: str,
    user_question: str,
    classify_question: str,
    units: list[StoredUnit],
    context: GraphContext,
    seeds: list[SearchHit],
    jev: JevClient,
    jev_model: str,
    timeout_seconds: float,
    retrieve_seconds: float,
    retrieval: dict[str, object],
    max_nav_steps: int,
    max_units: int,
) -> CellResult:
    counter = _fresh_jev(jev)
    by_key = context.by_key()
    local = [unit for unit in units if unit.relative_path == relative_path]
    examined: list[StoredUnit] = []
    judgments: list[Judgment] = []
    visited: set[str] = set()
    navigation: list[dict[str, object]] = []
    classify_seconds = 0.0
    navigate_seconds = 0.0
    for hit in seeds:
        unit = by_key.get(hit.key)
        if unit is None or unit.key in visited:
            continue
        if len(examined) >= max_units:
            break
        visited.add(unit.key)
        examined.append(unit)
        added, elapsed = classify_units(
            counter,
            [_candidate(context, unit, rank=len(examined), score=hit.score)],
            question=classify_question,
            model=jev_model,
            timeout_seconds=timeout_seconds,
        )
        judgments.extend(added)
        classify_seconds += elapsed
    current = _current_unit(examined, judgments)
    steps = 0
    budget_exhausted = False
    if not examined:
        return _empty_cell(
            relative_path,
            question_id,
            user_question,
            VARIANT_A,
            retrieve_seconds,
            retrieval,
            NOT_FOUND,
            "no_candidates",
        )
    while True:
        if current is None:
            decision = UNCERTAIN
            break
        offer = valid_operations(current, local, context.structures, visited)
        try:
            decision = decide(
                counter,
                user_question=user_question,
                offer=offer,
                examined=examined,
                judgments=judgments,
                model=jev_model,
                timeout_seconds=timeout_seconds,
            )
        except JevError as exc:
            return _finish_jev_answer(
                relative_path=relative_path,
                question_id=question_id,
                user_question=user_question,
                variant=VARIANT_A,
                examined=examined,
                context=context,
                jev=counter,
                jev_model=jev_model,
                timeout_seconds=timeout_seconds,
                retrieve_seconds=retrieve_seconds,
                classify_seconds=classify_seconds,
                navigate_seconds=navigate_seconds,
                retrieval=retrieval,
                navigation=navigation,
                navigation_steps=steps,
                judgments=judgments,
                budget_exhausted=budget_exhausted,
                forced_status=UNCERTAIN,
                notes=f"invalid_decision:{exc}",
            )
        if decision in {ANSWER, UNCERTAIN, NOT_FOUND}:
            break
        if steps >= max_nav_steps or len(examined) >= max_units:
            budget_exhausted = True
            decision = UNCERTAIN
            break
        hop_started = time.perf_counter()
        option = option_by_choice(offer, decision)
        if option is None:
            navigation.append(
                {
                    "attempted": decision,
                    "status": "INVALID",
                    "substituted": False,
                }
            )
            budget_exhausted = False
            decision = UNCERTAIN
            navigate_seconds += time.perf_counter() - hop_started
            break
        target = by_key.get(option.target_key)
        if target is None or target.key in visited:
            navigation.append(
                {
                    "operation": option.operation,
                    "reference": option.reference,
                    "requested": option.target_key,
                    "status": "ABSENT",
                    "substituted": False,
                }
            )
            navigate_seconds += time.perf_counter() - hop_started
            decision = UNCERTAIN
            break
        visited.add(target.key)
        examined.append(target)
        steps += 1
        navigation.append(
            {
                "operation": option.operation,
                "reference": option.reference,
                "requested": option.target_key,
                "fetched": target.key,
                "status": "FETCHED",
                "substituted": False,
            }
        )
        added, elapsed = classify_units(
            counter,
            [_candidate(context, target, rank=len(examined), score=0.0)],
            question=classify_question,
            model=jev_model,
            timeout_seconds=timeout_seconds,
        )
        judgments.extend(added)
        classify_seconds += elapsed
        navigate_seconds += time.perf_counter() - hop_started
        current = target
    forced = None
    notes = ""
    if decision == UNCERTAIN and budget_exhausted:
        forced = UNCERTAIN
        notes = "budget_exhausted"
    elif decision == UNCERTAIN:
        forced = UNCERTAIN
    elif decision == NOT_FOUND:
        forced = NOT_FOUND
    elif decision == ANSWER:
        forced = None
    else:
        forced = UNCERTAIN
        notes = notes or "invalid_decision"
    return _finish_jev_answer(
        relative_path=relative_path,
        question_id=question_id,
        user_question=user_question,
        variant=VARIANT_A,
        examined=examined,
        context=context,
        jev=counter,
        jev_model=jev_model,
        timeout_seconds=timeout_seconds,
        retrieve_seconds=retrieve_seconds,
        classify_seconds=classify_seconds,
        navigate_seconds=navigate_seconds,
        retrieval=retrieval,
        navigation=navigation,
        navigation_steps=steps,
        judgments=judgments,
        budget_exhausted=budget_exhausted,
        forced_status=forced,
        notes=notes,
    )


def _finish_jev_answer(
    *,
    relative_path: str,
    question_id: str,
    user_question: str,
    variant: str,
    examined: list[StoredUnit],
    context: GraphContext,
    jev: CountingJev,
    jev_model: str,
    timeout_seconds: float,
    retrieve_seconds: float,
    classify_seconds: float,
    navigate_seconds: float,
    retrieval: dict[str, object],
    navigation: list[dict[str, object]],
    navigation_steps: int,
    judgments: list[Judgment],
    budget_exhausted: bool,
    forced_status: str | None = None,
    notes: str = "",
    instructions: str | None = None,
    status_criteria: dict[str, str] | None = None,
    present_structure: bool = False,
    multi_answers: bool = False,
) -> CellResult:
    usage = jev.usage
    if not examined:
        return _empty_cell(
            relative_path,
            question_id,
            user_question,
            variant,
            retrieve_seconds,
            retrieval,
            forced_status or NOT_FOUND,
            notes or "no_candidates",
        )
    if forced_status in {UNCERTAIN, NOT_FOUND}:
        return CellResult(
            document_id=document_short_id(relative_path),
            relative_path=relative_path,
            question_id=question_id,
            question=user_question,
            variant=variant,
            status=forced_status,
            answer="",
            source_unit_ids=[],
            sources=[],
            navigation_steps=navigation_steps,
            units_examined=len(examined),
            jev_calls=usage.calls,
            prompt_tokens=usage.prompt_tokens or None,
            completion_tokens=usage.completion_tokens or None,
            retrieve_seconds=retrieve_seconds,
            classify_seconds=classify_seconds,
            navigate_seconds=navigate_seconds,
            retrieval=retrieval,
            navigation=navigation,
            budget_exhausted=budget_exhausted,
            notes=notes,
        )
    answer_started = time.perf_counter()
    try:
        if multi_answers:
            status, pairs = answer_cell_multi(
                jev,
                user_question=user_question,
                examined=examined,
                model=jev_model,
                timeout_seconds=timeout_seconds,
                status_criteria=status_criteria,
            )
        else:
            status, source_id, excerpt, _excerpt_id = answer_cell(
                jev,
                user_question=user_question,
                examined=examined,
                model=jev_model,
                timeout_seconds=timeout_seconds,
                instructions=instructions,
                status_criteria=status_criteria,
                structures=context.structures if present_structure else None,
            )
            pairs = [(source_id, excerpt, _excerpt_id)]
    except JevError as exc:
        return CellResult(
            document_id=document_short_id(relative_path),
            relative_path=relative_path,
            question_id=question_id,
            question=user_question,
            variant=variant,
            status=UNCERTAIN,
            answer="",
            source_unit_ids=[],
            sources=[],
            navigation_steps=navigation_steps,
            units_examined=len(examined),
            jev_calls=usage.calls,
            prompt_tokens=usage.prompt_tokens or None,
            completion_tokens=usage.completion_tokens or None,
            retrieve_seconds=retrieve_seconds,
            classify_seconds=classify_seconds,
            navigate_seconds=navigate_seconds,
            retrieval=retrieval,
            navigation=navigation,
            budget_exhausted=budget_exhausted,
            notes=f"invalid_answer:{exc}",
        )
    answer_seconds = time.perf_counter() - answer_started
    status = require_status(status)
    sources, source_ids, answer, notes = _validated_answers(
        examined,
        context.structures,
        status,
        pairs,
        notes,
    )
    if status == ANSWERED and not sources:
        status = UNCERTAIN
        notes = notes or "citation_failed"
        answer = ""
        source_ids = []
    if status != ANSWERED:
        answer = ""
        sources = []
        source_ids = []
    return CellResult(
        document_id=document_short_id(relative_path),
        relative_path=relative_path,
        question_id=question_id,
        question=user_question,
        variant=variant,
        status=status,
        answer=answer,
        source_unit_ids=source_ids,
        sources=sources,
        navigation_steps=navigation_steps,
        units_examined=len(examined),
        jev_calls=jev.usage.calls,
        prompt_tokens=jev.usage.prompt_tokens or None,
        completion_tokens=jev.usage.completion_tokens or None,
        retrieve_seconds=retrieve_seconds,
        classify_seconds=classify_seconds,
        navigate_seconds=navigate_seconds,
        answer_seconds=answer_seconds,
        retrieval=retrieval,
        navigation=navigation,
        budget_exhausted=budget_exhausted,
        notes=notes,
    )


def _candidate(
    context: GraphContext,
    unit: StoredUnit,
    *,
    rank: int,
    score: float,
) -> ClassifiedCandidate:
    structure = context.structures.get(unit.structure_id, {})
    parent_id = str(structure.get("parent_id") or "")
    parent = context.structures.get(parent_id, {})
    previous_text, next_text = context.neighbors.get(unit.key, ("", ""))
    return ClassifiedCandidate(
        key=unit.key,
        rank=rank,
        score=score,
        relative_path=unit.relative_path,
        document_id=unit.document_id,
        text=unit.text,
        structure_title=str(structure.get("title") or ""),
        parent_title=str(parent.get("title") or ""),
        parent_text=context.parent_texts.get(parent_id, ""),
        previous_text=previous_text,
        next_text=next_text,
        gold_label="other",
    )


def _current_unit(examined: list[StoredUnit], judgments: list[Judgment]) -> StoredUnit | None:
    by_key = {item.key: item.predicted for item in judgments}
    for predicted in ("YES", "UNCERTAIN"):
        for unit in examined:
            if by_key.get(unit.key) == predicted:
                return unit
    return examined[0] if examined else None


def _clause_number(unit: StoredUnit, structures: dict[str, dict[str, object]]) -> str:
    return str(structures.get(unit.structure_id, {}).get("clause_number") or "")


def _validated_answers(
    examined: list[StoredUnit],
    structures: dict[str, dict[str, object]],
    status: str,
    pairs: list[tuple[str, str, str]],
    notes: str,
) -> tuple[list[SourceRef], list[str], str, str]:
    if status != ANSWERED:
        return [], [], "", notes
    by_key = {unit.key: unit for unit in examined}
    sources: list[SourceRef] = []
    source_ids: list[str] = []
    seen: set[str] = set()
    for source_id, excerpt, _excerpt_id in pairs:
        unit = by_key.get(source_id)
        if unit is None or excerpt in seen:
            continue
        ref = source_ref(
            unit,
            excerpt,
            clause_number=_clause_number(unit, structures),
        )
        if not ref.validated:
            continue
        seen.add(excerpt)
        sources.append(ref)
        source_ids.append(unit.key)
    answer = "\n\n".join(item.excerpt for item in sources)
    return sources, source_ids, answer, notes


def _empty_cell(
    relative_path: str,
    question_id: str,
    user_question: str,
    variant: str,
    retrieve_seconds: float,
    retrieval: dict[str, object],
    status: str,
    notes: str,
) -> CellResult:
    return CellResult(
        document_id=document_short_id(relative_path),
        relative_path=relative_path,
        question_id=question_id,
        question=user_question,
        variant=variant,
        status=status,
        answer="",
        source_unit_ids=[],
        sources=[],
        retrieve_seconds=retrieve_seconds,
        retrieval=retrieval,
        notes=notes,
    )


def _as_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _fresh_jev(jev: JevClient) -> CountingJev:
    inner = jev.inner if isinstance(jev, CountingJev) else jev
    return CountingJev(inner)
