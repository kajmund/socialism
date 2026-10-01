"""Human-authored legal benchmark expectations, separate from schema validity."""

import hashlib

from pydantic import BaseModel, Field, model_validator

from app.services.legal_research_result import LegalResearchResult, LegalSourceIdentity


class LegalExpectation(BaseModel):
    holding_established: bool
    adjustment_granted: bool | None
    decision_basis: str | None = None
    court_level: str | None = None
    forbidden_holding_spans: list[str] = Field(default_factory=list)


class LegalBenchmarkInput(BaseModel):
    id: str
    source: LegalSourceIdentity
    question: str
    raw_text: str = Field(min_length=1)
    raw_text_sha256: str
    truncated: bool = False
    expected: LegalExpectation

    @model_validator(mode="after")
    def bind_expectations(self):
        if hashlib.sha256(self.raw_text.encode()).hexdigest() != self.raw_text_sha256:
            raise ValueError("Legal expectations must match the exact source text")
        return self


def check_legal_quality(result: LegalResearchResult, case: LegalBenchmarkInput) -> dict[str, bool]:
    analysis = result.case_law
    if analysis is None:
        raise ValueError("This benchmark requires a case-law interpretation")
    holding = analysis.authoritative_holding
    expected = case.expected
    checks = {
        "source_identity": result.source.canonical_uri == case.source.canonical_uri,
        "same_source_text": result.raw_text == case.raw_text,
        "holding_established": (holding is not None) == expected.holding_established,
        "adjustment_granted": analysis.adjustment_granted == expected.adjustment_granted,
        "no_forbidden_holding_spans": not holding
        or all(
            citation.source_span_id not in expected.forbidden_holding_spans
            for citation in holding.citations
        ),
    }
    if expected.court_level is not None:
        checks["court_level"] = holding is not None and holding.court_level == expected.court_level
    if expected.decision_basis is not None:
        checks["decision_basis"] = (
            holding is not None and holding.decision_basis == expected.decision_basis
        )
    return checks
