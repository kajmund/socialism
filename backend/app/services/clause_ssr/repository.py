"""Async persistence boundary for clause SSR mutations.

Domain rules stay synchronous; this module reads current node state, builds one
atomic owner batch and retries only read-modify-write precondition conflicts.
"""

from __future__ import annotations

from typing import Any

from app.services.clause_ssr.graph import now_ms
from app.services.clause_ssr.keys import (
    anchor_key,
    review_key,
    revision_key,
    session_key,
    verification_key,
)
from app.services.clause_ssr.labels import (
    ABOUT,
    ANSWERS as ANSWERS_EDGE,
    ANCHOR,
    CLASSIFICATION,
    FOR,
    REVIEW_SESSION,
    SUPERSEDES,
    VERIFICATION,
    VERIFICATION_REVISION,
)
from app.services.clause_ssr.types import ANSWERS, LABEL_ANSWERS, DecisionAnswer
from app.services.clause_ssr.verifications import polarity_for
from app.services.knowledge.scope import KnowledgeTenantScope
from app.services.overgraph.labels import scope_label
from app.services.overgraph.owner import OwnerClient


class ClauseRepository:
    def __init__(self, client: OwnerClient) -> None:
        self.client = client

    async def _read(self, label: str, key: str) -> dict[str, Any] | None:
        response = await self.client.read([{"label": label, "key": key}])
        return response["values"].get(f"{label}:{key}")

    async def _apply(self, mutation_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        return await self.client.mutate(mutation_id, patch, kind="batch")

    async def get_or_create_session(
        self,
        *,
        scope: KnowledgeTenantScope,
        reviewer_id: str,
        classification_id: str,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        session_id = session_key(scope.scope_key, reviewer_id, classification_id, document_id)
        for _attempt in range(3):
            existing = await self._read(REVIEW_SESSION, session_id)
            if existing is not None:
                return existing
            props = {
                "id": session_id,
                "scope_key": scope.scope_key,
                "reviewer_id": reviewer_id,
                "classification_id": classification_id,
                "document_id": document_id or "",
                "last_unit_id": "",
                "last_verification_id": "",
                "decided_yes": 0,
                "decided_no": 0,
                "skipped": 0,
                "unsure": 0,
                "session_version": 1,
            }
            result = await self._apply(
                f"session:{session_id}",
                {
                    "expected_absent": [{"label": REVIEW_SESSION, "key": session_id}],
                    "upsert_nodes": [{
                        "labels": [REVIEW_SESSION, scope_label(scope.scope_key)],
                        "key": session_id, "props": props,
                    }],
                    "upsert_edges": [{
                        "from": {"label": REVIEW_SESSION, "key": session_id},
                        "to": {"label": CLASSIFICATION, "key": classification_id},
                        "label": FOR,
                    }],
                },
            )
            if result.get("error") == "precondition_failed":
                continue
            return props
        raise RuntimeError("clause session precondition conflict")

    async def record_decision(  # noqa: C901, PLR0912
        self,
        *,
        scope: KnowledgeTenantScope,
        classification_id: str,
        unit_id: str,
        reviewer_id: str,
        answer: DecisionAnswer,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        if answer not in ANSWERS:
            raise ValueError(f"unknown decision answer: {answer}")
        key = verification_key(scope.scope_key, classification_id, unit_id, reviewer_id)
        session_id = session_key(scope.scope_key, reviewer_id, classification_id, document_id)
        for _attempt in range(3):
            classification = await self._read(CLASSIFICATION, classification_id)
            unit = await self._read("TextUnit", unit_id)
            if classification is None:
                raise KeyError(f"unknown classification {classification_id}")
            if unit is None:
                raise KeyError(f"unknown TextUnit {unit_id}")
            existing = await self._read(VERIFICATION, key)
            session = await self._read(REVIEW_SESSION, session_id)
            if existing is not None and existing.get("status") == "active" and existing.get("answer") == answer:
                return {"verification": dict(existing), "session": session or {}, "duplicate": True}
            revision = int((existing or {}).get("revision") or 0) + 1
            props = {
                "id": key,
                "scope_key": scope.scope_key,
                "source_unit_id": unit_id,
                "source_document_id": str(unit.get("document_id") or ""),
                "content_hash": str(unit.get("content_hash") or ""),
                "classification_id": classification_id,
                "classification_version": int(classification.get("version") or 1),
                "question": str(classification.get("question") or ""),
                "category": str(classification.get("category") or ""),
                "answer": answer,
                "polarity": polarity_for(answer) or "",
                "reviewer_id": reviewer_id,
                "decided_at_ms": now_ms(),
                "source": "admin_queue",
                "revision": revision,
                "status": "active",
                "review_key": review_key(classification_id, reviewer_id),
                "labeled": answer in LABEL_ANSWERS,
            }
            nodes: list[dict[str, Any]] = [{
                "labels": [VERIFICATION, scope_label(scope.scope_key)],
                "key": key,
                "props": props,
            }]
            edges: list[dict[str, Any]] = [
                {"from": {"label": VERIFICATION, "key": key}, "to": {"label": CLASSIFICATION, "key": classification_id}, "label": ABOUT},
                {"from": {"label": VERIFICATION, "key": key}, "to": {"label": "TextUnit", "key": unit_id}, "label": ANSWERS_EDGE},
            ]
            expected: dict[str, Any] = {"expected_absent": [{"label": VERIFICATION, "key": key}]}
            if existing is not None:
                expected = {"expected_nodes": [{"label": VERIFICATION, "key": key, "props": {"revision": int(existing.get("revision") or 1), "status": str(existing.get("status") or "active")}}]}
                if existing.get("status") == "active":
                    nodes.append({
                        "labels": [VERIFICATION_REVISION, scope_label(scope.scope_key)],
                        "key": revision_key(key, int(existing.get("revision") or 1)),
                        "props": {**existing, "status": "superseded", "revision": int(existing.get("revision") or 1)},
                    })
                    edges.append({
                        "from": {"label": VERIFICATION, "key": key},
                        "to": {"label": VERIFICATION_REVISION, "key": revision_key(key, int(existing.get("revision") or 1))},
                        "label": SUPERSEDES,
                    })
            anchor = await self._read(ANCHOR, anchor_key(scope.scope_key, key))
            if anchor is not None and anchor.get("status") in {"draft", "active"}:
                nodes.append({"labels": [ANCHOR, scope_label(scope.scope_key)], "key": anchor_key(scope.scope_key, key), "props": {**anchor, "status": "revoked"}})

            counts = {
                "yes": int((session or {}).get("decided_yes") or 0),
                "no": int((session or {}).get("decided_no") or 0),
                "skip": int((session or {}).get("skipped") or 0),
                "unsure": int((session or {}).get("unsure") or 0),
            }
            if existing is not None and existing.get("status") == "active":
                old_answer = str(existing.get("answer") or "")
                if old_answer in counts:
                    counts[old_answer] = max(0, counts[old_answer] - 1)
            if answer in counts:
                counts[answer] += 1
            session_props = {
                "id": session_id,
                "scope_key": scope.scope_key,
                "reviewer_id": reviewer_id,
                "classification_id": classification_id,
                "document_id": document_id or "",
                "last_unit_id": unit_id,
                "last_verification_id": key,
                "decided_yes": counts["yes"],
                "decided_no": counts["no"],
                "skipped": counts["skip"],
                "unsure": counts["unsure"],
                "session_version": int((session or {}).get("session_version") or 0) + 1,
            }
            nodes.append({"labels": [REVIEW_SESSION, scope_label(scope.scope_key)], "key": session_id, "props": session_props})
            edges.append({"from": {"label": REVIEW_SESSION, "key": session_id}, "to": {"label": CLASSIFICATION, "key": classification_id}, "label": FOR})
            if session is None:
                expected["expected_absent"].append({"label": REVIEW_SESSION, "key": session_id})
            else:
                expected.setdefault("expected_nodes", []).append({
                    "label": REVIEW_SESSION, "key": session_id,
                    "props": {"session_version": session.get("session_version")},
                })
            result = await self._apply(f"decision:{key}:{revision}", {**expected, "upsert_nodes": nodes, "upsert_edges": edges})
            if result.get("error") == "precondition_failed":
                continue
            return {"verification": props, "session": session_props, "result": result}
        raise RuntimeError("clause decision precondition conflict")

    async def revoke_verification(
        self, *, scope: KnowledgeTenantScope, verification_id: str,
    ) -> dict[str, Any]:
        for _attempt in range(3):
            current = await self._read(VERIFICATION, verification_id)
            if current is None:
                raise KeyError(f"unknown verification {verification_id}")
            if current.get("status") == "revoked":
                return current
            revision = int(current.get("revision") or 1)
            nodes = [
                {
                    "labels": [VERIFICATION_REVISION, scope_label(scope.scope_key)],
                    "key": revision_key(verification_id, revision),
                    "props": {**current, "status": "superseded", "revision": revision},
                },
                {
                    "labels": [VERIFICATION, scope_label(scope.scope_key)],
                    "key": verification_id,
                    "props": {**current, "status": "revoked"},
                },
            ]
            anchor = await self._read(ANCHOR, anchor_key(scope.scope_key, verification_id))
            if anchor is not None:
                nodes.append({
                    "labels": [ANCHOR, scope_label(scope.scope_key)],
                    "key": anchor_key(scope.scope_key, verification_id),
                    "props": {**anchor, "status": "revoked"},
                })
            result = await self._apply(
                f"revoke:{verification_id}:{revision}",
                {
                    "expected_nodes": [{
                        "label": VERIFICATION, "key": verification_id,
                        "props": {"revision": revision, "status": str(current.get("status") or "active")},
                    }],
                    "upsert_nodes": nodes,
                    "upsert_edges": [{
                        "from": {"label": VERIFICATION, "key": verification_id},
                        "to": {"label": VERIFICATION_REVISION, "key": revision_key(verification_id, revision)},
                        "label": SUPERSEDES,
                    }],
                },
            )
            if result.get("error") == "precondition_failed":
                continue
            return {**current, "status": "revoked", "result": result}
        raise RuntimeError("clause revocation precondition conflict")

    async def undo_last(
        self,
        *,
        scope: KnowledgeTenantScope,
        reviewer_id: str,
        classification_id: str,
        document_id: str | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        session_id = session_key(scope.scope_key, reviewer_id, classification_id, document_id)
        for _attempt in range(3):
            session = await self._read(REVIEW_SESSION, session_id)
            if session is None or not session.get("last_verification_id"):
                return session, None
            verification_id = str(session["last_verification_id"])
            current = await self._read(VERIFICATION, verification_id)
            if current is None:
                return session, None
            revision = int(current.get("revision") or 1)
            unit_id = str(current.get("source_unit_id") or "")
            nodes = [
                {
                    "labels": [VERIFICATION_REVISION, scope_label(scope.scope_key)],
                    "key": revision_key(verification_id, revision),
                    "props": {**current, "status": "superseded", "revision": revision},
                },
                {
                    "labels": [VERIFICATION, scope_label(scope.scope_key)],
                    "key": verification_id,
                    "props": {**current, "status": "revoked"},
                },
            ]
            anchor = await self._read(ANCHOR, anchor_key(scope.scope_key, verification_id))
            if anchor is not None:
                nodes.append({
                    "labels": [ANCHOR, scope_label(scope.scope_key)],
                    "key": anchor_key(scope.scope_key, verification_id),
                    "props": {**anchor, "status": "revoked"},
                })
            counts = {
                "yes": int(session.get("decided_yes") or 0),
                "no": int(session.get("decided_no") or 0),
                "skip": int(session.get("skipped") or 0),
                "unsure": int(session.get("unsure") or 0),
            }
            old_answer = str(current.get("answer") or "")
            if old_answer in counts:
                counts[old_answer] = max(0, counts[old_answer] - 1)
            session_props = {
                "id": session_id,
                "scope_key": scope.scope_key,
                "reviewer_id": reviewer_id,
                "classification_id": classification_id,
                "document_id": document_id or "",
                "last_unit_id": "",
                "last_verification_id": "",
                "decided_yes": counts["yes"],
                "decided_no": counts["no"],
                "skipped": counts["skip"],
                "unsure": counts["unsure"],
                "session_version": int(session.get("session_version") or 0) + 1,
            }
            nodes.append({"labels": [REVIEW_SESSION, scope_label(scope.scope_key)], "key": session_id, "props": session_props})
            result = await self._apply(
                f"undo:{verification_id}:{revision}",
                {
                    "expected_nodes": [
                        {"label": VERIFICATION, "key": verification_id, "props": {"revision": revision, "status": str(current.get("status") or "active")}},
                        {"label": REVIEW_SESSION, "key": session_id, "props": {"session_version": session.get("session_version")}},
                    ],
                    "upsert_nodes": nodes,
                    "upsert_edges": [{
                        "from": {"label": VERIFICATION, "key": verification_id},
                        "to": {"label": VERIFICATION_REVISION, "key": revision_key(verification_id, revision)},
                        "label": SUPERSEDES,
                    }],
                },
            )
            if result.get("error") == "precondition_failed":
                continue
            return session_props, unit_id
        raise RuntimeError("clause undo precondition conflict")

    async def promote_anchor(
        self,
        *,
        scope: KnowledgeTenantScope,
        verification_id: str,
        embedding: Any,
    ) -> dict[str, Any]:
        anchor_id = anchor_key(scope.scope_key, verification_id)
        for _attempt in range(3):
            verification = await self._read(VERIFICATION, verification_id)
            if verification is None:
                raise KeyError(f"unknown verification {verification_id}")
            if verification.get("status") != "active" or verification.get("answer") not in LABEL_ANSWERS:
                raise ValueError("only active yes/no verifications can become anchors")
            polarity = str(verification.get("polarity") or "")
            if polarity not in {"positive", "negative"}:
                raise ValueError("skip/unsure cannot become anchors")
            existing = await self._read(ANCHOR, anchor_id)
            if existing is not None and existing.get("status") not in {"revoked", "source_revoked"}:
                return existing
            unit = await self._read("TextUnit", str(verification.get("source_unit_id") or ""))
            if unit is None:
                raise KeyError("verification source unit is missing")
            read = await self.client.read(
                [{"label": "TextUnit", "key": str(unit.get("id") or verification.get("source_unit_id"))}],
                include_vectors=True,
            )
            key_name = f"TextUnit:{verification.get('source_unit_id')}"
            vector = (read.get("vectors") or {}).get(key_name)
            if vector is not None and len(vector) != int(getattr(embedding, "dimension", len(vector))):
                vector = None
            status = "draft" if vector is not None else "stale_embedding"
            props = {
                "id": anchor_id,
                "scope_key": scope.scope_key,
                "verification_id": verification_id,
                "source_unit_id": str(verification.get("source_unit_id") or ""),
                "classification_id": str(verification.get("classification_id") or ""),
                "category": str(verification.get("category") or ""),
                "polarity": polarity,
                "content_hash": str(verification.get("content_hash") or ""),
                "status": status,
                "embedding_model": str(getattr(embedding, "model", "")),
                "embedding_revision": str(getattr(embedding, "revision", "")),
                "embedding_dimension": int(getattr(embedding, "dimension", 0)),
                "reviewer_id": str(verification.get("reviewer_id") or ""),
                "question": str(verification.get("question") or ""),
            }
            patch = {
                "expected_nodes": [{
                    "label": VERIFICATION, "key": verification_id,
                    "props": {"revision": int(verification.get("revision") or 1), "status": "active"},
                }],
                "upsert_nodes": [{
                    "labels": [ANCHOR, scope_label(scope.scope_key)],
                    "key": anchor_id, "props": props,
                    "dense_vector": vector,
                }],
                "upsert_edges": [
                    {"from": {"label": ANCHOR, "key": anchor_id}, "to": {"label": VERIFICATION, "key": verification_id}, "label": "ssr.DERIVED_FROM"},
                    {"from": {"label": ANCHOR, "key": anchor_id}, "to": {"label": "TextUnit", "key": props["source_unit_id"]}, "label": "ssr.REPRESENTS"},
                ],
            }
            if existing is None:
                patch["expected_absent"] = [{"label": ANCHOR, "key": anchor_id}]
            else:
                patch["expected_nodes"].append({
                    "label": ANCHOR, "key": anchor_id,
                    "props": {"status": existing.get("status")},
                })
            result = await self._apply(f"promote:{anchor_id}:{verification.get('revision')}", patch)
            if result.get("error") == "precondition_failed":
                continue
            return props
        raise RuntimeError("clause promotion precondition conflict")
