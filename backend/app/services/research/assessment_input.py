"""Lossless source-text sharing and request-local references for the assessor."""

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from app.services.research.assessment import ResearchAssessmentDraft, ResearchAssessmentError

ASSESSMENT_MAX_INPUT_CHARS = 60_000
ASSESSMENT_PASSAGE_CHARS = 1_500

_MIN_SHARED_TEXT_LENGTH = 32
_MIN_SOURCE_MATCH_LENGTH = 128
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


def _analysis_texts(value: Any) -> list[str]:
    # Small scalar fields stay inline; a reference would add overhead.
    if isinstance(value, str):
        return [value] if len(value) >= _MIN_SHARED_TEXT_LENGTH else []
    if isinstance(value, dict):
        return [text for item in value.values() for text in _analysis_texts(item)]
    if isinstance(value, list):
        return [text for item in value for text in _analysis_texts(item)]
    return []


class PassagePool:
    """Split at exact paragraph/analysis boundaries, sharing the literal text."""

    def __init__(self, shared_texts: set[str]) -> None:
        self.shared_texts = shared_texts
        self.text_ids: dict[str, str] = {}
        self.references: dict[str, list[str]] = {}

    def share(self, text: str) -> list[str]:
        if text in self.references:
            return self.references[text]
        cuts = {0, len(text)}
        for match in re.finditer(r"\n[ \t\r]*\n+", text):
            cuts.update((match.start(), match.end()))
        occurrences = []
        for shared in self.shared_texts:
            start = text.find(shared)
            while start >= 0:
                end = start + len(shared)
                cuts.update((start, end))
                occurrences.append((shared, start, end))
                # Identical overlapping occurrences would create one fragment per character.
                start = text.find(shared, end)
        boundaries = sorted(cuts)
        refs = [
            self.text_ids.setdefault(text[start:end], f"p{len(self.text_ids)}")
            for start, end in zip(boundaries, boundaries[1:])
        ]
        positions = {position: index for index, position in enumerate(boundaries)}
        for shared, start, end in occurrences:
            self.references.setdefault(shared, refs[positions[start] : positions[end]])
        self.references[text] = refs
        return refs

    def payload(self) -> dict[str, str]:
        return {ref: text for text, ref in self.text_ids.items()}


def _share_analysis(
    value: Any,
    pool: PassagePool,
    schemas: dict[tuple[str, ...], str],
) -> Any:
    if isinstance(value, str) and value in pool.shared_texts:
        return {"passage_ids": pool.share(value)}
    if isinstance(value, dict):
        fields = tuple(value)
        schema = schemas.setdefault(fields, f"l{len(schemas)}")
        return {
            "schema_id": schema,
            "values": [_share_analysis(item, pool, schemas) for item in value.values()],
        }
    if isinstance(value, list):
        return [_share_analysis(item, pool, schemas) for item in value]
    return value


@dataclass(frozen=True)
class AssessmentInput:
    payload: dict[str, object]
    evidence_ids: dict[str, str]
    omitted_evidence_ids: tuple[str, ...] = ()

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


def _encode_rows(rows: Sequence[dict[str, Any]]) -> AssessmentInput:
    evidence_ids = {}
    texts = Counter(text for row in rows for text in _analysis_texts(row.get("legal_result")))
    excerpts = [row["excerpt"] for row in rows if row["excerpt"] is not None]
    pool = PassagePool(
        {
            text
            for text, count in texts.items()
            if count > 1
            or (
                len(text) >= _MIN_SOURCE_MATCH_LENGTH
                and any(text in excerpt for excerpt in excerpts)
            )
        }
    )
    # Source passages establish the references before quotations reuse them.
    for row in rows:
        if row["excerpt"] is not None:
            pool.share(row["excerpt"])
    sources: dict[str, str] = {}
    schemas: dict[tuple[str, ...], str] = {}
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
        row["passage_ids"] = None if text is None else pool.share(text)
        row["legal_result"] = _share_analysis(row.get("legal_result"), pool, schemas)
        evidence.append(row)
    return AssessmentInput(
        payload={
            "evidence": evidence,
            "passages": pool.payload(),
            "legal_schemas": {ref: list(fields) for fields, ref in schemas.items()},
        },
        evidence_ids=evidence_ids,
    )

def _truncate_text(text: str) -> str:
    if len(text) <= ASSESSMENT_PASSAGE_CHARS:
        return text
    return text[:ASSESSMENT_PASSAGE_CHARS] + "\n…[trunkerad]"


def _truncate_values(value: Any) -> Any:
    if isinstance(value, str):
        return _truncate_text(value)
    if isinstance(value, dict):
        return {key: _truncate_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_values(item) for item in value]
    return value


def _truncate_row(row: Mapping[str, Any]) -> dict[str, Any]:
    prepared = dict(row)
    excerpt = prepared.get("excerpt")
    if isinstance(excerpt, str):
        prepared["excerpt"] = _truncate_text(excerpt)
    for key in ("legal_result", "claims"):
        if key in prepared:
            prepared[key] = _truncate_values(prepared[key])
    return prepared


def encode_assessment_input(
    rows: Sequence[dict[str, Any]], *, max_chars: int | None = None
) -> AssessmentInput:
    if max_chars is None:
        return _encode_rows(rows)
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    full = [dict(row) for row in rows]
    encoded_full = _encode_rows(full)
    full_payload = {
        **encoded_full.payload,
        "omitted_evidence": [],
        "budget": {
            "max_chars": max_chars,
            "included_evidence": len(full),
            "omitted_evidence": 0,
        },
    }
    if len(json.dumps(full_payload, ensure_ascii=False, separators=(",", ":"))) <= max_chars:
        return AssessmentInput(
            payload=full_payload,
            evidence_ids=encoded_full.evidence_ids,
        )
    prepared = [_truncate_row(row) for row in rows]
    if not prepared:
        empty = _encode_rows([])
        return AssessmentInput(
            payload={**empty.payload, "omitted_evidence": [], "budget": {
                "max_chars": max_chars, "included_evidence": 0, "omitted_evidence": 0,
            }},
            evidence_ids={},
        )
    priority = {
        index: (0 if row.get("status") == "found" else 1, index)
        for index, row in enumerate(prepared)
    }
    selected = list(range(len(prepared)))
    omitted: list[dict[str, Any]] = []
    omitted_ids: list[str] = []
    while selected:
        encoded = _encode_rows([prepared[index] for index in selected])
        payload = {
            **encoded.payload,
            "omitted_evidence": [
                {
                    "evidence_id": row.get("evidence_id"),
                    "research_need_id": row.get("research_need_id"),
                    "status": row.get("status"),
                    "reason": "assessment_char_budget",
                }
                for row in omitted
            ],
            "budget": {
                "max_chars": max_chars,
                "included_evidence": len(selected),
                "omitted_evidence": len(omitted),
            },
        }
        size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        if size <= max_chars:
            return AssessmentInput(
                payload=payload,
                evidence_ids=encoded.evidence_ids,
                omitted_evidence_ids=tuple(omitted_ids),
            )
        drop = max(selected, key=lambda index: priority[index])
        selected.remove(drop)
        omitted.append(prepared[drop])
        omitted_ids.append(str(prepared[drop].get("evidence_id") or ""))
    raise ResearchAssessmentError(
        "assessment evidence does not fit the model input budget"
    )
