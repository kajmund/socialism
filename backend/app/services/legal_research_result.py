"""The legal domain result, independent of retrieval and the generic research engine."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class LegalSourceIdentity(BaseModel):
    kind: Literal["case_law", "preparatory_work", "statute"]
    title: str
    canonical_uri: str
    identifier: str | None = None
    court: str | None = None
    authority: str | None = None
    decision_date: date | None = None
    publication_year: int | None = None
    publisher_url: str | None = None


class LegalCitation(BaseModel):
    source_uri: str
    quote: str
    pinpoint: str | None = None


class CaseLawAnalysis(BaseModel):
    legal_issue: str
    court_reasoning: str
    outcome: str
    rule_or_principle: str | None = None
    applied_provisions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[LegalCitation] = Field(default_factory=list)


class PreparatoryWorkAnalysis(BaseModel):
    legislative_intent: str
    proposal_or_commentary: str
    provisions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[LegalCitation] = Field(default_factory=list)


class StatuteAnalysis(BaseModel):
    operative_rule: str
    conditions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    citations: list[LegalCitation] = Field(default_factory=list)


class LegalQuestionRelation(BaseModel):
    relation: Literal["supports", "limits", "contradicts", "contextual", "unclear"]
    explanation: str
    confidence: Literal["high", "medium", "low"]
    unresolved_questions: list[str] = Field(default_factory=list)


class LegalResearchResult(BaseModel):
    source: LegalSourceIdentity
    relation: LegalQuestionRelation
    case_law: CaseLawAnalysis | None = None
    preparatory_work: PreparatoryWorkAnalysis | None = None
    statute: StatuteAnalysis | None = None
    raw_text: str
    truncated: bool = False

    @model_validator(mode="after")
    def validate_source(self) -> LegalResearchResult:
        analyses = {
            "case_law": self.case_law,
            "preparatory_work": self.preparatory_work,
            "statute": self.statute,
        }
        if sum(value is not None for value in analyses.values()) != 1:
            raise ValueError("exactly one legal analysis is required")
        selected = analyses[self.source.kind]
        if selected is None:
            raise ValueError("legal analysis does not match source kind")
        if not self.raw_text.strip():
            raise ValueError("raw source text is required")
        for citation in selected.citations:
            if citation.source_uri != self.source.canonical_uri:
                raise ValueError("citation URI differs from retrieved source")
            if not citation.quote or citation.quote not in self.raw_text:
                raise ValueError("citation quote is absent from raw source")
        return self


def legal_result_summary(result: LegalResearchResult) -> list[str]:
    """Compact, source-grounded domain facts for expert prompts."""
    lines = [
        f"Legal relation: {result.relation.relation} ({result.relation.confidence})",
        f"Reason: {result.relation.explanation}",
    ]
    if result.case_law is not None:
        lines.extend(
            (
                f"Legal issue: {result.case_law.legal_issue}",
                f"Court reasoning: {result.case_law.court_reasoning}",
                f"Outcome: {result.case_law.outcome}",
            )
        )
        analysis = result.case_law
    elif result.preparatory_work is not None:
        lines.extend(
            (
                f"Legislative intent: {result.preparatory_work.legislative_intent}",
                f"Proposal/commentary: {result.preparatory_work.proposal_or_commentary}",
            )
        )
        analysis = result.preparatory_work
    else:
        assert result.statute is not None
        lines.append(f"Operative rule: {result.statute.operative_rule}")
        analysis = result.statute
    for citation in analysis.citations:
        lines.append(
            f'Verified quote: "{citation.quote}" ({citation.pinpoint or citation.source_uri})'
        )
    if result.truncated:
        lines.append("Source text was truncated during retrieval.")
    return lines
