"""The legal domain result, independent of retrieval and the generic research engine."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, computed_field, model_validator

LEGAL_RESULT_SCHEMA_VERSION = 7


class CitationGroundingError(ValueError):
    """A citation does not refer to an exact span in the fetched source."""


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
    quote: str = ""
    source_span_id: str | None = None
    pinpoint: str | None = None


class CourtStatement(BaseModel):
    court_level: Literal["supreme", "appeal", "first_instance", "specialist", "unknown"]
    text_role: Literal[
        "majority_reasons",
        "operative_order",
        "lower_court",
        "party_submission",
        "dissent",
        "reporter_proposal",
    ]
    outcome: str
    decision_basis: Literal[
        "statutory_adjustment", "contract_interpretation", "other", "not_determined"
    ] = Field(
        default="not_determined",
        description="statutory_adjustment means modifying a contract term under an adjustment power; "
        "contract_interpretation means construing the meaning of a contractual term. Interpreting "
        "or applying another statute (for example statutory good-faith rules) is other, not "
        "contract_interpretation. Use not_determined when the reasons do not establish the basis.",
    )
    adjustment_granted: bool | None = Field(
        default=None,
        description="Whether this court legally adjusted the CONTRACT term. Appellate reversal, repayment and contract interpretation alone are not adjustment.",
    )
    citations: list[LegalCitation] = Field(min_length=1)


class CaseLawAnalysis(BaseModel):
    @model_validator(mode="after")
    def validate_holding(self) -> CaseLawAnalysis:
        holding = self.authoritative_holding
        if holding is not None:
            if holding.text_role not in {"majority_reasons", "operative_order"}:
                raise ValueError(
                    "established holding requires the deciding court's majority or order"
                )
            if holding.court_level == "unknown":
                raise ValueError("established holding requires an identified court level")
            if (
                holding.adjustment_granted is True
                and holding.decision_basis != "statutory_adjustment"
            ):
                raise ValueError("granted adjustment requires statutory_adjustment decision basis")
        return self

    @computed_field
    @property
    def holding_status(self) -> Literal["established", "not_determined"]:
        return "established" if self.authoritative_holding is not None else "not_determined"

    @computed_field
    @property
    def outcome(self) -> str:
        return (
            self.authoritative_holding.outcome if self.authoritative_holding else "Not determined"
        )

    @computed_field
    @property
    def adjustment_granted(self) -> bool | None:
        return self.authoritative_holding.adjustment_granted if self.authoritative_holding else None

    legal_issue: str
    court_reasoning: str = Field(
        description="Explain the deciding court majority’s actual legal reasoning and basis before classifying its outcome. Distinguish interpretation of an existing obligation from modification of that obligation under a statutory adjustment power."
    )
    adjustment_requested: bool | None = None
    adjusted_term_type: str | None = None
    contract_type: str | None = None
    decisive_factors: list[str] = Field(default_factory=list)
    rejected_arguments: list[str] = Field(default_factory=list)
    party_context: Literal["consumer", "commercial", "mixed", "other", "unknown"] = "unknown"
    rule_or_principle: str | None = None
    applied_provisions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    citations: list[LegalCitation] = Field(default_factory=list)

    other_statements: list[CourtStatement] = Field(default_factory=list)
    authoritative_holding: CourtStatement | None = None


PreparatoryTextRole = Literal[
    "government_special_commentary", "government_general_reasoning", "consultation_response",
    "inquiry_proposal", "committee_statement", "proposed_statutory_text", "contents", "unknown",
]


class PreparatoryAttribution(BaseModel):
    speaker: str
    text_role: PreparatoryTextRole
    requested_text_role: Literal[
        "any", "government_special_commentary", "government_general_reasoning",
        "consultation_response", "inquiry_proposal", "committee_statement",
        "proposed_statutory_text", "contents", "unknown",
    ]
    role_citations: list[LegalCitation] = Field(min_length=1, description="Cite the actual heading or speaker introduction establishing the text role, not the user's question. Use unknown when the supplied passage cannot establish it.")


class PreparatoryWorkAnalysis(BaseModel):
    attribution: PreparatoryAttribution | None = None
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
    relation: Literal["supports", "limits", "contradicts", "contextual", "unclear", "irrelevant"]
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
        citations = list(selected.citations)
        if self.preparatory_work and self.preparatory_work.attribution:
            citations.extend(self.preparatory_work.attribution.role_citations)
        if self.case_law is not None:
            statements = list(self.case_law.other_statements)
            if self.case_law.authoritative_holding is not None:
                statements.append(self.case_law.authoritative_holding)
            citations.extend(
                citation for statement in statements for citation in statement.citations
            )
        for citation in citations:
            if citation.source_uri != self.source.canonical_uri:
                raise CitationGroundingError("citation URI differs from retrieved source")
            if not citation.quote or citation.quote not in self.raw_text:
                raise CitationGroundingError(
                    f"citation quote is absent from raw source: {citation.quote!r}"
                )
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
                f"Holding status: {result.case_law.holding_status}",
                f"Authoritative holding: {result.case_law.authoritative_holding}",
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
        if analysis.attribution:
            attribution = analysis.attribution
            lines.extend((
                f"Source speaker: {attribution.speaker}",
                f"Source text role: {attribution.text_role}",
                f"Requested text role: {attribution.requested_text_role}",
            ))
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
