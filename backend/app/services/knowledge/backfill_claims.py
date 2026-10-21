"""One-off backfill: materialise legacy SQL claims into OverGraph.

Claims written before the mirror exist only in SQL. The graph must hold every claim before
the SQL tables are dropped (parcel 6), so this walks the legacy rows and writes the logical
claim plus one evidence link per supporting document version, then verifies the result.
"""

from __future__ import annotations

import asyncio

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import KnowledgeClaimRecord, KnowledgeClaimTextUnit
from app.services.knowledge.claims import KnowledgeClaim
from app.services.knowledge.graph_claim_mirror import mirror_claim
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.legal_claims import (
    claim_in_graph,
    evidence_links,
    supporting_text_units,
)


@dataclass
class ClaimBackfillReport:
    rows: int = 0
    mirrored: int = 0
    verified: int = 0
    mismatches: list[str] = field(default_factory=list)

    @property
    def verified_completely(self) -> bool:
        return not self.mismatches and self.mirrored == self.rows == self.verified

    def as_dict(self) -> dict[str, object]:
        return {
            "rows": self.rows,
            "mirrored": self.mirrored,
            "verified": self.verified,
            "mismatches": list(self.mismatches),
        }


async def _support_ids(session: AsyncSession, claim_id: str) -> tuple[str, ...]:
    rows = (
        await session.execute(
            select(KnowledgeClaimTextUnit.text_unit_id)
            .where(KnowledgeClaimTextUnit.claim_id == claim_id)
            .order_by(KnowledgeClaimTextUnit.ordinal, KnowledgeClaimTextUnit.text_unit_id)
        )
    ).all()
    return tuple(row[0] for row in rows)


def _claim_from_row(row: KnowledgeClaimRecord, support: tuple[str, ...]) -> KnowledgeClaim:
    return KnowledgeClaim(
        id=row.id,
        customer_id=row.customer_id,
        predicate=row.predicate,
        value=row.value,
        supporting_text_unit_ids=support,
        scope_type=row.scope_type,
    )


def _verify(claim: KnowledgeClaim, expected_support: tuple[str, ...]) -> str | None:
    catalog = require_knowledge()
    node = claim_in_graph(
        catalog, scope_key=claim.scope.scope_key, identity=claim.id,
    )
    if node is None:
        return f"{claim.id}: missing in graph"
    units = supporting_text_units(catalog, claim.id)
    if sorted(units) != sorted(expected_support):
        return (
            f"{claim.id}: support mismatch "
            f"(graph={sorted(units)} legacy={sorted(expected_support)})"
        )
    if expected_support and not evidence_links(catalog, claim.id):
        return f"{claim.id}: no evidence link"
    return None


async def backfill_claims(session: AsyncSession) -> ClaimBackfillReport:
    report = ClaimBackfillReport()
    claims = list((await session.execute(select(KnowledgeClaimRecord))).scalars().all())
    report.rows = len(claims)
    for row in claims:
        support = await _support_ids(session, row.id)
        claim = _claim_from_row(row, support)
        await asyncio.to_thread(mirror_claim, claim, key=row.id)
        report.mirrored += 1
        problem = await asyncio.to_thread(_verify, claim, support)
        if problem is None:
            report.verified += 1
        else:
            report.mismatches.append(problem)
    return report
