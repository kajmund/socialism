"""Async expert-memory port backed by the Memory Owner (mem0 only extracts)."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from app.config import EMBEDDING_MODEL_DIMENSIONS, settings
from app.services.expertgranskning.memory import (
    LANGUAGE_PRESERVATION_INSTRUCTIONS,
    ExpertMemoryHit,
    _attach_image_sha256,
    _hit_from_row,
    _hits_from_add_result,
    _stable_hash,
    memory_agent_id,
    memory_user_id,
)
from app.services.expertgranskning.memory_staging import (
    StagedHit,
    begin,
    end,
    install_mem0_staging,
    root,
)
from app.services.knowledge.embeddings import OpenAIEmbeddingProvider
from app.services.overgraph.labels import MEMORY, MEMORY_ENTITY
from app.services.overgraph.owner_memory import (
    MemoryRecord,
    apply_changes,
    delete as delete_memory,
    get as get_memory,
    list_records,
    search as search_memory,
    update as update_memory,
)
from app.services.overgraph.owner_registry import memory_owner_client

TOP_K = 1000


class OwnerExpertMemory:
    def __init__(
        self,
        *,
        client_factory=memory_owner_client,
        embedder: Any | None = None,
        text_client: Any | None = None,
        vision_client: Any | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._embedder = embedder or OpenAIEmbeddingProvider(
            model=settings.mem0_embedding_model,
            dimension=EMBEDDING_MODEL_DIMENSIONS[settings.mem0_embedding_model],
        )
        self._text_client = text_client
        self._vision_client = vision_client

    def close(self) -> None:
        return None

    def _filters(self, customer_id: int, expert_id: str) -> dict[str, str]:
        return {
            "user_id": memory_user_id(customer_id),
            "agent_id": memory_agent_id(expert_id),
        }

    def _mem0_clients(self) -> tuple[Any, Any]:
        if self._text_client is None or self._vision_client is None:
            from mem0 import Memory

            from app.services.expertgranskning.memory import _memory_config

            install_mem0_staging()
            self._text_client = Memory.from_config(_staging_config(_memory_config(vision=False)))
            self._vision_client = Memory.from_config(_staging_config(_memory_config(vision=True)))
        return self._text_client, self._vision_client

    async def search(
        self, *, customer_id: int, expert_id: str, query: str,
        sources: frozenset[str], image_sha256: str | None = None,
    ) -> list[ExpertMemoryHit]:
        cleaned = query.strip()
        if image_sha256:
            text_client, vision_client = self._mem0_clients()
            del text_client
            cleaned = await asyncio.to_thread(
                _describe_image, vision_client, cleaned, image_sha256,
            )
        if not cleaned:
            return []
        vectors = await self._embedder.embed([cleaned])
        records = await search_memory(
            self._client_factory(), kind=MEMORY, vector=list(vectors[0]),
            top_k=settings.mem0_search_limit,
            filters=self._filters(customer_id, expert_id),
        )
        hits = [_owner_hit(record, expert_id=expert_id) for record in records]
        return [hit for hit in hits if hit.text and hit.source in sources]

    async def list_all(self, *, customer_id: int, expert_id: str) -> list[ExpertMemoryHit]:
        records = await list_records(
            self._client_factory(), kind=MEMORY,
            filters=self._filters(customer_id, expert_id), limit=TOP_K,
        )
        return [_owner_hit(record, expert_id=expert_id) for record in records]

    async def list_for_customer(self, *, customer_id: int) -> list[ExpertMemoryHit]:
        records = await list_records(
            self._client_factory(), kind=MEMORY,
            filters={"user_id": memory_user_id(customer_id)}, limit=TOP_K,
        )
        return [_owner_hit(record) for record in records]

    async def get(self, *, memory_id: str) -> ExpertMemoryHit | None:
        cleaned = memory_id.strip()
        if not cleaned:
            return None
        record = await get_memory(self._client_factory(), MEMORY, cleaned)
        return None if record is None else _owner_hit(record)

    async def update(self, *, memory_id: str, text: str) -> ExpertMemoryHit:
        cleaned_id = memory_id.strip()
        cleaned_text = text.strip()
        if not cleaned_id:
            raise ValueError("memory_id is required")
        if not cleaned_text:
            raise ValueError("text is required")
        client = self._client_factory()
        vectors = await self._embedder.embed([cleaned_text])
        await update_memory(
            client, kind=MEMORY, memory_id=cleaned_id, vector=list(vectors[0]),
            payload={"data": cleaned_text, "updated_at": _now()},
            collection=settings.mem0_collection_name,
        )
        refreshed = await self.get(memory_id=cleaned_id)
        if refreshed is None:
            return ExpertMemoryHit(id=cleaned_id, text=cleaned_text, source="", metadata={})
        if refreshed.text == cleaned_text:
            return refreshed
        return ExpertMemoryHit(
            id=refreshed.id, text=cleaned_text, source=refreshed.source,
            metadata=refreshed.metadata, expert_id=refreshed.expert_id,
            user_id=refreshed.user_id, created_at=refreshed.created_at,
            updated_at=refreshed.updated_at, event="UPDATE",
        )

    async def delete(self, *, memory_id: str) -> None:
        cleaned = memory_id.strip()
        if not cleaned:
            raise ValueError("memory_id is required")
        await delete_memory(self._client_factory(), MEMORY, cleaned)

    async def delete_all(self, *, customer_id: int, expert_id: str | None = None) -> None:
        filters = {"user_id": memory_user_id(customer_id)}
        cleaned_expert = (expert_id or "").strip()
        if cleaned_expert:
            filters["agent_id"] = memory_agent_id(cleaned_expert)
        records = await list_records(
            self._client_factory(), kind=MEMORY, filters=filters, limit=TOP_K,
        )
        if records:
            await apply_changes(
                self._client_factory(), kind=MEMORY,
                collection=settings.mem0_collection_name,
                upserts=[], deletes=[record.id for record in records],
            )

    async def add_chat_turn(
        self, *, customer_id: int, expert_id: str, user_message: str,
        assistant_message: str, source: str, image_sha256: str | None = None,
        session_id: str | None = None,
    ) -> list[ExpertMemoryHit]:
        metadata = {
            "source": source,
            "content_hash": _stable_hash([user_message, assistant_message, image_sha256]),
        }
        if image_sha256:
            metadata["image_sha256"] = image_sha256
        if session_id:
            metadata["session_id"] = session_id
        user_content: str | list[dict[str, Any]] = user_message.strip()
        if image_sha256:
            from app.services.image_cache import image_data_url

            parts: list[dict[str, Any]] = []
            if user_message.strip():
                parts.append({"type": "text", "text": user_message.strip()})
            parts.append({"type": "image_url", "image_url": {"url": image_data_url(image_sha256)}})
            user_content = parts
        result = await self._run_add(
            customer_id=customer_id, expert_id=expert_id, vision=image_sha256 is not None,
            messages=[
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_message.strip()},
            ],
            metadata=metadata, infer=True,
        )
        hits = [
            _attach_image_sha256(hit, image_sha256)
            for hit in _hits_from_add_result(result, expert_id=expert_id, source=source)
        ]
        if image_sha256 and not hits:
            return await self._store_image_memory(
                customer_id=customer_id, expert_id=expert_id,
                user_message=user_message, image_sha256=image_sha256,
                source=source, session_id=session_id,
            )
        return hits

    async def _store_image_memory(
        self, *, customer_id: int, expert_id: str, user_message: str,
        image_sha256: str, source: str, session_id: str | None,
    ) -> list[ExpertMemoryHit]:
        _text, vision = self._mem0_clients()
        described = await asyncio.to_thread(
            _describe_image, vision, user_message.strip(), image_sha256,
        )
        if not described:
            raise ValueError("Mem0 vision returned an empty image description")
        metadata = {
            "source": source,
            "content_hash": _stable_hash([user_message, described, image_sha256]),
            "image_sha256": image_sha256,
        }
        if session_id:
            metadata["session_id"] = session_id
        result = await self._run_add(
            customer_id=customer_id, expert_id=expert_id, vision=True,
            messages=[{"role": "user", "content": described}],
            metadata=metadata, infer=False,
        )
        return [
            _attach_image_sha256(hit, image_sha256)
            for hit in _hits_from_add_result(result, expert_id=expert_id, source=source)
        ]

    async def add_intent(
        self, *, customer_id: int, expert_ids: Sequence[str], text: str, job_id: str,
    ) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        content_hash = _stable_hash(cleaned)
        for expert_id in expert_ids:
            existing = await self.list_all(customer_id=customer_id, expert_id=expert_id)
            if any(
                hit.source == "intent_interview"
                and hit.metadata.get("content_hash") == content_hash
                for hit in existing
            ):
                continue
            await self._run_add(
                customer_id=customer_id, expert_id=expert_id, vision=False,
                messages=[{"role": "user", "content": cleaned}],
                metadata={
                    "source": "intent_interview", "job_id": job_id,
                    "content_hash": content_hash,
                },
                infer=False,
            )

    async def add_research_receipt(
        self, *, customer_id: int, expert_id: str, question: str,
        knowledge_question_id: str, source_attempt_id: str,
    ) -> None:
        cleaned = question.strip()
        if not cleaned:
            raise ValueError("question is required for a research receipt")
        existing = await self.list_all(customer_id=customer_id, expert_id=expert_id)
        if any(
            hit.source == "research_receipt"
            and hit.metadata.get("knowledge_question_id") == knowledge_question_id
            and hit.metadata.get("source_attempt_id") == source_attempt_id
            for hit in existing
        ):
            return
        await self._run_add(
            customer_id=customer_id, expert_id=expert_id, vision=False,
            messages=[{"role": "assistant", "content": cleaned}],
            metadata={
                "source": "research_receipt",
                "knowledge_question_id": knowledge_question_id,
                "source_attempt_id": source_attempt_id,
                "content_hash": _stable_hash(
                    [knowledge_question_id, source_attempt_id, cleaned]
                ),
            },
            infer=False,
        )

    async def replace_word_findings(
        self, *, customer_id: int, expert_id: str, doc_id: str, job_id: str,
        findings: Sequence[str],
    ) -> None:
        document_id = doc_id.strip()
        if not document_id:
            raise ValueError("doc_id is required for word_findings deduplication")
        cleaned = [finding.strip() for finding in findings if finding.strip()]
        if not cleaned:
            return
        content_hash = _stable_hash(cleaned)
        existing = [
            hit for hit in await self.list_all(customer_id=customer_id, expert_id=expert_id)
            if hit.source == "word_findings" and hit.metadata.get("doc_id") == document_id
        ]
        if existing and all(
            hit.metadata.get("content_hash") == content_hash for hit in existing
        ):
            return
        await self._run_add(
            customer_id=customer_id, expert_id=expert_id, vision=False,
            messages=[{"role": "assistant", "content": "\n".join(cleaned)}],
            metadata={
                "source": "word_findings", "doc_id": document_id,
                "job_id": job_id, "content_hash": content_hash,
            },
            infer=True,
            delete_before=[hit.id for hit in existing],
        )

    async def _run_add(
        self, *, customer_id: int, expert_id: str, vision: bool,
        messages: list[dict[str, Any]], metadata: dict[str, Any], infer: bool,
        delete_before: list[str] | None = None,
    ) -> object:
        client = self._client_factory()
        seed = await self._snapshot(client, customer_id=customer_id, expert_id=expert_id)
        before = {collection: dict(items) for collection, items in seed.items()}
        token = begin(seed)
        try:
            for memory_id in delete_before or ():
                seed[settings.mem0_collection_name].pop(memory_id, None)
            text, vision_client = self._mem0_clients()
            result = await asyncio.to_thread(
                (vision_client if vision else text).add,
                messages,
                user_id=memory_user_id(customer_id),
                agent_id=memory_agent_id(expert_id),
                metadata=metadata,
                infer=infer,
                prompt=LANGUAGE_PRESERVATION_INSTRUCTIONS,
            )
            await self._flush(
                client, before, customer_id=customer_id, expert_id=expert_id,
            )
        finally:
            end(token)
        return result

    async def _snapshot(
        self, client, *, customer_id: int, expert_id: str,
    ) -> dict[str, dict[str, StagedHit]]:
        filters = self._filters(customer_id, expert_id)
        seed: dict[str, dict[str, StagedHit]] = {}
        for kind, collection in (
            (MEMORY, settings.mem0_collection_name),
            (MEMORY_ENTITY, f"{settings.mem0_collection_name}_entities"),
        ):
            records = await list_records(
                client, kind=kind, filters=filters, limit=TOP_K, include_vectors=True,
            )
            seed[collection] = {
                record.id: StagedHit(
                    id=record.id, score=None, payload=record.payload,
                    vector=record.vector or (),
                )
                for record in records
            }
        return seed

    async def _flush(
        self, client, seed: dict[str, dict[str, StagedHit]], *,
        customer_id: int, expert_id: str,
    ) -> None:
        del customer_id, expert_id
        for collection, before in seed.items():
            current = root().get(collection, {})
            upserts = [
                MemoryRecord(
                    id=hit.id, score=None, payload=hit.payload, vector=hit.vector,
                )
                for memory_id, hit in current.items()
                if before.get(memory_id) != hit
            ]
            deletes = [memory_id for memory_id in before if memory_id not in current]
            kind = MEMORY_ENTITY if collection.endswith("_entities") else MEMORY
            await apply_changes(
                client, kind=kind, collection=collection,
                upserts=upserts, deletes=deletes,
            )


def _describe_image(vision_client: Any, query: str, image_sha256: str) -> str:
    from mem0.memory.utils import parse_vision_messages

    from app.services.image_cache import image_data_url

    messages: list[dict[str, Any]] = []
    if query.strip():
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": query.strip()},
                {"type": "image_url", "image_url": {"url": image_data_url(image_sha256)}},
            ],
        })
    else:
        messages.append({
            "role": "user",
            "content": {
                "type": "image_url", "image_url": {"url": image_data_url(image_sha256)},
            },
        })
    described = parse_vision_messages(
        messages, vision_client.llm, settings.mem0_vision_details,
    )
    parts = [
        str(item.get("content") or "").strip()
        for item in described if isinstance(item, dict)
    ]
    return "\n".join(part for part in parts if part) or query.strip()


def _owner_hit(record: MemoryRecord, *, expert_id: str = "") -> ExpertMemoryHit:
    row = {"id": record.id, "memory": record.payload.get("data"), **record.payload}
    return _hit_from_row(row, expert_id=expert_id)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _staging_config(config: dict[str, Any]) -> dict[str, Any]:
    vector = dict(config["vector_store"])
    vector["provider"] = "overgraph_staging"
    vector["config"] = {
        **dict(vector.get("config") or {}),
        "collection_name": settings.mem0_collection_name,
        "embedding_model_dims": EMBEDDING_MODEL_DIMENSIONS[settings.mem0_embedding_model],
    }
    config["vector_store"] = vector
    return config
