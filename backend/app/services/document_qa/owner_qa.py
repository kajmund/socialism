"""Owner-backed tenant Q&A reads and atomic publish."""

from __future__ import annotations

import json
from typing import Any

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
from app.services.document_qa.owner_qa_protocol import (
    OwnerQaError,
    _Batch,
    _apply,
    _edge,
    _neighbors,
    _node,
    _node_id,
    _props,
    _read,
    _vector,
)
from app.services.document_qa.types import (
    LoadedAnswer,
    LoadedCite,
    LoadedPost,
    LoadedQuestion,
    QaWrite,
    SourceCite,
)
from app.services.overgraph.owner import OwnerClient


async def _answers(
    client: OwnerClient,
    question_id: int,
) -> tuple[LoadedAnswer, ...]:
    rows = await _neighbors(client, question_id, HAS_ANSWER)
    answers = [
        await _answer_from_row(client, row) for row in rows if ANSWER in row.get("labels", [])
    ]
    return tuple(sorted(answers, key=lambda item: item.created_at))


async def _answer_from_row(client: OwnerClient, row: dict[str, Any]) -> LoadedAnswer:
    posts = tuple(
        _post_from_row(post)
        for post in await _neighbors(client, int(row["node_id"]), HAS_POST)
        if ANSWER_POST in post.get("labels", [])
    )
    return LoadedAnswer(
        key=str(row["key"]),
        status=str(row["props"].get("status") or ""),
        text=str(row["props"].get("text") or ""),
        model=str(row["props"].get("model") or ""),
        model_version=str(row["props"].get("model_version") or ""),
        method=str(row["props"].get("method") or ""),
        review_status=str(row["props"].get("review_status") or "unreviewed"),
        created_at=str(row["props"].get("created_at") or ""),
        posts=tuple(sorted(posts, key=lambda item: item.ordinal)),
    )


def _post_from_row(row: dict[str, Any]) -> LoadedPost:
    raw = json.loads(str(row["props"].get("cites_json") or "[]"))
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
        key=str(row["key"]),
        text=str(row["props"].get("text") or ""),
        ordinal=int(row["props"].get("ordinal") or 0),
        sources=sources,
    )


async def load_question(client: OwnerClient, key: str) -> LoadedQuestion | None:
    response = await _read(client, [(QUESTION, key)])
    props = _props(response, QUESTION, key)
    question_id = _node_id(response, QUESTION, key)
    if props is None or question_id is None:
        return None
    return _question_from(props, key, await _answers(client, question_id))


async def load_answer(client: OwnerClient, key: str) -> LoadedAnswer | None:
    response = await _read(client, [(ANSWER, key)])
    props = _props(response, ANSWER, key)
    answer_id = _node_id(response, ANSWER, key)
    if props is None or answer_id is None:
        return None
    return await _answer_from_row(
        client,
        {"node_id": answer_id, "key": key, "labels": [ANSWER], "props": props},
    )


def _question_from(
    props: dict[str, Any],
    key: str,
    answers: tuple[LoadedAnswer, ...],
) -> LoadedQuestion:
    return LoadedQuestion(
        key=key,
        text=str(props.get("text") or ""),
        normalized=str(props.get("normalized") or ""),
        document_id=str(props.get("document_id") or ""),
        document_version_id=str(props.get("document_version_id") or ""),
        workspace_id=str(props.get("workspace_id") or ""),
        asked_at=str(props.get("asked_at") or ""),
        archived=bool(int(props.get("archived") or 0)),
        answers=answers,
    )


def _question_node(
    write: QaWrite,
    viewer: Viewer,
    *,
    existing: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    normalized = normalize_question(write.question_text)
    digest = reuse_digest(normalized, write.document_version_id, write.contract)
    key = question_key(viewer.customer_id, digest)
    archived = int((existing or {}).get("archived") or 0)
    return key, {
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
    }


async def persist(
    client: OwnerClient,
    viewer: Viewer,
    write: QaWrite,
) -> LoadedQuestion:
    """Atomically publish document/version/question/answer/posts and citations."""
    viewer.require(write.document_id, write.document_version_id)
    cited = list(dict.fromkeys(cite.text_unit_id for post in write.posts for cite in post.sources))
    refs = [
        (CANONICAL_DOCUMENT, write.document_id),
        (
            QUESTION,
            question_key(
                viewer.customer_id,
                reuse_digest(
                    normalize_question(write.question_text),
                    write.document_version_id,
                    write.contract,
                ),
            ),
        ),
        *((TEXT_UNIT, unit_id) for unit_id in cited),
    ]
    response = await _read(client, refs, include_vectors=True)
    document = _props(response, CANONICAL_DOCUMENT, write.document_id)
    existing_question_ref = refs[1]
    existing_question = _props(response, QUESTION, existing_question_ref[1])
    units = {unit_id: _props(response, TEXT_UNIT, unit_id) for unit_id in cited}
    for unit_id, unit in units.items():
        version = str((unit or {}).get("document_version_id") or "")
        if version and version != write.document_version_id:
            raise ValueError("source TextUnit belongs to another document version")

    batch = _Batch()
    document_props = {
        "document_id": write.document_id,
        "archived": int((document or {}).get("archived") or 0),
    }
    batch.nodes.append(_node(CANONICAL_DOCUMENT, write.document_id, document_props))
    batch.nodes.append(
        _node(
            DOCUMENT_VERSION,
            write.document_version_id,
            {
                "document_id": write.document_id,
                "document_version_id": write.document_version_id,
            },
        )
    )
    batch.edges.append(
        _edge(
            (CANONICAL_DOCUMENT, write.document_id),
            (DOCUMENT_VERSION, write.document_version_id),
            HAS_VERSION,
        )
    )
    vector = (
        list(write.embedding)
        if write.embedding is not None
        else _vector(response, QUESTION, existing_question_ref[1])
    )
    q_key, q_props = _question_node(write, viewer, existing=existing_question)
    batch.nodes.append(_node(QUESTION, q_key, q_props, dense_vector=vector))
    batch.edges.append(
        _edge(
            (CANONICAL_DOCUMENT, write.document_id),
            (QUESTION, q_key),
            HAS_QUESTION,
        )
    )
    batch.edges.append(
        _edge(
            (QUESTION, q_key),
            (DOCUMENT_VERSION, write.document_version_id),
            ABOUT_VERSION,
        )
    )
    digest = str(q_props["reuse_digest"])
    a_key = answer_key(
        viewer.customer_id,
        digest,
        write.created_at,
        write.answer_text,
    )
    batch.nodes.append(
        _node(
            ANSWER,
            a_key,
            {
                "question_key": q_key,
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
    )
    batch.edges.append(_edge((QUESTION, q_key), (ANSWER, a_key), HAS_ANSWER))
    for ordinal, post in enumerate(write.posts):
        _append_post(
            write=write,
            viewer=viewer,
            answer=a_key,
            ordinal=ordinal,
            post=post,
            units=units,
            batch=batch,
        )
    await _apply(client, "qa:persist", nodes=batch.nodes, edges=batch.edges)
    loaded = await load_question(client, q_key)
    if loaded is None:
        raise OwnerQaError("persisted Q&A is missing after owner write")
    return loaded


def _append_post(
    *,
    write: QaWrite,
    viewer: Viewer,
    answer: str,
    ordinal: int,
    post: Any,
    units: dict[str, dict[str, Any] | None],
    batch: _Batch,
) -> None:
    key = post_key(viewer.customer_id, answer, ordinal)
    cites = [_anchor_cite(write, cite) for cite in post.sources]
    batch.nodes.append(
        _node(
            ANSWER_POST,
            key,
            {
                "answer_key": answer,
                "text": post.text,
                "ordinal": ordinal,
                "cites_json": json.dumps(cites, ensure_ascii=False),
            },
        )
    )
    batch.edges.append(_edge((ANSWER, answer), (ANSWER_POST, key), HAS_POST))
    for cite in post.sources:
        if units.get(cite.text_unit_id) is None:
            batch.nodes.append(
                _node(
                    TEXT_UNIT,
                    cite.text_unit_id,
                    {
                        "unit_id": cite.text_unit_id,
                        "document_id": write.document_id,
                        "document_version_id": write.document_version_id,
                        "text": cite.excerpt,
                    },
                )
            )
        batch.edges.append(
            _edge(
                (DOCUMENT_VERSION, write.document_version_id),
                (TEXT_UNIT, cite.text_unit_id),
                CONTAINS,
            )
        )
        batch.edges.append(
            _edge(
                (ANSWER_POST, key),
                (TEXT_UNIT, cite.text_unit_id),
                CITES,
                {
                    "excerpt": cite.excerpt,
                    "start": cite.start if cite.start is not None else -1,
                    "end": cite.end if cite.end is not None else -1,
                    "position_validated": int(cite.position_validated),
                },
            )
        )


def _anchor_cite(write: QaWrite, cite: SourceCite) -> dict[str, object]:
    return {
        "text_unit_id": cite.text_unit_id,
        "excerpt": cite.excerpt,
        "start": cite.start,
        "end": cite.end,
        "position_validated": cite.position_validated,
        "document_version_id": write.document_version_id,
    }
