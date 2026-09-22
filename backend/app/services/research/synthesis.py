"""Domain-neutral, provenance-preserving aggregation of answered child needs.

A derived answer contains the children's verified statements, not new primary
facts. The normal assessor must still decide whether they answer the parent.
"""

import hashlib
import json
from collections.abc import Sequence

from app.services.research.assessment import AssessableEvidence, ResearchAssessmentDraft
from app.services.research.followup import RuntimeResearchNeed
from app.services.research.models import ResearchEvidence, research_evidence


def derive_parent_answers(
    needs: Sequence[RuntimeResearchNeed],
    assessment: ResearchAssessmentDraft,
    evidence: Sequence[AssessableEvidence],
) -> list[ResearchEvidence]:
    by_id = {item.evidence_id: item for item in evidence}
    answered = {row.research_need_id: row for row in assessment.need_assessments if row.sufficient}
    parents: dict[str, list[RuntimeResearchNeed]] = {}
    known = {need.research_need_id: need for need in needs}
    for need in needs:
        parent = need.parent_research_need_id
        if (
            parent in known
            and parent != need.research_need_id
            and need.research_need_id in answered
        ):
            parents.setdefault(parent, []).append(need)
    results = []
    for parent, children in sorted(parents.items()):
        if parent in answered:
            continue
        inputs = []
        claims = []
        lines = []
        for child in sorted(children, key=lambda row: row.research_need_id):
            for evidence_id in answered[child.research_need_id].supporting_evidence_ids:
                item = by_id.get(evidence_id)
                if item is None or item.status != "found":
                    continue
                if child.research_need_id not in (
                    item.research_need_ids or (item.research_need_id,)
                ):
                    continue
                if item.provenance.get("derived"):
                    continue  # Never make a circular/transitively self-supporting derivation.
                if not item.claims and not item.excerpt:
                    continue
                inputs.append(
                    {
                        "child_need_id": child.research_need_id,
                        "evidence_id": evidence_id,
                        "content_hash": item.content_hash,
                        "child_assessment": {
                            "sufficient": True,
                            "supporting_evidence_ids": list(
                                answered[child.research_need_id].supporting_evidence_ids
                            ),
                        },
                    }
                )
                lines.append(f"{child.question}\n{item.excerpt or ''}")
                for claim in item.claims:
                    lines.append(
                        f"{claim['predicate']}: {json.dumps(claim['value'], ensure_ascii=False)}"
                    )
                    claims.append(
                        {
                            **claim,
                            "derived": True,
                            "research_need_id": parent,
                            "source_claim_id": claim["id"],
                            "source_evidence_id": evidence_id,
                            "source_need_id": child.research_need_id,
                        }
                    )
        if not inputs:
            continue
        fingerprint = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        for claim in claims:
            claim["id"] = hashlib.sha256(
                f"{parent}:{fingerprint}:{claim['source_claim_id']}".encode()
            ).hexdigest()
        results.append(
            research_evidence(
                research_need_id=parent,
                source_type="derived",
                status="found",
                title=known[parent].question,
                excerpt="\n\n".join(lines),
                provider="research_synthesis",
                source_id=f"derived:{parent}:{fingerprint}",
                metadata={
                    "derived": True,
                    "primary_source": False,
                    "source_nature": "secondary",
                    "derivation": "answered_child_aggregation",
                    "inputs": inputs,
                    "derived_claims": claims,
                },
            )
        )
    return results
