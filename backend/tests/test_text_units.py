"""Canonical Document → Section → TextUnit: IDs, structure, provenance, Q&A."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import CanonicalDocumentRecord, Kund, TextUnitRecord
from app.services.document_knowledge import (
    GeneratedDocumentKnowledge,
    _accepted_generated_items,
    supporting_text_unit_ids,
)
from app.services.knowledge.chunking import KnowledgeChunker, make_chunk_id
from app.services.knowledge.extractors import ExtractedBlock, ExtractedDocument
from app.services.knowledge.models import KnowledgeDocument, KnowledgeScope
from app.services.knowledge.persistence import current_text_units, persist_segmented_document
from app.services.knowledge.segmentation import DocumentSegmenter, expand_text_unit_context
from app.services.knowledge.units import TextUnit, hash_text, make_text_unit_id

KNOWLEDGE_CORE = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "knowledge"
)
_FORBIDDEN_DOMAIN_TERMS = (
    "lagen.nu",
    "nja ",
    "hovrätt",
    "tingsrätt",
    "domskäl",
    "förarbete",
    "proposition",
    "preparatory",
    "case_law",
    "avtalslagen",
)


def _document(*, document_id: str = "doc-a", version: str = "1") -> KnowledgeDocument:
    return KnowledgeDocument(
        document_id=document_id,
        provider="supabase",
        external_id="acme/a.txt",
        title="Agreement",
        mime_type="text/plain",
        scope=KnowledgeScope(customer_id=1, case_id="c1", module="dd"),
        version=version,
    )


def _extracted(*blocks: ExtractedBlock) -> ExtractedDocument:
    return ExtractedDocument(blocks=list(blocks))


def _unit(*, unit_id: str, text: str, locator: str, section_id: str = "sec-1") -> TextUnit:
    return TextUnit(
        id=unit_id,
        document_id="doc-a",
        section_id=section_id,
        ordinal=0,
        text=text,
        content_hash=hash_text(text),
        locator=locator,
        page_start=1,
    )


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        yield db
    await engine.dispose()


def test_text_unit_id_is_stable_for_same_passage():
    digest = hash_text("same passage")
    first = make_text_unit_id(
        document_id="doc-a",
        version="3",
        locator="page:1",
        content_hash=digest,
    )
    second = make_text_unit_id(
        document_id="doc-a",
        version="3",
        locator="page:1",
        content_hash=digest,
    )
    assert first == second
    assert first == make_chunk_id(
        document_id="doc-a",
        version="3",
        locator="page:1",
        content_hash=digest,
    )


def test_changed_passage_changes_text_unit_id():
    first = make_text_unit_id(
        document_id="doc-a",
        version="1",
        locator="page:1",
        content_hash=hash_text("alpha"),
    )
    second = make_text_unit_id(
        document_id="doc-a",
        version="1",
        locator="page:1",
        content_hash=hash_text("beta"),
    )
    assert first != second


def test_markdown_headings_create_nested_sections():
    extracted = _extracted(
        ExtractedBlock(text="# Parties", locator="line:1", metadata={"heading_level": 1}),
        ExtractedBlock(text="Acme AB and Beta AB.", locator="line:3"),
        ExtractedBlock(text="## Price", locator="line:5", metadata={"heading_level": 2}),
        ExtractedBlock(text="The price is 100 SEK.", locator="line:7"),
    )
    segmented = DocumentSegmenter().segment(extracted, _document())
    assert [section.title for section in segmented.sections] == ["Parties", "Price"]
    assert segmented.sections[0].parent_section_id is None
    assert segmented.sections[1].parent_section_id == segmented.sections[0].id
    parties = [unit for unit in segmented.text_units if unit.section_id == segmented.sections[0].id]
    price = [unit for unit in segmented.text_units if unit.section_id == segmented.sections[1].id]
    assert any("Acme AB" in unit.text for unit in parties)
    assert any("100 SEK" in unit.text for unit in price)
    assert all(unit.document_id == "doc-a" for unit in segmented.text_units)
    assert all(unit.locator for unit in segmented.text_units)


def test_size_split_stays_inside_section():
    long_body = "The obligation is detailed. " * 80
    extracted = _extracted(
        ExtractedBlock(text="# Scope", locator="line:1", metadata={"heading_level": 1}),
        ExtractedBlock(text=long_body, locator="line:3"),
        ExtractedBlock(text="# Other", locator="line:5", metadata={"heading_level": 1}),
        ExtractedBlock(text="Short other clause.", locator="line:7"),
    )
    segmented = DocumentSegmenter(target_chars=120, max_chars=240).segment(
        extracted,
        _document(),
    )
    scope = next(section for section in segmented.sections if section.title == "Scope")
    other = next(section for section in segmented.sections if section.title == "Other")
    scope_units = [unit for unit in segmented.text_units if unit.section_id == scope.id]
    other_units = [unit for unit in segmented.text_units if unit.section_id == other.id]
    assert len(scope_units) >= 2
    assert all("Short other clause" not in unit.text for unit in scope_units)
    assert len(other_units) == 1
    assert "Short other clause" in other_units[0].text


def test_fallback_uses_block_then_paragraph_then_sentence_split():
    sentences = " ".join(f"Sentence {index} describes the term." for index in range(1, 12))
    extracted = _extracted(
        ExtractedBlock(text="First block.", locator="page:1", metadata={"page": 1}),
        ExtractedBlock(text=sentences, locator="page:2", metadata={"page": 2}),
    )
    segmented = DocumentSegmenter(target_chars=80, max_chars=160).segment(
        extracted,
        _document(),
    )
    assert [section.type for section in segmented.sections] == ["block", "block"]
    first = [unit for unit in segmented.text_units if unit.locator == "page:1"]
    second = [unit for unit in segmented.text_units if unit.locator == "page:2"]
    assert [unit.text for unit in first] == ["First block."]
    assert len(second) >= 2
    assert all(unit.page_start == 2 for unit in second)
    assert all(unit.char_start is not None and unit.char_end is not None for unit in segmented.text_units)


def test_chunk_projection_keeps_text_unit_provenance():
    extracted = _extracted(
        ExtractedBlock(text="Page one parties.", locator="page:1", metadata={"page": 1})
    )
    chunker = KnowledgeChunker(target_chars=80, overlap_chars=0)
    chunks = chunker.chunk(extracted, _document())
    units = chunker.segment(extracted, _document()).text_units
    assert len(chunks) == 1
    assert chunks[0].chunk_id == units[0].id
    assert chunks[0].locator == "page:1"
    assert chunks[0].metadata["text_unit_id"] == units[0].id
    assert chunks[0].metadata["section_id"] == units[0].section_id
    assert chunks[0].metadata["page_start"] == 1


def test_qa_can_ground_to_multiple_text_units():
    units = [
        _unit(unit_id="u1", text="The price is 100 SEK per month.", locator="page:1"),
        _unit(unit_id="u2", text="The price is 100 SEK after year one.", locator="page:2"),
        _unit(unit_id="u3", text="Termination is thirty days.", locator="page:3"),
    ]
    assert supporting_text_unit_ids(
        locator="page:1",
        exact_quote="The price is 100 SEK",
        units=units,
    ) == ["u1"]
    assert supporting_text_unit_ids(
        locator=None,
        exact_quote="The price is 100 SEK",
        units=units,
    ) == ["u1", "u2"]
    accepted = _accepted_generated_items(
        [
            GeneratedDocumentKnowledge(
                kind="qa",
                title="Price",
                question="What is the price?",
                content="100 SEK.",
                locator="page:1",
                exact_quote="The price is 100 SEK per month.",
            )
        ],
        units=units,
        pdf_bytes=None,
    )
    assert [item.text_unit_ids for item in accepted] == [["u1"]]


def test_context_expansion_stays_in_section():
    units = [
        TextUnit(
            id=f"u{index}",
            document_id="doc-a",
            section_id="a" if index < 3 else "b",
            ordinal=index if index < 3 else index - 3,
            text=f"unit {index}",
            content_hash=hash_text(f"unit {index}"),
        )
        for index in range(5)
    ]
    expanded = expand_text_unit_context(units[1], units, adjacent=1)
    assert [unit.id for unit in expanded] == ["u0", "u1", "u2"]
    assert all(unit.section_id == "a" for unit in expanded)


async def test_persist_keeps_stable_ids_and_supersedes_removed_units(session: AsyncSession):
    kund = Kund(name="acme", slug="acme", available_modules=["dd"])
    session.add(kund)
    await session.flush()
    extracted = _extracted(
        ExtractedBlock(text="First passage about parties.", locator="page:1", metadata={"page": 1}),
        ExtractedBlock(text="Second passage about price.", locator="page:2", metadata={"page": 2}),
    )
    first = DocumentSegmenter().segment(extracted, _document())
    await persist_segmented_document(
        session,
        customer_id=kund.id,
        source_object_id=None,
        segmented=first,
    )
    await session.flush()
    stored = await current_text_units(session, "doc-a")
    assert {row.id for row in stored} == {unit.id for unit in first.text_units}

    changed = DocumentSegmenter().segment(
        _extracted(ExtractedBlock(text="Only price remains.", locator="page:2", metadata={"page": 2})),
        _document(),
    )
    await persist_segmented_document(
        session,
        customer_id=kund.id,
        source_object_id=None,
        segmented=changed,
    )
    await session.flush()
    current = await current_text_units(session, "doc-a")
    assert {row.id for row in current} == {unit.id for unit in changed.text_units}
    removed = (
        await session.get(TextUnitRecord, next(unit.id for unit in first.text_units if "parties" in unit.text))
    )
    assert removed is not None
    assert removed.superseded_at is not None
    document = await session.get(CanonicalDocumentRecord, "doc-a")
    assert document is not None
    assert document.source_type == "uploaded_file"


def test_core_knowledge_modules_have_no_legal_domain_logic():
    for path in sorted(KNOWLEDGE_CORE.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        lowered = source.casefold()
        for term in _FORBIDDEN_DOMAIN_TERMS:
            assert term not in lowered, f"{path} contains domain term {term!r}"
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            if module:
                assert not module.startswith("app.services.lagen_nu")
                assert not module.startswith("app.llm.legal_research")
                assert module != "app.services.legal_research_result"
