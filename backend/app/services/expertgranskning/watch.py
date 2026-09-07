"""Live Word-review watch — WebSocket fan-out and replay payloads."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ExpertgranskningResult, Job
from app.realtime.expertgranskning_broadcast import expertgranskning_broadcast
from app.services.expertgranskning.schemas import ExpertgranskningResultOut


def _result_created_at(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def serialize_result(row: ExpertgranskningResult) -> ExpertgranskningResultOut:
    return ExpertgranskningResultOut(
        id=row.id,
        job_id=row.job_id,
        customer_id=row.customer_id,
        section_index=row.section_index,
        paragraph_index=row.paragraph_index,
        expert_id=row.expert_id,
        expert_namn=row.expert_namn,
        kommentar=row.kommentar,
        is_heading_suggestion=row.is_heading_suggestion,
        comment_id=row.comment_id,
        status=row.status,
        created_at=_result_created_at(row.created_at),
    )


def build_expertgranskning_replay_payload(
    job: Job,
    results: list[ExpertgranskningResult],
) -> dict[str, Any]:
    return {
        "type": "expertgranskning.replay",
        "job_id": job.id,
        "status": job.status,
        "results": [serialize_result(row).model_dump(mode="json") for row in results],
    }


async def load_expertgranskning_results(
    session: AsyncSession, job_id: str
) -> list[ExpertgranskningResult]:
    result = await session.execute(
        select(ExpertgranskningResult)
        .where(ExpertgranskningResult.job_id == job_id)
        .order_by(
            ExpertgranskningResult.section_index,
            ExpertgranskningResult.paragraph_index,
            ExpertgranskningResult.created_at,
        )
    )
    return list(result.scalars().all())


async def publish_result_created(row: ExpertgranskningResult) -> None:
    await expertgranskning_broadcast.publish(
        row.job_id,
        {
            "type": "expertgranskning.result.created",
            "job_id": row.job_id,
            "result": serialize_result(row).model_dump(mode="json"),
        },
    )


async def publish_result_updated(row: ExpertgranskningResult) -> None:
    await expertgranskning_broadcast.publish(
        row.job_id,
        {
            "type": "expertgranskning.result.updated",
            "job_id": row.job_id,
            "result": serialize_result(row).model_dump(mode="json"),
        },
    )


async def publish_expertgranskning_finished(
    job_id: str,
    *,
    status: str,
    error: str | None = None,
    stats: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "type": "expertgranskning.finished",
        "job_id": job_id,
        "status": status,
    }
    if error:
        payload["error"] = error
    if stats is not None:
        payload["stats"] = stats
    await expertgranskning_broadcast.publish(job_id, payload)
