"""lagen.nu adapter projects legal entities on the generic graph."""

from __future__ import annotations

from app.services.knowledge.claims import SUPPORTED_BY, KnowledgeClaim
from app.services.knowledge.relationships import ABOUT, SAME_AS
from app.services.lagen_nu.legal_graph import (
    LEGAL_APPLIES,
    LEGAL_CITES,
    LEGAL_COURT,
    LEGAL_DECIDED_BY,
    LEGAL_ISSUE,
    LEGAL_PROVISION,
    LEGAL_SOURCE,
    ground_legal_graph,
)
from app.services.legal_research_result import (
    CaseLawAnalysis,
    CourtStatement,
    LegalCitation,
    LegalQuestionRelation,
    LegalResearchResult,
    LegalSourceIdentity,
)

URI = "https://lagen.nu/dom/nja/2005s142"
HOLDING = "Högsta domstolen ogillade yrkandet om jämkning enligt 36 §."


def _result() -> LegalResearchResult:
    return LegalResearchResult(
        source=LegalSourceIdentity(
            kind="case_law",
            title="NJA 2005 s. 142",
            canonical_uri=URI,
            identifier="NJA 2005 s. 142",
            court="Högsta domstolen",
        ),
        relation=LegalQuestionRelation(
            relation="limits",
            explanation="Avtalstolkning, inte jämkning.",
            confidence="high",
        ),
        case_law=CaseLawAnalysis(
            legal_issue="Jämkning",
            court_reasoning=HOLDING,
            applied_provisions=["36 § avtalslagen"],
            authoritative_holding=CourtStatement(
                court_level="supreme",
                text_role="majority_reasons",
                outcome="Ogillat",
                adjustment_granted=False,
                citations=[LegalCitation(source_uri=URI, quote=HOLDING)],
            ),
            citations=[LegalCitation(source_uri=URI, quote=HOLDING)],
        ),
        raw_text=HOLDING,
    )


def _claim(predicate: str, value: object, *unit_ids: str) -> KnowledgeClaim:
    return KnowledgeClaim(
        id=f"claim-{predicate}",
        customer_id=7,
        document_id="doc-a",
        document_version_id="ver-a",
        predicate=predicate,
        value={"value": value},
        supporting_text_unit_ids=tuple(unit_ids),
    )


def test_legal_graph_uses_core_edges_then_namespaced_legal_relations():
    claims = [
        _claim("legal.adjustment_granted", False, "tu-hold"),
        _claim("legal.applied_provision", "36 § avtalslagen", "tu-hold"),
    ]
    entities, edges = ground_legal_graph(
        _result(),
        claims,
        customer_id=7,
        document_id="doc-a",
    )
    types = {entity.entity_type for entity in entities}
    assert types == {LEGAL_SOURCE, LEGAL_COURT, LEGAL_ISSUE, LEGAL_PROVISION}
    relations = {edge.relation for edge in edges}
    assert {ABOUT, SUPPORTED_BY, SAME_AS, LEGAL_APPLIES, LEGAL_DECIDED_BY} <= relations
    assert all(edge.to_id != edge.from_id or edge.relation != LEGAL_CITES for edge in edges)
    assert any(
        edge.relation == SUPPORTED_BY
        and edge.from_kind == "claim"
        and edge.to_id == "tu-hold"
        for edge in edges
    )
    assert any(edge.relation == SAME_AS for edge in edges)
