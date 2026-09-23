"""Named exclusions must not terminate discovery or re-enter through search."""

from dataclasses import replace

import pytest

from app.llm.lagen_nu_citation_intent import (
    CaseCitationIntent,
    CaseCitationPlan,
    LlmCaseCitationPlanner,
)
from app.services.lagen_nu.models import ResolvedCitations, SearchResults
from app.services.lagen_nu.research_source import LagenNuResearchSource, _CallBudget
from app.services.lagen_nu.selection import LagenNuSelectionError
from app.services.prompt_catalog import default_prompts
from tests.test_lagen_nu_provider import FakeLagenNuClient, _hit
from tests.test_research import _context, _need

A = "NJA 1983 s. 332"
B = "NJA 1989 s. 346"
QUESTION = f"Vilka andra HD-avgöranden tillämpar 36 § avtalslagen, utöver {A} och {B}?"
QUERY = "HD 36 § avtalslagen oskälighet"


def plan(*roles, query=QUERY):
    return CaseCitationPlan(
        citations=[
            CaseCitationIntent(citation=c, role=r) for c, r in zip((A, B), roles, strict=False)
        ],
        search_query=query,
    )


class Planner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def plan(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def hit(uri, citation):
    return replace(_hit(uri=uri, title=citation, source="dv", pinpoint=None), identifier=citation)


async def test_exclusions_are_resolved_and_removed_even_as_search_fragments():
    a = hit("https://lagen.nu/dom/nja/1983s332", A)
    b = hit("https://lagen.nu/dom/nja/1989s346", B)
    other = hit("https://lagen.nu/dom/nja/2017s113", "NJA 2017 s. 113")
    client = FakeLagenNuClient(
        resolved_by_citation={
            A: ResolvedCitations(results=(a,)),
            B: ResolvedCitations(results=(b,)),
        },
        search=SearchResults(
            query=QUERY, total=3, results=(replace(a, uri=a.uri + "#dom"), b, other)
        ),
    )
    planner = Planner(plan("exclude", "exclude"))
    source = LagenNuResearchSource(
        source_type="swedish_case_law", client=client, case_citation_planner=planner
    )
    results = await source._case_law_candidates(
        _need("swedish_case_law", question=QUESTION), _context(), _CallBudget(12), "dv"
    )
    assert [item.hit.uri for item in results] == [other.uri]
    assert client.calls[-1] == (
        "search",
        {"query": QUERY, "source": "dv", "kind": "case", "limit": 10},
    )
    assert planner.calls[0]["citations"] == [A, B]


async def test_target_and_exclusion_keep_target_and_search_for_more():
    a = hit("https://lagen.nu/dom/nja/1983s332", A)
    b = hit("https://lagen.nu/dom/nja/1989s346", B)
    client = FakeLagenNuClient(
        resolved_by_citation={
            A: ResolvedCitations(results=(a,)),
            B: ResolvedCitations(results=(b,)),
        }
    )
    source = LagenNuResearchSource(
        source_type="swedish_case_law",
        client=client,
        case_citation_planner=Planner(plan("target", "exclude")),
    )
    results = await source._case_law_candidates(
        _need("swedish_case_law", question=QUESTION), _context(), _CallBudget(12), "dv"
    )
    assert [item.hit.uri for item in results] == [a.uri]
    assert client.calls[-1][0] == "search"


async def test_background_examples_do_not_become_direct_lookup_targets():
    client = FakeLagenNuClient()
    source = LagenNuResearchSource(
        source_type="swedish_case_law",
        client=client,
        case_citation_planner=Planner(plan("context", "context")),
    )
    await source._case_law_candidates(
        _need("swedish_case_law", question=QUESTION), _context(), _CallBudget(12), "dv"
    )
    assert [name for name, _ in client.calls] == ["search"]


async def test_unresolved_exclusion_fails_before_search_or_document_fetch():
    client = FakeLagenNuClient()
    source = LagenNuResearchSource(
        source_type="swedish_case_law",
        client=client,
        case_citation_planner=Planner(plan("exclude", "exclude")),
    )
    with pytest.raises(LagenNuSelectionError, match="could not be resolved"):
        await source._case_law_candidates(
            _need("swedish_case_law", question=QUESTION), _context(), _CallBudget(12), "dv"
        )
    assert [name for name, _ in client.calls] == ["resolve_citation"]


@pytest.mark.parametrize(
    "result",
    [
        plan("target"),
        CaseCitationPlan(
            citations=[CaseCitationIntent(citation=A, role="target")] * 2, search_query=""
        ),
        plan("exclude", "exclude", query=""),
        plan("exclude", "exclude", query=f"36 § {A}"),
    ],
)
def test_invalid_or_incomplete_intent_is_rejected(result):
    with pytest.raises(ValueError):
        result.verify([A, B])


async def test_model_boundary_receives_question_and_validates_returned_citations():
    async def complete(messages, response_model, **kwargs):
        assert QUESTION in messages[1]["content"]
        assert A in messages[1]["content"]
        assert response_model is CaseCitationPlan
        return plan("exclude", "exclude").model_dump()

    planner = LlmCaseCitationPlanner(completer=complete, prompts=default_prompts("sv"))
    result = await planner.plan(
        need=_need("swedish_case_law", question=QUESTION), citations=[A, B], context=_context()
    )
    assert result.search_query == QUERY
    assert [item.role for item in result.citations] == ["exclude", "exclude"]


async def test_questions_without_named_cases_do_not_invoke_intent_model():
    class UnexpectedPlanner:
        async def plan(self, **kwargs):
            raise AssertionError("unnamed cases need no citation intent call")

    client = FakeLagenNuClient()
    source = LagenNuResearchSource(
        source_type="swedish_case_law", client=client, case_citation_planner=UnexpectedPlanner()
    )
    await source._case_law_candidates(
        _need("swedish_case_law", question="Vilka domstolsavgöranden gäller oskäliga avtal?"),
        _context(),
        _CallBudget(12),
        "dv",
    )
    assert [name for name, _ in client.calls] == ["search"]


async def test_model_cannot_invent_a_citation_and_failure_is_visible():
    async def complete(*args, **kwargs):
        return CaseCitationPlan(
            citations=[CaseCitationIntent(citation="NJA 2099 s. 1", role="target")],
            search_query="",
        )

    source = LagenNuResearchSource(
        source_type="swedish_case_law",
        client=FakeLagenNuClient(),
        case_citation_planner=LlmCaseCitationPlanner(
            completer=complete, prompts=default_prompts("sv")
        ),
    )
    results = await source.research(_need("swedish_case_law", question=QUESTION), _context())
    assert len(results) == 1
    assert results[0].metadata["failure_category"] == "selection_failed"
    assert results[0].metadata["mcp_calls"] == []
