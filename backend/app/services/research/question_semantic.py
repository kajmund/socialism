"""Semantic KnowledgeQuestion identity matching in the shared vector index."""

from __future__ import annotations

from collections.abc import Sequence

from app.services.knowledge.embeddings import EmbeddingProvider
from app.services.knowledge.models import (
    EmbeddedKnowledgeChunk,
    EmbeddedKnowledgeQuery,
    KnowledgeChunk,
    KnowledgeQuery,
    KnowledgeScope,
)
from app.services.knowledge.vector_store import KnowledgeVectorStore
from app.services.research.knowledge_question import (
    EmbeddingMetadata,
    KnowledgeQuestion,
)

QUESTION_VECTOR_KIND = "knowledge_question"
QUESTION_VECTOR_CUSTOMER_ID = -1


class SemanticQuestionIdentityMatcher:
    def __init__(
        self,
        *,
        vector_store: KnowledgeVectorStore,
        embeddings: EmbeddingProvider,
        version: str,
        threshold: float,
        limit: int,
    ) -> None:
        if not version.strip():
            raise ValueError("KnowledgeQuestion embedding version is required")
        if threshold < 0.0 or threshold > 1.0:
            raise ValueError("KnowledgeQuestion semantic threshold must be between 0 and 1")
        if limit < 1:
            raise ValueError("KnowledgeQuestion semantic limit must be >= 1")
        self._vector_store = vector_store
        self._embeddings = embeddings
        self._version = version.strip()
        self._threshold = threshold
        self._limit = limit

    @property
    def embedding_metadata(self) -> EmbeddingMetadata:
        return (self._embeddings.model, self._version, self._embeddings.dimension)

    async def index(self, candidates: Sequence[KnowledgeQuestion]) -> None:
        pending = [
            question
            for question in candidates
            if (
                question.embedding_model,
                question.embedding_version,
                question.embedding_dimension,
            )
            != self.embedding_metadata
        ]
        if not pending:
            return
        vectors = await self._embeddings.embed([question.normalized_text for question in pending])
        if len(vectors) != len(pending):
            raise RuntimeError(
                "EmbeddingProvider returned an unexpected KnowledgeQuestion vector count"
            )
        await self._vector_store.upsert_chunks(
            [
                EmbeddedKnowledgeChunk(
                    chunk=_question_chunk(question),
                    embedding=vector,
                )
                for question, vector in zip(pending, vectors, strict=True)
            ]
        )

    async def match(
        self,
        *,
        normalized_text: str,
        identity_key: str,
        candidates: Sequence[KnowledgeQuestion],
    ) -> KnowledgeQuestion | None:
        del identity_key
        if not candidates:
            return None
        namespaces = {question.scope.namespace for question in candidates}
        if len(namespaces) != 1:
            raise ValueError("Semantic KnowledgeQuestion candidates must share a namespace")
        await self.index(candidates)
        vectors = await self._embeddings.embed([normalized_text])
        if len(vectors) != 1:
            raise RuntimeError("EmbeddingProvider returned an unexpected query vector count")
        sample = candidates[0]
        hits = await self._vector_store.search(
            EmbeddedKnowledgeQuery(
                query=KnowledgeQuery(
                    query=normalized_text,
                    scope=KnowledgeScope(customer_id=QUESTION_VECTOR_CUSTOMER_ID),
                    limit=self._limit,
                    filters={
                        "knowledge_kind": QUESTION_VECTOR_KIND,
                        "namespace": sample.scope.namespace,
                    },
                ),
                embedding=vectors[0],
            )
        )
        by_id = {question.id: question for question in candidates}
        for hit in hits:
            question_id = hit.metadata.get("knowledge_question_id")
            if (
                isinstance(question_id, str)
                and question_id in by_id
                and hit.score is not None
                and hit.score >= self._threshold
            ):
                return by_id[question_id]
        return None


def _question_chunk(question: KnowledgeQuestion) -> KnowledgeChunk:
    return KnowledgeChunk(
        document_id=f"knowledge-question:{question.id}",
        chunk_id="question",
        text=question.normalized_text,
        customer_id=QUESTION_VECTOR_CUSTOMER_ID,
        case_id=None,
        module=None,
        title=question.display_text,
        provider=QUESTION_VECTOR_KIND,
        version=question.embedding_version,
        metadata={
            "knowledge_kind": QUESTION_VECTOR_KIND,
            "knowledge_question_id": question.id,
            "namespace": question.scope.namespace,
        },
    )
