"""Test-only FastAPI entrypoint for the two-process Overgraph owner check.

The real app is served by uvicorn, with only truly external boundaries replaced:
OpenAI embeddings and object storage. The Overgraph owner is a separate OS
process reached through the normal owner socket.

Environment:
  OWNER_TEST_STORAGE_DIR   shared filesystem object store (defaults to in-process memory)
  OWNER_TEST_GUARD_FILE    append a line if a direct Catalog write is attempted
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.object_storage import (
    MemoryObjectStorage,
    ObjectStorageError,
    set_object_storage,
)


class FileObjectStorage:
    """Shared across test backend processes; the real adapter is Supabase S3."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: str, key: str) -> Path:
        safe = Path(*[part for part in key.split("/") if part not in {"", ".", ".."}])
        target = (self.root / bucket / safe).resolve()
        if self.root.resolve() not in target.parents:
            raise ObjectStorageError("object key escapes the test store")
        return target

    def ensure_bucket(self, name: str) -> None:
        (self.root / name).mkdir(parents=True, exist_ok=True)

    def put_object(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        target = self._path(bucket, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get_object(self, bucket: str, key: str) -> tuple[bytes, str]:
        target = self._path(bucket, key)
        try:
            return target.read_bytes(), "application/octet-stream"
        except FileNotFoundError as exc:
            raise ObjectStorageError(f"Object not found: {bucket}/{key}") from exc

    def delete_object(self, bucket: str, key: str) -> None:
        self._path(bucket, key).unlink(missing_ok=True)


_storage_dir = os.environ.get("OWNER_TEST_STORAGE_DIR", "").strip()
if _storage_dir:
    set_object_storage(FileObjectStorage(Path(_storage_dir)))
else:
    set_object_storage(MemoryObjectStorage())

from app.services.knowledge.embeddings import OpenAIEmbeddingProvider  # noqa: E402


class _FakeEmbeddings:
    provider_id = "test"
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large")
    dimension = int(os.environ.get("EMBEDDING_DIMENSION", "3072"))

    async def embed(self, texts):
        # Deterministic and distinct per text so vector writes are observable.
        return [
            [float(len(text) % 97) / 97.0] * self.dimension
            for text in texts
        ]


def _fake_from_settings(cls, *, client=None):
    return _FakeEmbeddings()


OpenAIEmbeddingProvider.from_settings = classmethod(_fake_from_settings)

from app.main import app  # noqa: E402
import app.main as app_module  # noqa: E402
import app.services.overgraph.catalogs as catalogs_module  # noqa: E402
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore  # noqa: E402
from app.services.overgraph.catalogs import Catalog  # noqa: E402
from app.services.research.composition import (  # noqa: E402
    set_knowledge_vector_store_factory,
)

_store = MemoryKnowledgeVectorStore()
set_knowledge_vector_store_factory(lambda: _store)

_guard_file = os.environ.get("OWNER_TEST_GUARD_FILE", "").strip()
if _guard_file:

    def _record(message: str) -> None:
        Path(_guard_file).open("a", encoding="utf-8").write(f"{os.getpid()} {message}\n")

    _real_open_catalog = catalogs_module.open_catalog

    def _guarded_open_catalog(path, *, kind, dimension):
        if os.environ.get("OWNER_TEST_NO_LOCAL_KNOWLEDGE") == "1" and kind == "knowledge":
            _record(f"LOCAL_KNOWLEDGE_OPEN {path}")
        return _real_open_catalog(path, kind=kind, dimension=dimension)

    catalogs_module.open_catalog = _guarded_open_catalog
    _real_open_runtime = catalogs_module.open_runtime

    def _guarded_open_runtime(root, *, knowledge_dimension, memory_dimension):
        if os.environ.get("OWNER_TEST_NO_LOCAL_KNOWLEDGE") == "1":
            _record(f"LOCAL_KNOWLEDGE_RUNTIME_OPEN {root}")
        return _real_open_runtime(
            root, knowledge_dimension=knowledge_dimension,
            memory_dimension=memory_dimension,
        )

    catalogs_module.open_runtime = _guarded_open_runtime
    app_module.open_runtime = _guarded_open_runtime

    def _guard(method: str):
        def fail(*_args, **_kwargs):
            Path(_guard_file).open("a", encoding="utf-8").write(f"{os.getpid()} {method}\n")
            raise RuntimeError(
                f"test backend attempted a direct Catalog write: {method}"
            )

        return fail

    for _method in (
        "upsert_node", "upsert_edge", "delete_node", "graph_patch",
        "batch_upsert_nodes", "begin_write_txn",
    ):
        setattr(Catalog, _method, _guard(_method))

from fastapi import Request  # noqa: E402


@app.post("/__owner_test__/publish-answer")
async def _test_publish_answer(request: Request) -> dict:
    from app.database.knowledge_scope import customer_scope
    from app.services.overgraph.owner_facts import publish_answer_via_owner
    from app.services.overgraph.owner_runtime import get_owner_runtime
    from app.services.overgraph.publish import AnswerPublish

    body = await request.json()
    published = AnswerPublish(
        question_id=str(body["question_id"]),
        question_text=str(body["question_text"]),
        scope=customer_scope(int(body["customer_id"])),
        identity=str(body["identity"]),
        evidence_set_id=str(body["evidence_set_id"]),
        attributes=dict(body["attributes"]),
        basis=list(body["basis"]),
        assessment=dict(body.get("assessment") or {"sufficient": True}),
        dependency_ids=(),
    )
    fact_id = await publish_answer_via_owner(
        get_owner_runtime().require_client(), published,
    )
    return {"fact_id": fact_id}


@app.post("/__owner_test__/seed-retrieval")
async def _test_seed_retrieval(request: Request) -> dict:
    from app.database.knowledge_scope import customer_scope
    from app.services.graph_v2.types import FactInput, NodeInput, SourceRef
    from app.services.overgraph.labels import ENTITY, scope_label
    from app.services.overgraph.owner_facts import write_fact_via_owner
    from app.services.overgraph.owner_runtime import get_owner_runtime
    from app.services.overgraph.research import INDEX_PREFIX
    from app.services.overgraph.write import entity_key

    body = await request.json()
    scope = customer_scope(1)
    source = NodeInput(node_type="legal.source", name="Källa", scope=scope)
    target = NodeInput(node_type="legal.issue", name="Fråga", scope=scope)
    client = get_owner_runtime().require_client()
    result = await write_fact_via_owner(
        client,
        FactInput(
            source_id=entity_key(source),
            target_id=entity_key(target),
            scope=scope,
            predicate="legal.rule",
            fact_text=str(body["text"]),
            sources=(SourceRef("episode", str(body["key"])),),
            embedding=tuple(float(value) for value in body["vector"]),
            occurrence_key=str(body["key"]),
        ),
        entities=(source, target),
    )
    await client.mutate(f"test-index-{body['key']}", {"upsert_nodes": [{
        "labels": [ENTITY, scope_label(scope.scope_key)],
        "key": f"{INDEX_PREFIX}{scope.scope_key}",
        "props": {
            "scope_key": scope.scope_key, "node_type": "research.index",
            "name": "index", "has_text_unit_facts": 1,
        },
    }]}, kind="batch")
    return {"fact_id": result["key"]}


@app.post("/__owner_test__/lookup-candidates")
async def _test_lookup_candidates(request: Request) -> dict:
    from app.services.overgraph.research import lookup_candidates

    body = await request.json()
    hits = await lookup_candidates(
        customer_id=1, question_id=None,
        dense_query=[float(value) for value in body["vector"]], bound=10,
    )
    return {"facts": [{"id": hit.fact.id, "score": hit.score} for hit in hits]}


@app.post("/__owner_test__/lookup-answers")
async def _test_lookup_answers(request: Request) -> dict:
    from app.database.session import SessionLocal
    from app.services.knowledge.models import KnowledgeScope
    from app.services.research.answer_graph import lookup_answers
    from app.services.research.models import ResearchContext, ResearchNeed

    body = await request.json()
    need = ResearchNeed(
        id=str(body["need_id"]),
        question=str(body["question"]),
        why_needed="test reuse",
        source_types=["document"],
        knowledge_question_id=str(body["question_id"]),
    )
    context = ResearchContext(
        scope=KnowledgeScope(
            customer_id=int(body["customer_id"]), module=body.get("module"),
        ),
        limit=10,
    )
    async with SessionLocal() as session:
        found = await lookup_answers(session, need=need, context=context, now=now())
    return {
        "evidence": [
            {
                "evidence_id": item.evidence_id,
                "source_id": item.source_id,
                "metadata": dict(item.metadata),
            }
            for item in found
        ]
    }


def now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(sys.argv[1]),
        log_level="warning",
    )
