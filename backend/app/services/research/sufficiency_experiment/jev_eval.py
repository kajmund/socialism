"""Parallel Jev evaluations of (need, passage) jobs."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence

from app.jev.system import JevSystemOne, JevSystemOneResult
from app.services.research.models import ResearchNeed, ResearchPlan
from app.services.research.sufficiency_experiment.types import (
    EvaluationJob,
    EvidencePassage,
    ExperimentConfig,
    PassageEvaluation,
    require_verdict,
)

PASSAGE_VERDICT_QUESTION = {
    "verdict": {
        "type": "choice",
        "instructions": (
            "Judge only the supplied passage against the research need. "
            "Do not assume omitted text. Do not invent citations."
        ),
        "criteria": {
            "SUPPORTED": "The passage answers or directly supports the need.",
            "UNSUPPORTED": "The passage does not answer the need.",
            "CONTRADICTS": "The passage contradicts the need or a supporting answer.",
            "UNDECIDED": "The passage is relevant but not enough to decide.",
        },
    }
}


def evaluation_jobs(
    plan: ResearchPlan,
    passages: Sequence[EvidencePassage],
) -> list[EvaluationJob]:
    jobs: list[EvaluationJob] = []
    for need in plan.needs:
        for passage in passages:
            if passage.research_need_ids and need.id not in passage.research_need_ids:
                continue
            jobs.append(
                EvaluationJob(
                    job_id=f"{need.id}:{passage.passage_id}",
                    need_id=need.id,
                    passage=passage,
                )
            )
    return jobs


async def evaluate_jobs(
    jobs: Sequence[EvaluationJob],
    plan: ResearchPlan,
    client: JevSystemOne,
    config: ExperimentConfig,
) -> list[PassageEvaluation]:
    needs = {need.id: need for need in plan.needs}
    slots = asyncio.Semaphore(config.jev_concurrency)

    async def one(job: EvaluationJob) -> PassageEvaluation:
        async with slots:
            return await evaluate_job(job, needs[job.need_id], client, config)

    return list(await asyncio.gather(*[one(job) for job in jobs]))


async def evaluate_job(
    job: EvaluationJob,
    need: ResearchNeed,
    client: JevSystemOne,
    config: ExperimentConfig,
) -> PassageEvaluation:
    state = {
        "need_id": need.id,
        "question": need.question,
        "why_needed": need.why_needed,
        "passage_id": job.passage.passage_id,
        "evidence_id": job.passage.evidence_id,
        "start": job.passage.start,
        "end": job.passage.end,
        "passage": job.passage.text,
    }
    result = await client.ask(
        state=state,
        questions=PASSAGE_VERDICT_QUESTION,
        model=config.jev_model,
        timeout_seconds=config.jev_timeout_seconds,
    )
    return _record(job, result, state)


def _record(
    job: EvaluationJob,
    result: JevSystemOneResult,
    state: dict[str, object],
) -> PassageEvaluation:
    row = result.answers.get("verdict")
    choice = row.get("choice") if isinstance(row, dict) else None
    body = {"state": state, "questions": PASSAGE_VERDICT_QUESTION}
    return PassageEvaluation(
        job_id=job.job_id,
        need_id=job.need_id,
        passage_id=job.passage.passage_id,
        evidence_id=job.passage.evidence_id,
        verdict=require_verdict(choice),
        model=result.model,
        latency_ms=result.latency_ms,
        input_chars=result.input_chars,
        request_hash=hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    )
