"""Persistent evaluation artifacts. Unique per security scope and evaluation key."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import JevEvaluationArtifactRecord
from app.jev.evaluation import (
    EVALUATION_STATUS_VALID,
    EvaluationArtifact,
    artifact_id,
)


async def get_artifact(
    session: AsyncSession,
    *,
    evaluation_key: str,
    security_scope: str,
) -> EvaluationArtifact | None:
    row = (
        await session.execute(
            select(JevEvaluationArtifactRecord).where(
                JevEvaluationArtifactRecord.security_scope == security_scope,
                JevEvaluationArtifactRecord.evaluation_key == evaluation_key,
                JevEvaluationArtifactRecord.status == EVALUATION_STATUS_VALID,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    artifact = _from_row(row)
    # Callers keep the copied artifact. The row must not outlive this read.
    session.expunge(row)
    return artifact


async def put_artifact(
    session: AsyncSession,
    artifact: EvaluationArtifact,
) -> EvaluationArtifact:
    """Insert or return the winner. Concurrent writers must not fail the caller."""
    if artifact.status != EVALUATION_STATUS_VALID:
        raise ValueError("only valid evaluations can be stored")
    existing = await get_artifact(
        session,
        evaluation_key=artifact.evaluation_key,
        security_scope=artifact.security_scope,
    )
    if existing is not None:
        return existing
    row = JevEvaluationArtifactRecord(
        id=artifact_id(artifact.security_scope, artifact.evaluation_key),
        security_scope=artifact.security_scope,
        evaluation_key=artifact.evaluation_key,
        evaluator_id=artifact.evaluator_id,
        evaluator_version=artifact.evaluator_version,
        model_provider=artifact.model_provider,
        model=artifact.model,
        status=artifact.status,
        result=dict(artifact.result),
        signals=dict(artifact.signals),
        input_provenance=dict(artifact.input_provenance),
        created_at=artifact.created_at,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        winner = await get_artifact(
            session,
            evaluation_key=artifact.evaluation_key,
            security_scope=artifact.security_scope,
        )
        if winner is None:
            raise
        return winner
    stored = _from_row(row)
    session.expunge(row)
    return stored


def _from_row(row: JevEvaluationArtifactRecord) -> EvaluationArtifact:
    created = row.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    signals = {key: float(value) for key, value in dict(row.signals).items()}
    return EvaluationArtifact(
        evaluation_key=row.evaluation_key,
        security_scope=row.security_scope,
        result=dict(row.result),
        signals=signals,
        evaluator_id=row.evaluator_id,
        evaluator_version=row.evaluator_version,
        model_provider=row.model_provider,
        model=row.model,
        input_provenance=dict(row.input_provenance),
        created_at=created,
        status=row.status,
    )


def utc_now() -> datetime:
    return datetime.now(UTC)
