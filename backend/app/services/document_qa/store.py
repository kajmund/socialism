"""Persist an already-produced analysis. No extra model call."""

from __future__ import annotations

import json

from app.services.document_qa.access import Viewer
from app.services.document_qa.labels import (
    ABOUT_VERSION,
    ANSWER,
    ANSWER_POST,
    CANONICAL_DOCUMENT,
    CITES,
    CONTAINS,
    DOCUMENT_VERSION,
    HAS_ANSWER,
    HAS_POST,
    HAS_QUESTION,
    HAS_VERSION,
    QUESTION,
    TEXT_UNIT,
)
from app.services.document_qa.normalize import (
    answer_key,
    normalize_question,
    post_key,
    question_key,
    reuse_digest,
)
from app.services.document_qa.types import (
    LoadedAnswer,
    LoadedCite,
    LoadedPost,
    LoadedQuestion,
    QaWrite,
    SourceCite,
)
from app.services.overgraph.catalogs import Catalog
from app.services.overgraph.model import GraphRecord


def persist(catalog: Catalog, viewer: Viewer, write: QaWrite) -> LoadedQuestion:
    viewer.require(write.document_id, write.document_version_id)
    document = _upsert_document(catalog, write)
    version = _upsert_version(catalog, write, document)
    question = _upsert_question(catalog, viewer, write, document=document, version=version)
    answer = _upsert_answer(catalog, viewer, write, question)
    for ordinal, post in enumerate(write.posts):
        _upsert_post(catalog, viewer, write, answer, ordinal=ordinal, text=post.text, sources=post.sources)
    loaded = load_question(catalog, question.key)
    if loaded is None:
        raise RuntimeError("persisted Q&A is missing after write")
    return loaded


def load_question(catalog: Catalog, key: str) -> LoadedQuestion | None:
    row = catalog.get_by_key(QUESTION, key)
    if row is None or row.engine_id is None:
        return None
    answers = tuple(sorted(
        (
            answer
            for answer_id in catalog.neighbors(
                row.engine_id, edge_label_filter=[HAS_ANSWER]
            )
            if (answer := _load_answer(catalog, answer_id)) is not None
        ),
        key=lambda item: item.created_at,
    ))
    return _question_from(row, answers)


def load_answer(catalog: Catalog, key: str) -> LoadedAnswer | None:
    row = catalog.get_by_key(ANSWER, key)
    if row is None or row.engine_id is None:
        return None
    return _load_answer(catalog, row.engine_id)


def _upsert_document(catalog: Catalog, write: QaWrite) -> GraphRecord:
    existing = catalog.get_by_key(CANONICAL_DOCUMENT, write.document_id)
    archived = int((existing.props if existing else {}).get("archived") or 0)
    catalog.upsert_node(
        [CANONICAL_DOCUMENT],
        write.document_id,
        props={"document_id": write.document_id, "archived": archived},
    )
    row = catalog.get_by_key(CANONICAL_DOCUMENT, write.document_id)
    if row is None:
        raise RuntimeError("document node missing after upsert")
    return row


def _upsert_version(catalog: Catalog, write: QaWrite, document: GraphRecord) -> GraphRecord:
    catalog.upsert_node(
        [DOCUMENT_VERSION],
        write.document_version_id,
        props={
            "document_id": write.document_id,
            "document_version_id": write.document_version_id,
        },
    )
    row = catalog.get_by_key(DOCUMENT_VERSION, write.document_version_id)
    if row is None or row.engine_id is None or document.engine_id is None:
        raise RuntimeError("document version node missing after upsert")
    catalog.upsert_edge(document.engine_id, row.engine_id, HAS_VERSION)
    return row


def _upsert_question(
    catalog: Catalog,
    viewer: Viewer,
    write: QaWrite,
    *,
    document: GraphRecord,
    version: GraphRecord,
) -> GraphRecord:
    normalized = normalize_question(write.question_text)
    digest = reuse_digest(normalized, write.document_version_id, write.contract)
    key = question_key(viewer.customer_id, digest)
    existing = catalog.get_by_key(QUESTION, key)
    vector = write.embedding if write.embedding is not None else (
        existing.dense_vector if existing is not None else None
    )
    archived = int((existing.props if existing else {}).get("archived") or 0)
    catalog.upsert_node(
        [QUESTION],
        key,
        props={
            "text": write.question_text,
            "normalized": normalized,
            "reuse_digest": digest,
            "document_id": write.document_id,
            "document_version_id": write.document_version_id,
            "workspace_id": write.workspace_id,
            "kind": write.contract.kind,
            "method": write.contract.method,
            "model": write.contract.model,
            "model_version": write.contract.model_version,
            "examined_scope": write.contract.examined_scope,
            "question_context": write.contract.question_context,
            "asked_at": write.asked_at,
            "archived": archived,
        },
        dense_vector=vector,
    )
    row = catalog.get_by_key(QUESTION, key)
    if row is None or row.engine_id is None:
        raise RuntimeError("question node missing after upsert")
    if document.engine_id is not None:
        catalog.upsert_edge(document.engine_id, row.engine_id, HAS_QUESTION)
    if version.engine_id is not None:
        catalog.upsert_edge(row.engine_id, version.engine_id, ABOUT_VERSION)
    return row


def _upsert_answer(
    catalog: Catalog, viewer: Viewer, write: QaWrite, question: GraphRecord
) -> GraphRecord:
    digest = str(question.props.get("reuse_digest") or "")
    key = answer_key(viewer.customer_id, digest, write.created_at, write.answer_text)
    catalog.upsert_node(
        [ANSWER],
        key,
        props={
            "question_key": question.key,
            "document_id": write.document_id,
            "document_version_id": write.document_version_id,
            "status": write.status,
            "text": write.answer_text,
            "model": write.contract.model,
            "model_version": write.contract.model_version,
            "method": write.contract.method,
            "review_status": "unreviewed",
            "created_at": write.created_at,
        },
    )
    row = catalog.get_by_key(ANSWER, key)
    if row is None or row.engine_id is None or question.engine_id is None:
        raise RuntimeError("answer node missing after upsert")
    catalog.upsert_edge(question.engine_id, row.engine_id, HAS_ANSWER)
    return row


def _upsert_post(
    catalog: Catalog,
    viewer: Viewer,
    write: QaWrite,
    answer: GraphRecord,
    *,
    ordinal: int,
    text: str,
    sources: tuple[SourceCite, ...],
) -> GraphRecord:
    key = post_key(viewer.customer_id, answer.key, ordinal)
    cites = [_anchor_cite(catalog, write, cite) for cite in sources]
    catalog.upsert_node(
        [ANSWER_POST],
        key,
        props={
            "answer_key": answer.key,
            "text": text,
            "ordinal": ordinal,
            "cites_json": json.dumps(cites, ensure_ascii=False),
        },
    )
    row = catalog.get_by_key(ANSWER_POST, key)
    if row is None or row.engine_id is None or answer.engine_id is None:
        raise RuntimeError("answer post missing after upsert")
    catalog.upsert_edge(answer.engine_id, row.engine_id, HAS_POST)
    _link_cites(catalog, row, sources)
    return row


def _anchor_cite(catalog: Catalog, write: QaWrite, cite: SourceCite) -> dict[str, object]:
    existing = catalog.get_by_key(TEXT_UNIT, cite.text_unit_id)
    if existing is not None:
        version = str(existing.props.get("document_version_id") or "")
        if version and version != write.document_version_id:
            raise ValueError("source TextUnit belongs to another document version")
    catalog.upsert_node(
        [TEXT_UNIT],
        cite.text_unit_id,
        props={
            "unit_id": cite.text_unit_id,
            "document_id": write.document_id,
            "document_version_id": write.document_version_id,
            "text": cite.excerpt,
        },
    )
    unit = catalog.get_by_key(TEXT_UNIT, cite.text_unit_id)
    version = catalog.get_by_key(DOCUMENT_VERSION, write.document_version_id)
    if unit is None or version is None or unit.engine_id is None or version.engine_id is None:
        raise RuntimeError("source TextUnit missing after upsert")
    catalog.upsert_edge(version.engine_id, unit.engine_id, CONTAINS)
    return {
        "text_unit_id": cite.text_unit_id,
        "excerpt": cite.excerpt,
        "start": cite.start,
        "end": cite.end,
        "position_validated": cite.position_validated,
        "document_version_id": write.document_version_id,
    }


def _link_cites(catalog: Catalog, post: GraphRecord, sources: tuple[SourceCite, ...]) -> None:
    if post.engine_id is None:
        raise RuntimeError("answer post is missing an engine id")
    for cite in sources:
        unit = catalog.get_by_key(TEXT_UNIT, cite.text_unit_id)
        if unit is None or unit.engine_id is None:
            raise RuntimeError("cited TextUnit is missing")
        catalog.upsert_edge(
            post.engine_id,
            unit.engine_id,
            CITES,
            props={
                "excerpt": cite.excerpt,
                "start": cite.start if cite.start is not None else -1,
                "end": cite.end if cite.end is not None else -1,
                "position_validated": int(cite.position_validated),
            },
        )


def _load_answer(catalog: Catalog, engine_id: int) -> LoadedAnswer | None:
    row = catalog.get(engine_id)
    if row is None or ANSWER not in row.labels:
        return None
    posts = tuple(
        post
        for post_id in catalog.neighbors(engine_id, edge_label_filter=[HAS_POST])
        if (post := _load_post(catalog, post_id)) is not None
    )
    posts = tuple(sorted(posts, key=lambda item: item.ordinal))
    return LoadedAnswer(
        key=row.key,
        status=str(row.props.get("status") or ""),
        text=str(row.props.get("text") or ""),
        model=str(row.props.get("model") or ""),
        model_version=str(row.props.get("model_version") or ""),
        method=str(row.props.get("method") or ""),
        review_status=str(row.props.get("review_status") or "unreviewed"),
        created_at=str(row.props.get("created_at") or ""),
        posts=posts,
    )


def _load_post(catalog: Catalog, engine_id: int) -> LoadedPost | None:
    row = catalog.get(engine_id)
    if row is None or ANSWER_POST not in row.labels:
        return None
    raw = json.loads(str(row.props.get("cites_json") or "[]"))
    sources = tuple(
        LoadedCite(
            text_unit_id=str(item["text_unit_id"]),
            excerpt=str(item["excerpt"]),
            start=item.get("start"),
            end=item.get("end"),
            position_validated=bool(item.get("position_validated")),
            document_version_id=str(item["document_version_id"]),
        )
        for item in raw
    )
    return LoadedPost(
        key=row.key,
        text=str(row.props.get("text") or ""),
        ordinal=int(row.props.get("ordinal") or 0),
        sources=sources,
    )


def _question_from(row: GraphRecord, answers: tuple[LoadedAnswer, ...]) -> LoadedQuestion:
    return LoadedQuestion(
        key=row.key,
        text=str(row.props.get("text") or ""),
        normalized=str(row.props.get("normalized") or ""),
        document_id=str(row.props.get("document_id") or ""),
        document_version_id=str(row.props.get("document_version_id") or ""),
        workspace_id=str(row.props.get("workspace_id") or ""),
        asked_at=str(row.props.get("asked_at") or ""),
        archived=bool(int(row.props.get("archived") or 0)),
        answers=answers,
    )
