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
    adjustment_requested: bool | None = None
    adjustment_granted: bool | None = None
    adjusted_term_type: str | None = None
    contract_type: str | None = None
    decisive_factors: list[str] = Field(default_factory=list)
    rejected_arguments: list[str] = Field(default_factory=list)
    party_context: Literal["consumer", "commercial", "mixed", "other", "unknown"] = "unknown"
    rule_or_principle: str | None = None
    applied_provisions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[LegalCitation] = Field(default_factory=list)


class PreparatoryWorkAnalysis(BaseModel):
    legislative_intent: str
    proposal_or_commentary: str
    interpretation_guidance: list[str] = Field(default_factory=list)
    policy_considerations: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    provisions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[LegalCitation] = Field(default_factory=list)


class StatuteAnalysis(BaseModel):
    operative_rule: str
    conditions: list[str] = Field(default_factory=list)
    legal_effects: list[str] = Field(default_factory=list)
    cross_references: list[str] = Field(default_factory=list)
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
        if not selected.citations:
            raise ValueError("legal analysis requires a verified citation")
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
        lines.extend(
            (
                f"Adjustment requested: {analysis.adjustment_requested}",
                f"Adjustment granted: {analysis.adjustment_granted}",
                f"Adjusted term type: {analysis.adjusted_term_type or 'unknown'}",
                f"Contract type: {analysis.contract_type or 'unknown'}",
                f"Party context: {analysis.party_context}",
            )
        )
        lines.extend(f"Decisive factor: {factor}" for factor in analysis.decisive_factors)
        lines.extend(f"Rejected argument: {argument}" for argument in analysis.rejected_arguments)
    elif result.preparatory_work is not None:
        lines.extend(
            (
                f"Legislative intent: {result.preparatory_work.legislative_intent}",
                f"Proposal/commentary: {result.preparatory_work.proposal_or_commentary}",
            )
        )
        analysis = result.preparatory_work
        lines.extend(
            f"Interpretation guidance: {value}" for value in analysis.interpretation_guidance
        )
        lines.extend(f"Policy consideration: {value}" for value in analysis.policy_considerations)
    else:
        assert result.statute is not None
        lines.append(f"Operative rule: {result.statute.operative_rule}")
        analysis = result.statute
        lines.extend(f"Condition: {value}" for value in analysis.conditions)
        lines.extend(f"Legal effect: {value}" for value in analysis.legal_effects)
    for citation in analysis.citations:
        lines.append(
            f'Verified quote: "{citation.quote}" ({citation.pinpoint or citation.source_uri})'
        )
    if result.truncated:
        lines.append("Source text was truncated during retrieval.")
    return lines
