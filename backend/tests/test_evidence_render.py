"""Deterministic frozen EvidenceSet → [E#] prompt evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services.execution.evidence_render import render_frozen_evidence


def _item(
    *,
    item_id: str,
    ordinal: int,
    status: str = "found",
    title: str | None = "Kommunens skattesats",
    excerpt: str | None = "skattesats 32%",
    locator: str | None = "p. 14",
    source_type: str = "customer_knowledge",
    provider: str | None = "supabase",
    source_url: str | None = "https://example.test/brief.pdf",
    original_evidence_id: str | None = "ev-1",
    provenance: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=item_id,
        ordinal=ordinal,
        status=status,
        title=title,
        excerpt=excerpt,
        locator=locator,
        source_type=source_type,
        provider=provider,
        source_url=source_url,
        source_id="doc-brief",
        original_evidence_id=original_evidence_id,
        provenance=provenance or {"secret": "do-not-leak", "content_hash": "abc"},
        retrieved_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
    )


def test_found_items_get_stable_e_refs_in_ordinal_order():
    later = _item(item_id="b", ordinal=4, title="Jämförelse", excerpt="jämförelse 2024")
    earlier = _item(item_id="a", ordinal=1, title="Kommunens skattesats")
    rendered = render_frozen_evidence([later, earlier])
    assert list(rendered.refs) == ["E1", "E2"]
    assert rendered.refs["E1"].item_id == "a"
    assert rendered.refs["E1"].ordinal == 1
    assert rendered.refs["E2"].item_id == "b"
    assert rendered.found_count == 2
    assert "[E1] Kommunens skattesats" in rendered.prompt_body
    assert "[E2] Jämförelse" in rendered.prompt_body
    assert rendered.prompt_body.index("[E1]") < rendered.prompt_body.index("[E2]")


def test_not_found_and_error_are_gaps_not_positive_evidence():
    found = _item(item_id="a", ordinal=0, original_evidence_id="orig-a")
    missing = _item(
        item_id="b",
        ordinal=1,
        status="not_found",
        title="Ingen kundpolicy",
        excerpt=None,
        source_type="customer_knowledge",
        original_evidence_id="orig-b",
    )
    errored = _item(
        item_id="c",
        ordinal=2,
        status="error",
        title="swedish_law timeout",
        excerpt=None,
        source_type="swedish_law",
        original_evidence_id="orig-c",
    )
    rendered = render_frozen_evidence([found, missing, errored])
    assert list(rendered.refs) == ["E1"]
    assert rendered.refs["E1"].original_evidence_id == "orig-a"
    assert rendered.found_count == 1
    assert rendered.gap_count == 2
    assert "[E2]" not in rendered.prompt_body
    assert "Known gaps (not evidence):" in rendered.prompt_body
    assert "not_found · customer_knowledge · Ingen kundpolicy" in rendered.prompt_body
    assert "error · swedish_law · swedish_law timeout" in rendered.prompt_body


def test_empty_found_set_states_no_positive_evidence():
    missing = _item(item_id="b", ordinal=0, status="not_found", title="Saknas")
    rendered = render_frozen_evidence([missing])
    assert rendered.refs == {}
    assert rendered.found_count == 0
    assert "No positive evidence was found." in rendered.prompt_body
    assert "Known gaps (not evidence):" in rendered.prompt_body


def test_renderer_omits_provenance_and_useless_urls():
    item = _item(
        item_id="a",
        ordinal=0,
        source_url="internal://not-useful",
        provenance={"document_id": "secret-doc", "raw": {"token": "xyz"}},
    )
    rendered = render_frozen_evidence([item])
    assert "secret-doc" not in rendered.prompt_body
    assert "token" not in rendered.prompt_body
    assert "internal://not-useful" not in rendered.prompt_body
    assert "Source type: customer_knowledge" in rendered.prompt_body
    assert "Provider: supabase" in rendered.prompt_body
    assert "Locator: p. 14" in rendered.prompt_body
    assert 'Excerpt: "skattesats 32%"' in rendered.prompt_body
