"""Lossless source-text sharing and request-local references for the assessor."""

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.services.research.assessment import ResearchAssessmentDraft

_AUDIT_ONLY_KEYS = {
    "legal_result",
    "derived_claims",  # Structured analyses have their own fields.
    "graph_fact_ids",
    "supporting_text_unit_ids",
    "document_ids",
    "document_version_ids",
    "document_version_id",
    "canonical_document_id",
    "text_unit_ids",
    "knowledge_claim_ids",
    "research_evidence_id",
    "answer_fact_id",
    "domain_result_id",
    "reused_domain_result_id",
    "answered_by_question_key",
    "previous_answer_status",
    "passage_candidate_ids",
    "passage_kept_ids",
    "mcp_calls",
    "retrieval_origins",
    "search_rank",
    "query_term_overlap",
    "selection_why",
    "reused_text_units",
    "passage_router",
    "access_mechanism",
    "retrieval_provider",
}
_REUSE_AUDIT_KEYS = {"origin", "knowledge_question_id", "relation", "relation_sv", "evidence_ref"}


def compact_provenance(provenance: Mapping[str, object]) -> dict[str, object]:
    # Remove known storage/diagnostic fields, never unknown semantic warnings.
    result = {
        key: value for key, value in provenance.items() if key not in _AUDIT_ONLY_KEYS | {"reuse"}
    }
    reuse = provenance.get("reuse")
    if isinstance(reuse, dict):
        semantic_reuse = {
            key: value for key, value in reuse.items() if key not in _REUSE_AUDIT_KEYS
        }
        if semantic_reuse:
            result["reuse"] = semantic_reuse
    return result


def _paragraphs(text: str) -> Iterable[str]:
    # Include separators in their preceding fragment: concatenation is byte-exact.
    start = 0
    for match in re.finditer(r"\n[ \t\r]*\n+", text):
        yield text[start : match.end()]
        start = match.end()
    if start < len(text):
        yield text[start:]


@dataclass(frozen=True)
class AssessmentInput:
    payload: dict[str, object]
    evidence_ids: dict[str, str]

    def restore(self, draft: ResearchAssessmentDraft) -> ResearchAssessmentDraft:
        def canonical(refs: Sequence[str]) -> list[str]:
            # Only IDs actually exposed to this model call can become citations.
            return [self.evidence_ids[ref] for ref in refs if ref in self.evidence_ids]

        return replace(
            draft,
            need_assessments=[
                replace(
                    row,
                    supporting_evidence_ids=canonical(row.supporting_evidence_ids),
                )
                for row in draft.need_assessments
            ],
            considered_evidence_ids=canonical(draft.considered_evidence_ids),
        )


def encode_assessment_input(rows: Sequence[dict[str, Any]]) -> AssessmentInput:
    evidence_ids = {}
    fragments: dict[str, str] = {}
    sources: dict[str, str] = {}
    evidence = []
    for index, original in enumerate(rows):
        row = dict(original)
        ref = f"e{index}"
        evidence_ids[ref] = row["evidence_id"]
        row["evidence_id"] = ref
        duplicate_ids = row.pop("duplicate_evidence_ids", [])
        row["duplicate_count"] = len(duplicate_ids)
        row.pop("content_hash", None)
        source = row.get("source_id") or row.get("source_url")
        if source:
            row["source_id"] = sources.setdefault(source, f"s{len(sources)}")
        text = row.pop("excerpt")
        row["passage_ids"] = (
            None
            if text is None
            else [
                fragments.setdefault(fragment, f"p{len(fragments)}")
                for fragment in _paragraphs(text)
            ]
        )
        evidence.append(row)
    return AssessmentInput(
        payload={
            "evidence": evidence,
            "passages": {ref: text for text, ref in fragments.items()},
        },
        evidence_ids=evidence_ids,
    )
