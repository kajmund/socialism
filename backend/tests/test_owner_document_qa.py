"""Owner-backed tenant Q&A: atomic publish, immediate reads, isolation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from app.services.document_qa.access import Viewer
from app.services.document_qa.labels import ANSWER, CANONICAL_DOCUMENT, QUESTION, TEXT_UNIT
from app.services.document_qa.normalize import normalize_question, question_key, reuse_digest
from app.services.document_qa.owner_qa import (
    load_answer,
    load_question,
    persist,
)
from app.services.document_qa.owner_qa_lifecycle import (
    archive_document,
    document_exists,
    document_is_archived,
    purge_document,
    review_answer,
    review_history,
)
from app.services.document_qa.owner_qa_retrieve import exact_reuse, semantic_candidates
from app.services.document_qa.types import (
    AnalysisContract,
    AnswerPostWrite,
    QaWrite,
    SourceCite,
)
from app.services.overgraph.owner import OvergraphOwner, OwnerClient

DIMENSION = 4
EMBEDDING = (1.0, 0.0, 0.0, 0.0)
CONTRACT = AnalysisContract(
    kind="document_chat",
    method="evidence_answer",
    model="test-model",
    model_version="v1",
)


def _viewer(customer_id: int = 1) -> Viewer:
    return Viewer(
        customer_id=customer_id,
        workspace_id="ws-1",
        readable_document_ids=frozenset({"doc-1"}),
        readable_version_ids=frozenset({"ver-1"}),
    )


def _write(*, text: str = "Svar om uppsägning.", created: str = "2026-10-11T10:00:00Z") -> QaWrite:
    return QaWrite(
        question_text="Vad gäller uppsägning?",
        document_id="doc-1",
        document_version_id="ver-1",
        workspace_id="ws-1",
        contract=CONTRACT,
        status="ANSWERED",
        answer_text=text,
        posts=(
            AnswerPostWrite(
                text=text,
                sources=(
                    SourceCite(
                        text_unit_id="tu-1",
                        excerpt="citat A",
                        start=0,
                        end=7,
                        position_validated=True,
                    ),
                    SourceCite(text_unit_id="tu-2", excerpt="citat B"),
                ),
            ),
        ),
        asked_at=created,
        created_at=created,
        embedding=EMBEDDING,
    )


def _unit(key: str, version: str, text: str) -> dict:
    return {
        "labels": [TEXT_UNIT],
        "key": key,
        "props": {
            "unit_id": key,
            "document_id": "doc-1",
            "document_version_id": version,
            "text": text,
        },
    }


async def _start(root: Path, name: str) -> tuple[OvergraphOwner, OwnerClient, OwnerClient]:
    owner = OvergraphOwner(
        root / name,
        dimension=DIMENSION,
        socket_path=root / f"{name}.sock",
    )
    await owner.start()
    first = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    second = OwnerClient(owner.socket_path, catalog_id=owner.catalog_id)
    return owner, first, second


async def test_persist_is_atomic_and_visible_to_a_second_client():
    root = Path(tempfile.mkdtemp(prefix="owner-qa-"))
    owner, first, second = await _start(root, "tenant-1")
    try:
        await first.mutate(
            "seed",
            {
                "upsert_nodes": [
                    _unit("tu-1", "ver-1", "avtalstext"),
                    _unit("tu-2", "ver-1", "bilaga"),
                ]
            },
            kind="batch",
        )
        loaded = await persist(first, _viewer(), _write())
        assert loaded.answers[0].posts[0].sources[0].excerpt == "citat A"
        assert loaded.answers[0].posts[0].sources[1].text_unit_id == "tu-2"
        seen = await load_question(second, loaded.key)
        assert seen is not None and seen.answers[0].text == "Svar om uppsägning."
        # The cited units keep their ingested text; the excerpt lives on the cite.
        assert owner.catalog.get_by_key(TEXT_UNIT, "tu-1").props["text"] == "avtalstext"
        # Republishing the same logical answer does not duplicate it.
        again = await persist(first, _viewer(), _write())
        assert len(again.answers) == 1
        assert len(await review_history(second, again.key)) == 0
        assert owner.catalog.count_nodes_by_labels([QUESTION]) == 1
    finally:
        await owner.close()


async def test_persist_rejects_foreign_version_before_any_write():
    root = Path(tempfile.mkdtemp(prefix="owner-qa-"))
    owner, first, _second = await _start(root, "tenant-1")
    try:
        await first.mutate(
            "seed",
            {
                "upsert_nodes": [
                    _unit("tu-1", "ver-other", "annan version"),
                    _unit("tu-2", "ver-other", "x"),
                ]
            },
            kind="batch",
        )
        write = _write()
        try:
            await persist(first, _viewer(), write)
        except ValueError as exc:
            assert "another document version" in str(exc)
        else:
            raise AssertionError("foreign TextUnit version must be rejected")
        assert (
            owner.catalog.get_by_key(
                QUESTION,
                question_key(
                    _viewer().customer_id,
                    reuse_digest(normalize_question(write.question_text), "ver-1", CONTRACT),
                ),
            )
            is None
        )
        assert owner.catalog.count_nodes_by_labels([QUESTION]) == 0
    finally:
        await owner.close()


async def test_exact_and_semantic_reuse_read_through_the_owner():
    root = Path(tempfile.mkdtemp(prefix="owner-qa-"))
    owner, first, second = await _start(root, "tenant-1")
    try:
        loaded = await persist(first, _viewer(), _write())
        viewer = _viewer()
        hit = await exact_reuse(
            second,
            viewer,
            question_text="Vad gäller uppsägning?",
            document_id="doc-1",
            document_version_id="ver-1",
            contract=CONTRACT,
        )
        assert hit is not None and hit.answer.key == loaded.answers[0].key
        candidates = await semantic_candidates(
            second,
            viewer,
            embedding=EMBEDDING,
            document_id="doc-1",
            document_version_id="ver-1",
        )
        assert [candidate.question.key for candidate in candidates] == [loaded.key]
        assert candidates[0].current_version is True
        # Another document never sees this answer.
        assert (
            await exact_reuse(
                second,
                viewer,
                question_text="Vad gäller uppsägning?",
                document_id="doc-2",
                document_version_id="ver-1",
                contract=CONTRACT,
            )
            is None
        )
    finally:
        await owner.close()


async def test_review_archive_and_purge_are_owner_writes():
    root = Path(tempfile.mkdtemp(prefix="owner-qa-"))
    owner, first, second = await _start(root, "tenant-1")
    try:
        loaded = await persist(first, _viewer(), _write())
        answer_key = loaded.answers[0].key
        reviewed = await review_answer(
            first,
            _viewer(),
            answer_key,
            action="approve",
            reviewed_at="2026-10-12T10:00:00Z",
            reviewer="user-1",
        )
        assert reviewed.review_status == "user_verified"
        assert (await load_answer(second, answer_key)).review_status == "user_verified"
        assert await review_history(second, answer_key) == (
            {
                "action": "approve",
                "reviewed_at": "2026-10-12T10:00:00Z",
                "reviewer": "user-1",
            },
        )
        await archive_document(first, _viewer(), "doc-1")
        assert await document_is_archived(second, "doc-1") is True
        assert (await load_question(second, loaded.key)).archived is True
        assert (
            await exact_reuse(
                second,
                _viewer(),
                question_text="Vad gäller uppsägning?",
                document_id="doc-1",
                document_version_id="ver-1",
                contract=CONTRACT,
            )
            is None
        )
        await purge_document(first, _viewer(), "doc-1")
        assert await document_exists(second, "doc-1") is False
        assert await load_question(second, loaded.key) is None
        assert await load_answer(second, answer_key) is None
        assert owner.catalog.count_nodes_by_labels([ANSWER]) == 0
        assert owner.catalog.count_nodes_by_labels([CANONICAL_DOCUMENT]) == 0
    finally:
        await owner.close()


async def test_two_tenant_owners_keep_the_same_ids_isolated():
    root = Path(tempfile.mkdtemp(prefix="owner-qa-"))
    owner_a, first_a, read_a = await _start(root, "tenant-1")
    owner_b, first_b, read_b = await _start(root, "tenant-2")
    try:
        loaded_a = await persist(first_a, _viewer(1), _write())
        loaded_b = await persist(first_b, _viewer(2), _write())
        assert loaded_a.key != loaded_b.key
        assert len((await load_question(read_a, loaded_a.key)).answers) == 1
        assert len((await load_question(read_b, loaded_b.key)).answers) == 1
        assert owner_a.catalog.count_nodes_by_labels([QUESTION]) == 1
        assert owner_b.catalog.count_nodes_by_labels([QUESTION]) == 1
    finally:
        await owner_a.close()
        await owner_b.close()


def _text_unit(unit_id: str, document_id: str, version_id: str, *, next_id: str | None = None):
    from app.services.knowledge.scope import customer_scope
    from app.services.overgraph.model import TextUnitWrite

    return TextUnitWrite(
        unit_id=unit_id,
        scope=customer_scope(1),
        document_id=document_id,
        document_version_id=version_id,
        text=f"text {unit_id}",
        content_hash=f"hash-{unit_id}",
        ordinal=0,
        next_id=next_id,
        embedding=EMBEDDING,
    )


async def test_document_units_are_published_atomically():
    from app.services.document_qa.owner_ingest import persist_document_units
    from app.services.overgraph.labels import CONTAINS

    root = Path(tempfile.mkdtemp(prefix="owner-qa-"))
    owner, first, second = await _start(root, "tenant-1")
    try:
        units = (
            _text_unit("unit-1", "doc-9", "ver-9", next_id="unit-2"),
            _text_unit("unit-2", "doc-9", "ver-9"),
        )
        await persist_document_units(first, document_id="doc-9", units=units)
        response = await second.read(
            [{"label": CANONICAL_DOCUMENT, "key": "doc-9"},
             {"label": "DocumentVersion", "key": "ver-9"},
             {"label": TEXT_UNIT, "key": "unit-1"}],
            include_vectors=True,
        )
        assert response["values"][f"{CANONICAL_DOCUMENT}:doc-9"]["archived"] == 0
        assert response["values"]["DocumentVersion:ver-9"]["document_id"] == "doc-9"
        assert response["vectors"][f"{TEXT_UNIT}:unit-1"] == list(EMBEDDING)
        version_id = response["ids"]["DocumentVersion:ver-9"]
        assert sorted(
            row["key"] for row in await second.neighbors(version_id, labels=[CONTAINS])
        ) == ["unit-1", "unit-2"]
        # Duplicate ingest is idempotent: no duplicated nodes.
        await persist_document_units(first, document_id="doc-9", units=units)
        assert owner.catalog.count_nodes_by_labels([TEXT_UNIT]) == 2
    finally:
        await owner.close()


async def test_document_index_writes_and_reclassifies_through_the_owner():
    from app.services.document_qa.owner_document_index import (
        classify_and_index,
        documents_for_type,
    )
    from app.services.document_qa.owner_ingest import persist_document_units

    root = Path(tempfile.mkdtemp(prefix="owner-qa-"))
    owner, first, second = await _start(root, "tenant-1")
    try:
        for document_id in ("doc-a", "doc-b"):
            await persist_document_units(first, document_id=document_id, units=(
                _text_unit(f"{document_id}-unit", document_id, f"{document_id}-ver"),
            ))
        await classify_and_index(first, document_id="doc-a", document_type="nda")
        await classify_and_index(first, document_id="doc-b", document_type="dpa")
        assert await documents_for_type(second, "nda") == ["doc-a"]
        assert await documents_for_type(second, "dpa") == ["doc-b"]
        # Reclassification removes the document from the old category.
        await classify_and_index(first, document_id="doc-a", document_type="dpa")
        assert await documents_for_type(second, "nda") == []
        assert await documents_for_type(second, "dpa") == ["doc-a", "doc-b"]
        # Archived documents are not returned by the index.
        await archive_document(
            first,
            Viewer(
                customer_id=1, workspace_id="ws-1",
                readable_document_ids=frozenset({"doc-b"}),
                readable_version_ids=frozenset({"doc-b-ver"}),
            ),
            "doc-b",
        )
        assert await documents_for_type(second, "dpa") == ["doc-a"]
    finally:
        await owner.close()
