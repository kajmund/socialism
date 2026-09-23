from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.llm.lagen_nu_passage_queries import LlmPassageQueryPlanner, PassageQueries
from app.services.lagen_nu.models import LagenNuPin, ResolvedCitations, SearchResults
from app.services.lagen_nu.research_source import MAX_MCP_TOOL_CALLS, LagenNuResearchSource
from app.services.prompt_catalog import default_prompts
from tests.test_lagen_nu_provider import (
    FakeLagenNuClient,
    FakeLegalInterpreter,
    PassthroughLagenNuSelector,
    _document,
    _hit,
)
from tests.test_research import _context, _need

URI = "https://lagen.nu/prop/1975/76:81"


class Planner:
    async def plan_queries(self, **kwargs):
        return ["svagare", "jämkning"]


def setup_source(*, fragments=True, bad_response=False):
    root = replace(_hit(uri=URI, source="forarbete", pinpoint=None), identifier="Prop. 1975/76:81")
    pin = LagenNuPin(
        uri=URI + "#a10-2", pinpoint="a10-2", label="Specialmotivering", highlight=("Svagare part",)
    )
    wrong = replace(pin, uri="https://lagen.nu/prop/2000/01:1#a10-2")
    hits = (replace(root, fragments=(pin, wrong)),) if fragments else (root,)
    document = _document(
        uri=URI, source="forarbete", pinpoint=None, text="Endast dokumentets inledning."
    )
    passage = _document(
        uri=URI,
        source="forarbete",
        pinpoint="a10-2",
        text="Hänsyn skall tas till den svagare partens behov av skydd.",
    )
    if bad_response:
        passage = replace(passage, uri="https://lagen.nu/prop/2000/01:1")
    client = FakeLagenNuClient(
        resolved=ResolvedCitations(results=(root,)),
        search=SearchResults(query="svagare", total=len(hits), results=hits),
        documents={URI: replace(document, truncated=True), URI + "#a10-2": passage},
    )
    source = LagenNuResearchSource(
        source_type="swedish_preparatory_works",
        client=client,
        selector=PassthroughLagenNuSelector(),
        interpreter=FakeLegalInterpreter(),
        passage_query_planner=Planner(),
    )
    return source, client


async def research(source):
    return await source.research(
        _need(
            "swedish_preparatory_works",
            question="Vad säger prop. 1975/76:81 om svagare parts skydd?",
        ),
        _context(),
    )


async def test_truncated_proposition_fetches_grounded_section_in_same_document():
    source, client = setup_source()
    evidence = await research(source)
    assert len(evidence) == 1
    assert evidence[0].status == "found"
    assert evidence[0].source_id == URI + "#a10-2"
    fetches = [args for name, args in client.calls if name == "get_document"]
    assert [args["pinpoint"] for args in fetches] == [None, "a10-2"]
    assert all(args["uri"] == URI for args in fetches)
    assert len(client.calls) <= MAX_MCP_TOOL_CALLS


async def test_no_passage_does_not_interpret_truncated_prefix():
    source, _ = setup_source(fragments=False)
    evidence = await research(source)
    assert evidence[0].metadata["failure_category"] == "passage_not_found"
    assert evidence[0].status != "found"


async def test_passage_response_cannot_change_source_document():
    source, _ = setup_source(bad_response=True)
    evidence = await research(source)
    assert evidence[0].status != "found"
    assert evidence[0].metadata["failure_category"] == "fetch_failed"


@pytest.mark.parametrize("queries", [[], ["x"] * 4, [" "], ["x" * 121]])
def test_query_plan_rejects_unbounded_or_empty_searches(queries):
    with pytest.raises(ValidationError):
        PassageQueries(queries=queries)


async def test_query_planner_uses_configured_prompt_and_compact_document_metadata():
    async def complete(messages, response_model):
        assert (
            messages[0]["content"]
            == default_prompts("sv")["research.lagen_nu.passage_queries.system"]
        )
        assert URI in messages[1]["content"]
        assert "SECRET_RAW_TEXT" not in str(messages)
        return {"queries": [" svagare ", "svagare", "jämkning"]}

    planner = LlmPassageQueryPlanner(completer=complete, prompts=default_prompts("sv"))
    result = await planner.plan_queries(
        need=_need("swedish_preparatory_works"),
        context=_context(),
        document=_document(uri=URI, text="SECRET_RAW_TEXT"),
    )
    assert result == ["svagare", "jämkning"]


async def test_passage_fetches_share_document_budget_and_skip_snippet_selector():
    source, client = setup_source()
    root = client.search_payload.results[0]
    pins = tuple(
        LagenNuPin(
            uri=URI + f"#a{i}", pinpoint=f"a{i}", label="Avsnitt", highlight=("Dokumentnummer",)
        )
        for i in range(10)
    )
    client.search_payload = replace(client.search_payload, results=(replace(root, fragments=pins),))
    for pin in pins:
        client.documents[pin.uri] = _document(uri=URI, source="forarbete", pinpoint=pin.pinpoint)

    class RejectSnippetSelection(PassthroughLagenNuSelector):
        async def select_hits(self, **kwargs):
            raise AssertionError("Source-verified passages must be judged from actual text")

    source._selector = RejectSnippetSelection()
    evidence = await research(source)
    fetches = [args for name, args in client.calls if name == "get_document"]
    assert len(fetches) == 5
    assert len(evidence) == 4
    assert len(client.calls) <= MAX_MCP_TOOL_CALLS
    assert all(
        args["query"].startswith('"1975/76:81" ') for name, args in client.calls if name == "search"
    )
