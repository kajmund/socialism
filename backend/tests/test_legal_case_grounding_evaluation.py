"""The live evaluation oracle must reject lower-court and dissent contamination."""

from types import SimpleNamespace as NS

from scripts.evaluate_legal_case_grounding import CASES, check_result


def fixture(case, *, quote="Majority holding.", relation=None):
    expected = CASES[case]
    raw = (
        "Lower court adjusted.\n"
        + expected["start"]
        + "\nMajority holding.\n"
        + expected["end"]
        + "\nDissent adjusted."
    )
    result = NS(
        relation=NS(relation=relation or ("supports" if expected["supports"] else "contextual")),
        case_law=NS(
            authoritative_holding=NS(
                court_level="supreme",
                adjustment_granted=expected["supports"],
                decision_basis="statutory_adjustment" if expected["supports"] else "other",
                citations=[NS(quote=quote)],
            ),
            decisive_factors=["factor"],
        ),
    )
    return raw, result


def test_true_majority_grounding_passes():
    for case in CASES:
        raw, result = fixture(case)
        assert all(check_result(case, raw, result).values())


def test_lower_court_or_dissent_quote_fails_even_with_correct_labels():
    for quote in ["Lower court adjusted.", "Dissent adjusted.", ""]:
        raw, result = fixture("1999s408", quote=quote)
        assert not check_result("1999s408", raw, result)["majority_grounding"]


def test_supporting_or_unclear_label_does_not_pass_negative_control():
    for relation in ["supports", "unclear"]:
        raw, result = fixture("2010s467", relation=relation)
        assert not check_result("2010s467", raw, result)["relation"]


async def test_extraction_failure_is_recorded_and_does_not_skip_remaining_case(
    tmp_path, monkeypatch
):
    import json

    from app.llm.legal_research import LegalDomainExtractionError
    from scripts import evaluate_legal_case_grounding as evaluation

    class Client:
        async def get_document(self, uri, **kwargs):
            return NS(text="public text", title=uri, truncated=False)

        async def aclose(self):
            pass

    class Interpreter:
        async def interpret(self, **kwargs):
            raise LegalDomainExtractionError(
                "outside majority", category="citation_grounding_failed"
            )

    monkeypatch.setattr(evaluation, "OfficialLagenNuMcpClient", Client)
    monkeypatch.setattr(evaluation, "LlmLegalInterpreter", Interpreter)
    output = tmp_path / "evaluation.json"
    assert not await evaluation.evaluate(1, "dd", output)
    payload = json.loads(output.read_text())
    assert payload["passed"] is False
    assert len(payload["cases"]) == 2
    assert all(row["category"] == "citation_grounding_failed" for row in payload["cases"])
    assert all(row["passed"] is False for row in payload["cases"])


def test_statutory_good_faith_is_not_contract_interpretation():
    raw, result = fixture("2010s467")
    result.case_law.authoritative_holding.decision_basis = "contract_interpretation"
    assert not check_result("2010s467", raw, result)["decision_basis"]
