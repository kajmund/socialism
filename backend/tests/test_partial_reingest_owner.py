from __future__ import annotations

from sqlalchemy import select

from app.database.models import DocumentVersionRecord
from app.services.knowledge.persistence import persist_segmented_document
from app.services.knowledge.units import (
    CanonicalDocument,
    DocumentSection,
    DocumentVersion,
    SegmentedDocument,
    TextUnit,
    hash_text,
)
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.text_units import load_domain_text_units


def _units(version_id: str, *, changed_index: int = 50, change: bool = False):
    units = []
    char = 0
    for index in range(100):
        text = f"Klausul {index}: standardtext."
        if change and index == changed_index:
            text = f"Klausul {index}: ändrad text med ny längd."
        locator = f"stycke {index + 1}"
        units.append(TextUnit(
            id=f"{version_id}:u{index}",
            document_version_id=version_id,
            document_id="doc-partial",
            section_id=f"sec-{version_id}",
            ordinal=index,
            text=text,
            content_hash=hash_text(text),
            locator=locator,
            page_start=index // 10 + 1,
            page_end=index // 10 + 1,
            char_start=char,
            char_end=char + len(text),
        ))
        char += len(text) + 1
    return tuple(units)


def _segmented(version_id: str, *, changed_index: int = 50, change: bool = False) -> SegmentedDocument:
    units = _units(version_id, changed_index=changed_index, change=change)
    return SegmentedDocument(
        document=CanonicalDocument(
            id="doc-partial", source_type="test", canonical_uri="test://partial",
            title="Partial reingest",
        ),
        version=DocumentVersion(
            id=version_id, document_id="doc-partial",
            content_hash=hash_text(str(change)), mime_type="text/plain",
        ),
        sections=(
            DocumentSection(
                id=f"sec-{version_id}", document_version_id=version_id, document_id="doc-partial",
                parent_section_id=None, ordinal=0, type="body", title="Avtal",
            ),
        ),
        text_units=units,
    )


async def test_partial_reingest_keeps_versions_separate_and_positions_correct(client_db):
    _client, factory = client_db
    async with factory() as session:
        await persist_segmented_document(session, segmented=_segmented("ver-1"), customer_id=1)
        await session.commit()
    old_units = load_domain_text_units(require_knowledge(), document_version_id="ver-1")
    assert len(old_units) == 100

    async with factory() as session:
        await persist_segmented_document(
            session, segmented=_segmented("ver-2", change=True), customer_id=1,
        )
        await session.commit()
        versions = list((await session.execute(
            select(DocumentVersionRecord).where(DocumentVersionRecord.document_id == "doc-partial")
        )).scalars())
        assert len(versions) == 2
        current = next(version for version in versions if version.superseded_at is None)
        assert current.id == "ver-2"

    new_units = load_domain_text_units(require_knowledge(), document_version_id="ver-2")
    assert len(new_units) == 100
    assert all(unit.document_version_id == "ver-2" for unit in new_units)
    assert new_units[50].text.startswith("Klausul 50: ändrad")
    assert new_units[50].page_start == 6
    # The changed clause shifts later character positions; they must be updated.
    assert new_units[51].char_start > old_units[51].char_start
    assert new_units[51].locator == "stycke 52"
    # Old version remains historical, not current.
    assert load_domain_text_units(require_knowledge(), document_version_id="ver-1")
    assert all(unit.document_version_id == "ver-1" for unit in old_units)

    # Structure is scoped to the new version.
    assert require_knowledge().count_edges_by_label("CONTAINS") >= 200
