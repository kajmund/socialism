"""Tenant OverGraph Q&A. Exact reuse is separate from persist; no semantic cache."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.services.document_qa import (
    AnalysisContract,
    AnswerPostWrite,
    QaOutbox,
    QaPermissionError,
    QaStoreError,
    QaWrite,
    SourceCite,
    TenantCatalogs,
    Viewer,
    archive_document,
    cache_decision,
    exact_reuse,
    persist,
    persist_after_answer,
    purge_document,
    review_answer,
    review_history,
    semantic_candidates,
)
from app.services.document_qa.labels import QUESTION
from app.services.document_qa.lifecycle import document_exists, document_is_archived
from app.services.document_qa.store import load_question
from app.services.knowledge.scope import customer_scope
from app.services.knowledge.units import hash_text, make_text_unit_id
from app.services.overgraph.catalogs import open_catalog
from app.services.overgraph.ingest import ingest_document_units
from app.services.overgraph.model import TextUnitWrite

DIM = 8
CONTRACT = AnalysisContract(
    kind="document_chat", method="existing_analysis", model="test", model_version="v1",
)
APP = Path(__file__).resolve().parents[1] / "app"


def _vector(*values: float) -> tuple[float, ...]:
    out = [0.0] * DIM
    for index, value in enumerate(values):
        out[index] = value
    return tuple(out)


def _viewer(customer_id: int = 1, *, docs: tuple[str, ...] = ("doc-1",),
            versions: tuple[str, ...] = ("ver-1",), workspace: str = "ws-1") -> Viewer:
    return Viewer(
        customer_id=customer_id,
        workspace_id=workspace,
        readable_document_ids=frozenset(docs),
        readable_version_ids=frozenset(versions),
    )


def _write(patch: dict | None = None, *, posts=None) -> QaWrite:
    values = {
        "question": "Vad gäller uppsägning?",
        "version": "ver-1",
        "document": "doc-1",
        "status": "ANSWERED",
        "created": "2026-10-11T10:00:00Z",
        "asked": "2026-10-11T10:00:00Z",
        "embedding": _vector(1.0),
        "text": "Svar om uppsägning.",
    }
    values.update(patch or {})
    cites = (
        SourceCite("unit-1", "Paragraf 12 reglerar uppsägning.", start=0, end=32,
                   position_validated=True),
    )
    return QaWrite(
        question_text=values["question"],
        document_id=values["document"],
        document_version_id=values["version"],
        workspace_id="ws-1",
        contract=CONTRACT,
        status=values["status"],
        answer_text=values["text"],
        posts=posts or (AnswerPostWrite("Huvudpost", cites),),
        asked_at=values["asked"],
        created_at=values["created"],
        embedding=values["embedding"],
    )


@pytest.fixture
def tenants(tmp_path):
    registry = TenantCatalogs(tmp_path, dimension=DIM)
    try:
        yield registry
    finally:
        registry.close()


def test_client_cannot_choose_tenant_file(tenants):
    with pytest.raises(ValueError):
        tenants.open_for("1")
    with pytest.raises(ValueError):
        tenants.open_for(True)


def test_tenants_cannot_read_each_others_qa(tenants):
    alice = _viewer(1)
    persist(tenants.open_for(1), alice, _write())
    bob = _viewer(2, docs=("doc-1",), versions=("ver-1",))
    assert exact_reuse(
        tenants.open_for(2), bob, question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    ) is None
    alice_key = persist(tenants.open_for(1), alice, _write()).key
    assert tenants.open_for(2).get_by_key(QUESTION, alice_key) is None


def test_workspace_and_document_permissions(tenants):
    catalog = tenants.open_for(1)
    persist(catalog, _viewer(), _write())
    stranger = _viewer(1, docs=("other",), versions=("ver-1",), workspace="ws-2")
    with pytest.raises(QaPermissionError):
        persist(catalog, stranger, _write())
    assert exact_reuse(
        catalog, stranger, question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    ) is None


def test_multiple_posts_and_sources(tenants):
    posts = (
        AnswerPostWrite("Första posten", (
            SourceCite("unit-1", "citat A", start=0, end=7, position_validated=True),
            SourceCite("unit-2", "citat B"),
        )),
        AnswerPostWrite("Andra posten", (SourceCite("unit-3", "citat C"),)),
    )
    loaded = persist(tenants.open_for(1), _viewer(), _write(posts=posts))
    assert len(loaded.answers) == 1
    answer = loaded.answers[0]
    assert len(answer.posts) == 2
    sources = [cite.text_unit_id for post in answer.posts for cite in post.sources]
    assert sources == ["unit-1", "unit-2", "unit-3"]
    first = answer.posts[0].sources[0]
    assert first.excerpt == "citat A" and first.position_validated
    assert first.document_version_id == "ver-1"


def test_source_must_belong_to_the_same_version(tenants):
    catalog = tenants.open_for(1)
    persist(catalog, _viewer(), _write())
    later = _write(
        {"version": "ver-2"},
        posts=(AnswerPostWrite("Ny version", (SourceCite("unit-1", "samma citat"),)),),
    )
    with pytest.raises(ValueError, match="another document version"):
        persist(catalog, _viewer(versions=("ver-1", "ver-2")), later)


def test_exact_question_is_reused(tenants):
    catalog = tenants.open_for(1)
    persist(catalog, _viewer(), _write())
    hit = exact_reuse(
        catalog, _viewer(), question_text="  vad GÄLLER uppsägning?  ",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    )
    assert hit is not None and hit.reuse == "exact"
    assert hit.answer.status == "ANSWERED"
    missing = persist(
        catalog, _viewer(),
        _write({"question": "Finns bilaga X?", "status": "NOT_FOUND",
                "text": "Hittades inte i undersökt material.",
                "created": "2026-10-11T10:05:00Z", "embedding": _vector(0.0, 1.0)}),
    )
    assert missing.answers[0].status == "NOT_FOUND"
    assert exact_reuse(
        catalog, _viewer(), question_text="Finns bilaga X?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    ) is None
    decision = cache_decision(hit, ())
    assert decision.reuse == "exact"


def test_uncertain_and_not_found_do_not_become_more_reliable(tenants):
    catalog = tenants.open_for(1)
    persist(catalog, _viewer(), _write({
        "status": "UNCERTAIN", "text": "Osäkert i undersökt material.",
    }))
    persist(catalog, _viewer(), _write({
        "question": "Finns karens?", "status": "NOT_FOUND",
        "text": "Hittades inte i undersökt material.",
        "created": "2026-10-11T10:05:00Z", "embedding": _vector(0.0, 1.0),
    }))
    viewer = _viewer()
    assert exact_reuse(
        catalog, viewer, question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    ) is None
    assert exact_reuse(
        catalog, viewer, question_text="Finns karens?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    ) is None


def test_different_scope_or_context_is_not_an_exact_hit(tenants):
    catalog = tenants.open_for(1)
    persist(catalog, _viewer(), _write())
    viewer = _viewer()
    retrieved = AnalysisContract(
        kind="document_chat", method="existing_analysis", model="test",
        model_version="v1", examined_scope="retrieved_evidence",
    )
    appendix = AnalysisContract(
        kind="document_chat", method="existing_analysis", model="test",
        model_version="v1", question_context="bilaga 2",
    )
    assert exact_reuse(
        catalog, viewer, question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=retrieved,
    ) is None
    assert exact_reuse(
        catalog, viewer, question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=appendix,
    ) is None


def test_semantic_similarity_is_not_a_cache_hit(tenants):
    catalog = tenants.open_for(1)
    persist(catalog, _viewer(), _write({"embedding": _vector(1.0, 0.2)}))
    hit = exact_reuse(
        catalog, _viewer(), question_text="När får avtalet sägas upp?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    )
    candidates = semantic_candidates(
        catalog, _viewer(), embedding=_vector(1.0, 0.19),
        document_id="doc-1", document_version_id="ver-1",
    )
    assert hit is None
    assert candidates and candidates[0].reuse == "semantic"
    assert cache_decision(hit, candidates).reuse == "none"


def test_new_version_does_not_inherit_answers(tenants):
    catalog = tenants.open_for(1)
    persist(catalog, _viewer(), _write({"embedding": _vector(1.0)}))
    viewer = _viewer(versions=("ver-1", "ver-2"))
    assert exact_reuse(
        catalog, viewer, question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-2", contract=CONTRACT,
    ) is None
    candidates = semantic_candidates(
        catalog, viewer, embedding=_vector(1.0),
        document_id="doc-1", document_version_id="ver-2",
    )
    assert candidates and candidates[0].current_version is False


def test_verified_answer_beats_unreviewed_and_rejected_is_not_reused(tenants):
    catalog = tenants.open_for(1)
    first = persist(catalog, _viewer(), _write({"created": "2026-10-11T10:00:00Z", "text": "första"}))
    second = persist(catalog, _viewer(), _write({"created": "2026-10-11T11:00:00Z", "text": "andra"}))
    review_answer(
        catalog, _viewer(), first.answers[0].key,
        action="approve", reviewed_at="2026-10-11T12:00:00Z", reviewer="anna",
    )
    hit = exact_reuse(
        catalog, _viewer(), question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    )
    assert hit is not None and hit.answer.text == "första"
    assert hit.answer.review_status == "user_verified"
    review_answer(
        catalog, _viewer(), first.answers[0].key,
        action="reject", reviewed_at="2026-10-11T13:00:00Z", reviewer="anna",
    )
    later = exact_reuse(
        catalog, _viewer(), question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    )
    assert later is not None and later.answer.text == "andra"
    review_answer(
        catalog, _viewer(), second.answers[-1].key,
        action="reject", reviewed_at="2026-10-11T14:00:00Z", reviewer="anna",
    )
    assert exact_reuse(
        catalog, _viewer(), question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    ) is None
    history = review_history(catalog, first.answers[0].key)
    assert [item["action"] for item in history] == ["approve", "reject"]


def test_archive_hides_and_purge_removes(tenants):
    catalog = tenants.open_for(1)
    outbox = QaOutbox(tenants)
    loaded = persist(catalog, _viewer(), _write())
    archive_document(catalog, _viewer(), "doc-1")
    assert document_is_archived(catalog, "doc-1")
    assert load_question(catalog, loaded.key) is not None
    assert exact_reuse(
        catalog, _viewer(), question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    ) is None
    hidden = exact_reuse(
        catalog, _viewer(), question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
        include_archived=True,
    )
    assert hidden is not None
    outbox.enqueue(_viewer(), _write({"created": "2026-10-11T15:00:00Z", "text": "senare"}))
    purge_document(catalog, _viewer(), "doc-1", outbox=outbox)
    assert document_exists(catalog, "doc-1") is False
    assert catalog.get_by_key(QUESTION, loaded.key) is None
    results = outbox.flush()
    assert results == []
    assert catalog.get_by_key(QUESTION, loaded.key) is None


def test_failed_writeback_does_not_block_answer(tenants):
    catalog = tenants.open_for(1)

    def boom(*_args, **_kwargs):
        raise QaStoreError("disk full")

    answer = persist_after_answer(catalog, _viewer(), _write(), persist_fn=boom)
    assert answer.text == "Svar om uppsägning." and answer.persisted is False
    outbox = QaOutbox(tenants, persist_fn=boom)
    queued = outbox.enqueue(_viewer(), _write())
    assert queued.persisted is False
    flushed = outbox.flush()
    assert flushed[0].ok is False
    assert exact_reuse(
        catalog, _viewer(), question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    ) is None


@pytest.mark.asyncio
async def test_ingest_does_not_create_qa(tmp_path):
    catalog = open_catalog(tmp_path / "knowledge", kind="knowledge", dimension=DIM)
    try:
        text = "36 § avtalslagen"
        digest = hash_text(text)
        await ingest_document_units(catalog, [TextUnitWrite(
            unit_id=make_text_unit_id(
                document_version_id="ver-1", locator="p0", content_hash=digest,
            ),
            scope=customer_scope(1),
            document_id="doc-1",
            document_version_id="ver-1",
            text=text,
            content_hash=digest,
            ordinal=0,
            embedding=_vector(0.4),
        )])
        assert catalog.vector_search("dense", {
            "k": 5,
            "dense_query": _vector(1.0),
            "label_filter": {"labels": [QUESTION], "mode": "all"},
        }) == []
    finally:
        catalog.close()


def test_document_qa_is_not_wired_into_chat_or_ingest():
    allowed = {
        "app/main.py",
        "app/services/document_find/fixture.py",
        "app/services/document_find/labels.py",
        "app/services/document_ingest_job.py",
        "app/services/graph_v2/outbox.py",
        "app/services/graph_v2/worker.py",
        "app/services/workspace/tool_handlers.py",
        "app/services/workspace_research_answer.py",
        "app/services/workspace_research_job.py",
    }
    leaked = [
        str(path.relative_to(APP.parent))
        for path in APP.rglob("*.py")
        if "document_qa" not in path.parts and "document_qa" in path.read_text()
    ]
    assert set(leaked) <= allowed
    ingest = (APP / "services/overgraph/ingest.py").read_text()
    assert "Question" not in ingest and "document_qa" not in ingest
    job = (APP / "services/document_ingest_job.py").read_text()
    assert "enqueue_document_catalog" in job
    assert "experiments/overgraph_ingest" not in job
    chat = (APP / "services/workspace_chat_turn.py").read_text()
    assert "document_qa" not in chat
    producer = (APP / "services/workspace_research_answer.py").read_text()
    assert "enqueue_workspace_document_answer" in producer
    assert "exact_reuse" not in producer and "semantic_candidates" not in producer
    job = (APP / "services/workspace_research_job.py").read_text()
    assert "try_reuse_workspace_answer" in job
    assert "semantic_candidates" not in job


def test_two_tenants_write_in_parallel(tenants):
    def work(customer_id: int, document_id: str) -> None:
        persist(
            tenants.open_for(customer_id),
            _viewer(customer_id, docs=(document_id,)),
            _write({"document": document_id}),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(work, 1, "doc-a")
        second = pool.submit(work, 2, "doc-b")
        first.result()
        second.result()
    assert exact_reuse(
        tenants.open_for(1), _viewer(1, docs=("doc-a",)),
        question_text="Vad gäller uppsägning?",
        document_id="doc-a", document_version_id="ver-1", contract=CONTRACT,
    ) is not None


def test_same_tenant_read_and_write_are_safe(tenants):
    catalog = tenants.open_for(1)
    persist(catalog, _viewer(), _write())

    def reader() -> None:
        exact_reuse(
            catalog, _viewer(), question_text="Vad gäller uppsägning?",
            document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
        )

    def writer() -> None:
        persist(catalog, _viewer(), _write({"created": "2026-10-11T16:00:00Z", "text": "uppdaterat"}))

    with ThreadPoolExecutor(max_workers=2) as pool:
        read = pool.submit(reader)
        write = pool.submit(writer)
        read.result()
        write.result()


def test_registry_keeps_one_catalog_per_tenant(tenants):
    first = tenants.open_for(1)
    second = tenants.open_for(1)
    other = tenants.open_for(2)
    assert first is second
    assert other is not first


def test_latency_cache_and_storage(tenants):
    catalog = tenants.open_for(1)
    started = time.perf_counter()
    persist(catalog, _viewer(), _write())
    persist_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    hit = exact_reuse(
        catalog, _viewer(), question_text="Vad gäller uppsägning?",
        document_id="doc-1", document_version_id="ver-1", contract=CONTRACT,
    )
    exact_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    candidates = semantic_candidates(
        catalog, _viewer(), embedding=_vector(1.0),
        document_id="doc-1", document_version_id="ver-1",
    )
    semantic_ms = (time.perf_counter() - started) * 1000
    stored = sum(path.stat().st_size for path in catalog.path.rglob("*") if path.is_file())
    assert hit is not None and cache_decision(hit, candidates).reuse == "exact"
    assert persist_ms < 2000 and exact_ms < 500 and semantic_ms < 500
    assert 0 < stored < 5_000_000
