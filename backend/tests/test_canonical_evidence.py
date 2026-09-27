"""Canonical passage dedup across knowledge reuse and provider retrieval."""

from __future__ import annotations

import logging

from app.services.research.canonical_evidence import (
    PATH_CLAIM,
    PATH_KNOWLEDGE_REUSE,
    PATH_PROVIDER_RETRIEVAL,
    canonical_passage_keys,
    dedupe_canonical_evidence,
)
from app.services.research.models import research_evidence
from app.services.research.question_reuse import (
    collapse_canonical_evidence,
    merge_reused_with_provider,
)


def _passage(
    *,
    need: str = "need-1",
    provider: str = "knowledge_claim",
    version: str = "ver-1",
    units: list[str] | None = None,
    claim_id: str | None = "claim-1",
    excerpt: str = "passage text",
    source_id: str = "doc-1",
    locator: str | None = None,
    source_type: str = "swedish_law",
):
    unit_ids = ["passage-1"] if units is None else units
    metadata: dict[str, object] = {"document_version_id": version}
    if provider == "knowledge_claim":
        metadata["supporting_text_unit_ids"] = unit_ids
        metadata["knowledge_claim_ids"] = [claim_id or "claim-1"]
        metadata["reuse"] = {
            "origin": "persistent_knowledge",
            "evidence_ref": claim_id or "claim-1",
        }
    else:
        metadata["text_unit_ids"] = unit_ids
    return research_evidence(
        research_need_id=need,
        source_type=source_type,
        status="found",
        title="Källa",
        excerpt=excerpt,
        locator=locator if locator is not None else ",".join(unit_ids),
        source_id=source_id,
        provider=provider,
        metadata=metadata,
    )


def _keys(items) -> set[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    for item in items:
        for key in canonical_passage_keys(item.metadata):
            assert key not in seen
            seen.add(key)
    return seen


def _paths(item) -> set[str]:
    return {entry["path"] for entry in item.metadata["discovered_via"]}


def test_reuse_and_retrieval_of_the_same_passage_collapse_to_one():
    reused = _passage(excerpt="återanvänd", claim_id="claim-a")
    live = _passage(
        provider="lagen_nu",
        excerpt="ny hämtning",
        source_id="https://lagen.nu/1915:218",
        locator="36 §",
        claim_id=None,
    )
    merged = merge_reused_with_provider([reused], [live])

    assert len(merged) == 1
    assert _keys(merged) == {("ver-1", "passage-1")}
    assert _paths(merged[0]) == {PATH_KNOWLEDGE_REUSE, PATH_CLAIM, PATH_PROVIDER_RETRIEVAL}
    assert merged[0].excerpt == "återanvänd"


def test_two_claims_for_the_same_passage_keep_both_claim_ids():
    first = _passage(claim_id="claim-a", excerpt="första formuleringen")
    second = _passage(claim_id="claim-b", excerpt="andra formuleringen")
    result = dedupe_canonical_evidence([first, second])

    assert result.knowledge_candidates == 2
    assert result.new_candidates == 0
    assert result.duplicates_removed == 1
    assert result.unique_evidence == 1
    assert result.unique_passages == 1
    claim_ids = {
        entry["claim_id"]
        for entry in result.evidence[0].metadata["discovered_via"]
        if entry["path"] == PATH_CLAIM
    }
    assert claim_ids == {"claim-a", "claim-b"}


def test_repeated_provider_hits_for_the_same_passage_collapse():
    first = _passage(provider="lagen_nu", excerpt="träff 1", source_id="https://lagen.nu/a")
    second = _passage(provider="lagen_nu", excerpt="träff 2", source_id="https://lagen.nu/a")
    result = dedupe_canonical_evidence([first, second])

    assert result.new_candidates == 2
    assert result.duplicates_removed == 1
    assert result.unique_evidence == 1
    assert _paths(result.evidence[0]) == {PATH_PROVIDER_RETRIEVAL}


def test_different_passages_from_the_same_source_stay():
    first = _passage(units=["passage-1"], excerpt="första stycket")
    second = _passage(units=["passage-2"], excerpt="andra stycket", claim_id="claim-2")
    result = dedupe_canonical_evidence([first, second])

    assert result.duplicates_removed == 0
    assert result.unique_evidence == 2
    assert _keys(result.evidence) == {("ver-1", "passage-1"), ("ver-1", "passage-2")}


def test_same_passage_id_on_another_document_version_stays():
    current = _passage(version="ver-1")
    revised = _passage(version="ver-2", excerpt="ny lydelse", claim_id="claim-2")
    result = dedupe_canonical_evidence([current, revised])

    assert result.unique_evidence == 2
    assert _keys(result.evidence) == {("ver-1", "passage-1"), ("ver-2", "passage-1")}


def test_different_sources_with_the_same_conclusion_stay():
    first = research_evidence(
        research_need_id="need-1",
        source_type="web",
        status="found",
        excerpt="samma slutsats",
        locator="p1",
        source_id="source-a",
        provider="web",
    )
    second = research_evidence(
        research_need_id="need-1",
        source_type="web",
        status="found",
        excerpt="samma slutsats",
        locator="p9",
        source_id="source-b",
        provider="web",
    )
    result = dedupe_canonical_evidence([first, second])

    assert result.duplicates_removed == 0
    assert [item.source_id for item in result.evidence] == ["source-a", "source-b"]
    assert "discovered_via" not in result.evidence[0].metadata


def test_partial_overlap_keeps_the_new_passage_once():
    reused = _passage(units=["passage-1"], claim_id="claim-a")
    live = _passage(
        provider="lagen_nu",
        units=["passage-1", "passage-2"],
        excerpt="bredare träff",
        source_id="https://lagen.nu/a",
        locator="1-2 §§",
    )
    result = dedupe_canonical_evidence([reused, live])

    assert result.duplicates_removed == 0
    assert result.unique_evidence == 2
    assert _keys(result.evidence) == {("ver-1", "passage-1"), ("ver-1", "passage-2")}
    kept = result.evidence[0]
    extra = result.evidence[1]
    assert _paths(kept) == {PATH_KNOWLEDGE_REUSE, PATH_CLAIM, PATH_PROVIDER_RETRIEVAL}
    assert canonical_passage_keys(extra.metadata) == (("ver-1", "passage-2"),)
    assert extra.locator == "1-2 §§"
    assert _paths(extra) == {PATH_PROVIDER_RETRIEVAL}


def test_not_found_is_not_a_candidate_and_is_kept():
    missing = research_evidence(
        research_need_id="need-1",
        source_type="swedish_law",
        status="not_found",
        provider="lagen_nu",
    )
    result = dedupe_canonical_evidence([missing, _passage()])

    assert result.evidence[0].status == "not_found"
    assert result.knowledge_candidates == 1
    assert result.new_candidates == 0
    assert result.unique_evidence == 1


def test_merge_logs_how_much_reuse_collapses(caplog):
    reused = [
        _passage(claim_id="claim-a", excerpt="första"),
        _passage(claim_id="claim-b", excerpt="andra"),
    ]
    live = [
        _passage(
            provider="lagen_nu",
            excerpt="ny",
            source_id="https://lagen.nu/a",
            locator="36 §",
        )
    ]
    with caplog.at_level(logging.INFO, logger="app.services.research.canonical_evidence"):
        merged = merge_reused_with_provider(reused, live)

    assert len(merged) == 1
    payload = caplog.records[-1].event_payload
    assert payload["research"] == {
        "scope": "need",
        "knowledge_candidates": 2,
        "new_candidates": 1,
        "duplicates_removed": 2,
        "unique_evidence": 1,
        "unique_passages": 1,
    }


def test_reused_only_collapse_logs_zero_new_candidates():
    collapsed = collapse_canonical_evidence(
        [
            _passage(claim_id="claim-a"),
            _passage(claim_id="claim-b", excerpt="kopia"),
        ]
    )

    assert len(collapsed) == 1
    assert _keys(collapsed) == {("ver-1", "passage-1")}
