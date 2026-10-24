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
    verification_key,
)
from app.services.clause_ssr.labels import (
    ABOUT,
    ANSWERS as ANSWERS_EDGE,
    ANCHOR,
    CLASSIFICATION,
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

    async def record_decision(
        self,
        *,
        scope: KnowledgeTenantScope,
        classification_id: str,
        unit_id: str,
        reviewer_id: str,
        answer: DecisionAnswer,
    ) -> dict[str, Any]:
        if answer not in ANSWERS:
            raise ValueError(f"unknown decision answer: {answer}")
        key = verification_key(scope.scope_key, classification_id, unit_id, reviewer_id)
        for _attempt in range(3):
            classification = await self._read(CLASSIFICATION, classification_id)
            unit = await self._read("TextUnit", unit_id)
            if classification is None:
                raise KeyError(f"unknown classification {classification_id}")
            if unit is None:
                raise KeyError(f"unknown TextUnit {unit_id}")
            existing = await self._read(VERIFICATION, key)
            revision = int((existing or {}).get("revision") or 0) + 1
            status = "active"
            props = {
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
                "status": status,
                "review_key": review_key(classification_id, reviewer_id),
                "labeled": answer in LABEL_ANSWERS,
            }
            nodes: list[dict[str, Any]] = [
                {
                    "labels": [VERIFICATION, scope_label(scope.scope_key)],
                    "key": key,
                    "props": props,
                }
            ]
            edges: list[dict[str, Any]] = [
                {"from": {"label": VERIFICATION, "key": key}, "to": {"label": CLASSIFICATION, "key": classification_id}, "label": ABOUT},
                {"from": {"label": VERIFICATION, "key": key}, "to": {"label": "TextUnit", "key": unit_id}, "label": ANSWERS_EDGE},
            ]
            expected: dict[str, Any] = {"expected_absent": [{"label": VERIFICATION, "key": key}]}
            if existing is not None:
                expected = {"expected_nodes": [{"label": VERIFICATION, "key": key, "props": {"revision": int(existing.get("revision") or 1), "status": str(existing.get("status") or "active")}}]}
                if existing.get("status") == "active" and existing.get("answer") == answer:
                    return existing
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
            result = await self._apply(f"decision:{key}:{revision}", {**expected, "upsert_nodes": nodes, "upsert_edges": edges})
            if result.get("error") == "precondition_failed":
                continue
            return {"verification": props, "result": result}
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
