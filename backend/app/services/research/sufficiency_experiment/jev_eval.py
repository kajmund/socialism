"""Passage evaluation through existing evidence-screen NOUL questions."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence

from app.jev.system import JevClientError, JevSystemOne, parse_noul
from app.services.research.assessment import AssessableEvidence
from app.services.research.evidence_screen import (
    EVIDENCE_SCREEN_QUESTIONS,
    EvidenceJevScores,
)
from app.services.research.models import ResearchNeed
from app.services.research.quality import QualityEvidenceInput, independence_key
from app.services.research.sufficiency_experiment.types import (
    EvidencePassage,
    ExperimentConfig,
    PassageEvaluation,
)


def quality_input_from_evidence(item: AssessableEvidence) -> QualityEvidenceInput:
    return QualityEvidenceInput(
        item_id=item.evidence_id,
        original_evidence_id=item.evidence_id,
        research_need_id=item.research_need_id,
        source_type=item.source_type,
        status=item.status,
        title=item.title,
        excerpt=item.excerpt,
        locator=item.locator,
        source_id=item.source_id,
        source_url=item.source_url,
        provider=item.provider,
        provenance=dict(item.provenance),
        retrieved_at=item.retrieved_at,
        content_hash=item.content_hash,
    )


def quality_inputs(evidence: Sequence[AssessableEvidence]) -> dict[str, QualityEvidenceInput]:
    return {item.evidence_id: quality_input_from_evidence(item) for item in evidence}


def evaluation_jobs(
    needs: Sequence[ResearchNeed],
    passages: Sequence[EvidencePassage],
    *,
    counterparts: Mapping[str, tuple[str, ...]] | None = None,
) -> list[dict[str, object]]:
    jobs: list[dict[str, object]] = []
    for need in needs:
        for passage in passages:
            if passage.research_need_ids and need.id not in passage.research_need_ids:
                continue
            jobs.append(
                {
                    "job_id": f"{need.id}:{passage.passage_id}",
                    "need_id": need.id,
                    "question": need.question,
                    "passage_id": passage.passage_id,
                    "evidence_id": passage.evidence_id,
                    "text": passage.text,
                    "content_hash": passage.content_hash,
                    "start": passage.start,
                    "end": passage.end,
                    "counterpart_passage_ids": (
                        counterparts.get(passage.passage_id, ()) if counterparts else ()
                    ),
                }
            )
    return jobs


async def evaluate_job(
    job: dict[str, object],
    client: JevSystemOne,
    config: ExperimentConfig,
    *,
    quality_item: QualityEvidenceInput | None = None,
) -> PassageEvaluation:
    try:
        result = await client.ask(
            state={
                "need_id": job["need_id"],
                "question": job["question"],
                "passage_id": job["passage_id"],
                "evidence_id": job["evidence_id"],
                "passage": job["text"],
            },
            questions=EVIDENCE_SCREEN_QUESTIONS,
            model=config.jev_model,
            timeout_seconds=config.jev_timeout_seconds,
        )
        scores = EvidenceJevScores(
            evidence_id=str(job["evidence_id"]),
            source_type="case_knowledge",
            content_hash=str(job["content_hash"]),
            relevant_to_question=parse_noul(result.answers, "relevant_to_question"),
            directly_supports_answer=parse_noul(result.answers, "directly_supports_answer"),
            contradicts_current_evidence=parse_noul(
                result.answers, "contradicts_current_evidence"
            ),
            material_new_information=parse_noul(result.answers, "material_new_information"),
            likely_duplicate_or_redundant=parse_noul(
                result.answers, "likely_duplicate_or_redundant"
            ),
            primary_or_high_authority_for_question=parse_noul(
                result.answers, "primary_or_high_authority_for_question"
            ),
            latency_ms=result.latency_ms,
        )
        error = None
    except (JevClientError, TimeoutError, ValueError) as exc:
        scores = EvidenceJevScores(
            evidence_id=str(job["evidence_id"]),
            source_type="case_knowledge",
            content_hash=str(job["content_hash"]),
            relevant_to_question=0.0,
            directly_supports_answer=0.0,
            contradicts_current_evidence=0.0,
            material_new_information=0.0,
            likely_duplicate_or_redundant=0.0,
            primary_or_high_authority_for_question=0.0,
            latency_ms=0.0,
        )
        error = type(exc).__name__
    key = independence_key(quality_item) if quality_item is not None else str(job["evidence_id"])
    return PassageEvaluation(
        job_id=str(job["job_id"]),
        need_id=str(job["need_id"]),
        passage_id=str(job["passage_id"]),
        evidence_id=str(job["evidence_id"]),
        scores=scores,
        independence_key=key,
        error=error,
        counterpart_passage_ids=tuple(job.get("counterpart_passage_ids", ())),
    )


async def evaluate_jobs(
    jobs: Sequence[dict[str, object]],
    client: JevSystemOne,
    config: ExperimentConfig,
    items: dict[str, QualityEvidenceInput],
) -> list[PassageEvaluation]:
    slots = asyncio.Semaphore(config.jev_concurrency)

    async def one(job: dict[str, object]) -> PassageEvaluation:
        async with slots:
            return await evaluate_job(
                job,
                client,
                config,
                quality_item=items.get(str(job["evidence_id"])),
            )

    return list(await asyncio.gather(*[one(job) for job in jobs]))
