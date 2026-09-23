"""Speaker and text-role grounding must survive interpretation and projection."""

import pytest
from pydantic import ValidationError

from app.llm.legal_research import LegalInterpretation
from app.services.legal_research_result import LegalResearchResult, legal_result_summary

URI = "https://lagen.nu/prop/1975/76:81#a4.2.1"
TEXT = "Remissinstanserna anför följande. Sveriges domareförbund föreslår särskild hänsyn."


def payload(
    role="consultation_response", relation="contextual", requested="government_special_commentary"
):
    return {
        "relation": {
            "relation": relation,
            "explanation": "Remissyttrande, inte regeringens motivering.",
            "confidence": "high",
        },
        "preparatory_work": {
            "legislative_intent": "Domareförbundets uppfattning.",
            "proposal_or_commentary": "Remissyttrande.",
            "attribution": {
                "speaker": "Sveriges domareförbund",
                "text_role": role,
                "requested_text_role": requested,
                "role_citations": [
                    {"source_uri": URI, "quote": "Remissinstanserna anför följande."}
                ],
            },
            "citations": [
                {"source_uri": URI, "quote": "Sveriges domareförbund föreslår särskild hänsyn."}
            ],
        },
    }


@pytest.mark.parametrize(
    "role",
    [
        "consultation_response",
        "inquiry_proposal",
        "proposed_statutory_text",
        "government_general_reasoning",
        "unknown",
        "contents",
    ],
)
def test_other_roles_cannot_directly_answer_question_about_special_commentary(role):
    result = LegalInterpretation.model_validate(payload(role=role, relation="supports"))
    assert result.relation.relation == "contextual"
    assert result.relation.confidence == "low"
    assert result.relation.unresolved_questions
    assert "source attribution check" in result.preparatory_work.limitations[-1]


def test_consultation_response_can_answer_a_question_about_consultation_responses():
    result = LegalInterpretation.model_validate(
        payload(relation="supports", requested="consultation_response")
    )
    assert result.relation.relation == "supports"


def test_special_commentary_can_support_matching_question():
    assert LegalInterpretation.model_validate(
        payload(role="government_special_commentary", relation="supports")
    )


def test_missing_attribution_cannot_pass_new_interpretation():
    data = payload()
    data["preparatory_work"]["attribution"] = None
    with pytest.raises(ValidationError, match="requires source attribution"):
        LegalInterpretation.model_validate(data)


def test_role_grounding_and_projection_keep_the_actual_speaker():
    data = payload()
    result = LegalResearchResult.model_validate(
        {
            **data,
            "source": {"kind": "preparatory_work", "title": "Proposition", "canonical_uri": URI},
            "raw_text": TEXT,
        }
    )
    from app.services.research_domain_results import legal_claims
    claims = legal_claims(result, result_id="r1", research_need_id="n1")
    speaker = next(claim for claim in claims if claim.predicate == "legal.source_speaker")
    assert speaker.value == {"value": "Sveriges domareförbund"}
    assert speaker.citations[0]["quote"] == "Remissinstanserna anför följande."
    summary = "\n".join(legal_result_summary(result))
    assert "Source speaker: Sveriges domareförbund" in summary
    assert "Source text role: consultation_response" in summary
    assert "Legal relation: contextual" in summary
    data["preparatory_work"]["attribution"]["role_citations"][0]["quote"] = (
        "Regeringens specialmotivering"
    )
    with pytest.raises(ValidationError, match="absent from raw source"):
        LegalResearchResult.model_validate(
            {
                **data,
                "source": {
                    "kind": "preparatory_work",
                    "title": "Proposition",
                    "canonical_uri": URI,
                },
                "raw_text": TEXT,
            }
        )


async def test_independent_source_role_is_unprimed_and_cannot_be_overwritten(monkeypatch):
    import app.llm.legal_research as module
    from app.services.legal_research_result import LegalSourceIdentity
    from app.services.prompt_catalog import default_prompts
    from tests.test_research import _context

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    async def prompts(*_args, **_kwargs):
        return default_prompts("sv")

    monkeypatch.setattr(module, "require_active_prompts", prompts)
    interpretations = 0
    question = "UNIQUE_RESEARCH_QUESTION specialmotiveringen"

    async def complete(messages, schema):
        nonlocal interpretations
        if schema is module.PreparatorySourceRole:
            assert question not in str(messages)
            assert "UNIQUE_RESEARCH_QUESTION" not in str(messages)
            assert TEXT in str(messages)
            return {
                "speaker": "Sveriges domareförbund",
                "text_role": "consultation_response",
                "role_span_ids": ["s0"],
            }
        interpretations += 1
        # Try to overwrite the independently established role to fit the question.
        result = payload(
            role="government_special_commentary",
            relation="supports" if interpretations == 1 else "contextual",
        )
        result["preparatory_work"]["citations"][0].update(source_span_id="s0", quote="")
        return result

    interpreter = module.LlmLegalInterpreter(completer=complete, session_factory=Session)
    result = await interpreter.interpret(
        source=LegalSourceIdentity(kind="preparatory_work", title="Proposition", canonical_uri=URI),
        question=question,
        raw_text=TEXT,
        truncated=False,
        context=_context(),
    )
    assert interpretations == 1
    assert result.relation.relation == "contextual"
    assert result.preparatory_work.attribution.text_role == "consultation_response"
    assert result.preparatory_work.attribution.role_citations[0].quote == TEXT
