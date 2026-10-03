"""Scope guards for frozen evidence attachments."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import ExecutionRun, EvidenceSet, ExecutionAttempt
from app.services.execution.errors import ExecutionScopeError


async def _load_evidence_set_for_run(
    session: AsyncSession,
    *,
    evidence_set_id: str,
    run: ExecutionRun,
) -> EvidenceSet:
    from app.services.execution.service import get_evidence_set, get_run

    evidence_set = await get_evidence_set(session, evidence_set_id)
    if evidence_set.run_id != run.id:
        from app.services.research.result_execution import may_attach_reused_set

        references = list(
            await session.scalars(
                select(ExecutionAttempt).where(
                    ExecutionAttempt.run_id == run.id,
                    ExecutionAttempt.evidence_set_id == evidence_set.id,
                )
            )
        )
        if not any([await may_attach_reused_set(session, row, evidence_set) for row in references]):
            raise ExecutionScopeError("Attempt may only attach an EvidenceSet from the same run")
    evidence_run = await get_run(session, evidence_set.run_id)
    if evidence_run.customer_id != run.customer_id:
        raise ExecutionScopeError("Attempt may not attach an EvidenceSet owned by another customer")
    return evidence_set
