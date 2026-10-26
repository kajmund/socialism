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

    @staticmethod
    def _pool_key(scope: KnowledgeTenantScope, category: str) -> str:
        return f"anchor-pool:{scope.scope_key}:{category}"

    async def _pool_revision(self, scope: KnowledgeTenantScope, category: str) -> int:
        row = await self._read("SsrAnchorPool", self._pool_key(scope, category))
        return int((row or {}).get("revision") or 0)

    async def _pool_bump(self, scope: KnowledgeTenantScope, category: str) -> tuple[dict[str, Any], dict[str, Any]]:
        key = self._pool_key(scope, category)
        current = await self._read("SsrAnchorPool", key)
        props = {
            "scope_key": scope.scope_key,
            "category": category,
            "revision": int((current or {}).get("revision") or 0) + 1,
        }
        node = {"labels": ["SsrAnchorPool", scope_label(scope.scope_key)], "key": key, "props": props}
        expected = (
            {"expected_absent": [{"label": "SsrAnchorPool", "key": key}]}
            if current is None
            else {"expected_nodes": [{"label": "SsrAnchorPool", "key": key, "props": {"revision": current.get("revision")}}]}
        )
        return node, expected

    async def list_anchor_candidates(
        self, *, scope: KnowledgeTenantScope, category: str,
    ) -> tuple[list[dict[str, Any]], int]:
        for _attempt in range(3):
            before = await self._pool_revision(scope, category)
            rows = await self.client.list_nodes(
                ANCHOR,
                props={"category": category, "scope_key": scope.scope_key},
                include_vectors=True,
            )
            after = await self._pool_revision(scope, category)
            if before != after:
                continue
            return [
                row for row in rows
                if row["props"].get("status") in {"draft", "active"}
            ], after
        raise RuntimeError("anchor candidate snapshot changed during listing")

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
        for _attempt in range(10):
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
            pool_node, pool_expected = await self._pool_bump(scope, str(classification.get("category") or ""))
            nodes.append(pool_node)
            expected.setdefault("expected_absent", []).extend(pool_expected.get("expected_absent", []))
            expected.setdefault("expected_nodes", []).extend(pool_expected.get("expected_nodes", []))
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
            pool_node, pool_expected = await self._pool_bump(scope, str(current.get("category") or ""))
            nodes.append(pool_node)
            expected = {
                "expected_nodes": [{
                    "label": VERIFICATION, "key": verification_id,
                    "props": {"revision": revision, "status": str(current.get("status") or "active")},
                }],
            }
            expected.setdefault("expected_absent", []).extend(pool_expected.get("expected_absent", []))
            expected.setdefault("expected_nodes", []).extend(pool_expected.get("expected_nodes", []))
            result = await self._apply(
                f"revoke:{verification_id}:{revision}",
                {
                    **expected,
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
            pool_node, pool_expected = await self._pool_bump(scope, str(verification.get("category") or ""))
            patch = {
                **pool_expected,
                "expected_nodes": [{
                    "label": VERIFICATION, "key": verification_id,
                    "props": {"revision": int(verification.get("revision") or 1), "status": "active"},
                }],
                "upsert_nodes": [{
                    "labels": [ANCHOR, scope_label(scope.scope_key)],
                    "key": anchor_id, "props": props,
                    "dense_vector": vector,
                }, pool_node],
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

    async def build_anchor_set(
        self,
        *,
        scope: KnowledgeTenantScope,
        category: str,
        embedding: Any,
        holdout_ids: tuple[str, ...] = (),
        max_per_polarity: int = 12,
    ) -> dict[str, Any]:
        from app.services.clause_ssr.select import _diverse_pick
        from app.services.clause_ssr.types import Anchor, EmbeddingSpec

        for _attempt in range(3):
            candidates, pool_revision = await self.list_anchor_candidates(scope=scope, category=category)
            verification_ids = [c["props"]["verification_id"] for c in candidates if c["props"].get("verification_id")]
            verifications = await self.client.read([
                {"label": VERIFICATION, "key": key} for key in verification_ids
            ]) if verification_ids else {"values": {}}
            anchors: list[Anchor] = []
            for row in candidates:
                props = row["props"]
                vector = row.get("dense_vector")
                if vector is None or len(vector) != int(getattr(embedding, "dimension", 0)):
                    continue
                if (props.get("embedding_model"), props.get("embedding_revision"), int(props.get("embedding_dimension") or 0)) != (embedding.model, embedding.revision, embedding.dimension):
                    continue
                verification = verifications.get("values", {}).get(f"{VERIFICATION}:{props.get('verification_id')}")
                if not verification or verification.get("status") != "active" or verification.get("answer") not in LABEL_ANSWERS:
                    continue
                if props.get("source_unit_id") in holdout_ids or props.get("content_hash") in holdout_ids:
                    continue
                anchors.append(Anchor(
                    id=row["key"], verification_id=str(props.get("verification_id") or ""),
                    source_unit_id=str(props.get("source_unit_id") or ""),
                    classification_id=str(props.get("classification_id") or ""),
                    category=str(props.get("category") or ""), polarity=str(props.get("polarity") or "positive"),
                    content_hash=str(props.get("content_hash") or ""), status=str(props.get("status") or "draft"),
                    embedding=EmbeddingSpec(model=str(props.get("embedding_model") or ""), revision=str(props.get("embedding_revision") or ""), dimension=int(props.get("embedding_dimension") or 0)),
                    vector=tuple(vector), scope_key=scope.scope_key,
                    provenance={"reviewer_id": str(props.get("reviewer_id") or ""), "question": str(props.get("question") or "")},
                ))
            selected = _diverse_pick(anchors, max_per_polarity)
            existing_sets = await self.client.list_nodes(
                "SsrClauseAnchorSet", props={"category": category, "scope_key": scope.scope_key},
            )
            version = max([int((row["props"] or {}).get("version") or 0) for row in existing_sets] or [0]) + 1
            set_id = f"{scope.scope_key}:aset:{category}:v{version}"
            set_props = {
                "id": set_id, "scope_key": scope.scope_key, "version": version,
                "category": category, "status": "active",
                "selection_method": "deterministic_diversity",
                "embedding_model": embedding.model, "embedding_revision": embedding.revision,
                "embedding_dimension": embedding.dimension,
                "holdout_ids": ",".join(holdout_ids), "created_at_ms": now_ms(),
            }
            nodes = [{"labels": ["SsrClauseAnchorSet", scope_label(scope.scope_key)], "key": set_id, "props": set_props}]
            for row in existing_sets:
                if row["props"].get("status") == "active":
                    nodes.append({"labels": ["SsrClauseAnchorSet", scope_label(scope.scope_key)], "key": row["key"], "props": {**row["props"], "status": "superseded"}})
            edges = [{"from": {"label": ANCHOR, "key": anchor.id}, "to": {"label": "SsrClauseAnchorSet", "key": set_id}, "label": "ssr.MEMBER_OF"} for anchor in selected]
            pool_key = self._pool_key(scope, category)
            pool = await self._read("SsrAnchorPool", pool_key)
            expected = {
                "expected_absent": [{"label": "SsrClauseAnchorSet", "key": set_id}],
                "expected_nodes": [{"label": "SsrAnchorPool", "key": pool_key, "props": {"revision": (pool or {}).get("revision")}}],
            }
            result = await self._apply(
                f"anchor-set:{set_id}:{pool_revision}",
                {**expected, "upsert_nodes": nodes, "upsert_edges": edges},
            )
            if result.get("error") == "precondition_failed":
                continue
            return {**set_props, "member_ids": [anchor.id for anchor in selected]}
        raise RuntimeError("anchor set precondition conflict")

    async def mark_stale_embeddings(self, *, scope: KnowledgeTenantScope, expected: Any) -> int:
        for _attempt in range(3):
            rows = await self.client.list_nodes(
                ANCHOR, props={"scope_key": scope.scope_key}, include_vectors=True,
            )
            nodes: list[dict[str, Any]] = []
            edges: list[dict[str, Any]] = []
            expected_nodes: list[dict[str, Any]] = []
            expected_absent: list[dict[str, Any]] = []
            pools: dict[str, dict[str, Any]] = {}
            for row in rows:
                props = row["props"]
                if props.get("status") not in {"draft", "active"}:
                    continue
                if (
                    props.get("embedding_model"), props.get("embedding_revision"),
                    int(props.get("embedding_dimension") or 0),
                ) == (expected.model, expected.revision, expected.dimension):
                    continue
                nodes.append({
                    "labels": [ANCHOR, scope_label(scope.scope_key)],
                    "key": row["key"], "props": {**props, "status": "stale_embedding"},
                })
                expected_nodes.append({
                    "label": ANCHOR, "key": row["key"],
                    "props": {"status": props.get("status")},
                })
                category = str(props.get("category") or "")
                if category and category not in pools:
                    pool_node, pool_expected = await self._pool_bump(scope, category)
                    pools[category] = pool_node
                    nodes.append(pool_node)
                    expected_nodes.extend(pool_expected.get("expected_nodes", []))
                    expected_absent.extend(pool_expected.get("expected_absent", []))
            if not nodes:
                return 0
            result = await self._apply(
                f"stale-embeddings:{scope.scope_key}:{now_ms()}",
                {"expected_nodes": expected_nodes, "expected_absent": expected_absent, "upsert_nodes": nodes, "upsert_edges": edges},
            )
            if result.get("error") == "precondition_failed":
                continue
            return len([node for node in nodes if node["labels"][0] == ANCHOR])
        raise RuntimeError("stale embedding mutation precondition conflict")
