"""Persistent expert memory backed by Mem0 OSS and local Chroma."""

from __future__ import annotations

# app.config mirrors MEM0_TELEMETRY before the Mem0 package is imported.
# ruff: noqa: I001

import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, Protocol

from app.config import settings
from app.services.image_cache import image_data_url
from mem0 import Memory
from mem0.memory.utils import parse_vision_messages

MemorySource = str


_SAVED_EVENTS = frozenset({"ADD", "UPDATE"})
_AGENT_PREFIX = "expert:"

LANGUAGE_PRESERVATION_INSTRUCTIONS = """Language preservation:
- Always write extracted memories in the same language as the source message.
- Never translate memories into English unless the source message is in English.
- If a conversation contains multiple languages, preserve the language of the statement from which each memory is derived.
- Preserve domain-specific terminology in its original language."""


@dataclass(frozen=True)
class ExpertMemoryHit:
    id: str
    text: str
    source: str
    metadata: dict[str, Any]
    expert_id: str = ""
    user_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    event: str = ""


class ExpertMemoryPort(Protocol):
    async def search(
        self,
        *,
        customer_id: int,
        expert_id: str,
        query: str,
        sources: frozenset[str],
        image_sha256: str | None = None,
    ) -> list[ExpertMemoryHit]: ...

    async def list_all(
        self,
        *,
        customer_id: int,
        expert_id: str,
    ) -> list[ExpertMemoryHit]: ...

    async def list_for_customer(
        self,
        *,
        customer_id: int,
    ) -> list[ExpertMemoryHit]: ...

    async def add_chat_turn(
        self,
        *,
        customer_id: int,
        expert_id: str,
        user_message: str,
        assistant_message: str,
        source: str,
        image_sha256: str | None = None,
        session_id: str | None = None,
    ) -> list[ExpertMemoryHit]: ...

    async def add_intent(
        self,
        *,
        customer_id: int,
        expert_ids: Sequence[str],
        text: str,
        job_id: str,
    ) -> None: ...

    async def add_research_receipt(
        self,
        *,
        customer_id: int,
        expert_id: str,
        question: str,
        knowledge_question_id: str,
        source_attempt_id: str,
    ) -> None: ...

    async def replace_word_findings(
        self,
        *,
        customer_id: int,
        expert_id: str,
        doc_id: str,
        job_id: str,
        findings: Sequence[str],
    ) -> None: ...

    async def get(self, *, memory_id: str) -> ExpertMemoryHit | None: ...

    async def update(self, *, memory_id: str, text: str) -> ExpertMemoryHit: ...

    async def delete(self, *, memory_id: str) -> None: ...

    async def delete_all(
        self,
        *,
        customer_id: int,
        expert_id: str | None = None,
    ) -> None: ...


def memory_user_id(customer_id: int) -> str:
    return f"kund:{customer_id}"


def customer_id_from_memory_user(user_id: str) -> int | None:
    prefix = "kund:"
    if not user_id.startswith(prefix):
        return None
    try:
        return int(user_id[len(prefix) :])
    except ValueError:
        return None


def memory_agent_id(expert_id: str) -> str:
    cleaned = expert_id.strip()
    if not cleaned:
        raise ValueError("expert_id is required")
    return f"{_AGENT_PREFIX}{cleaned}"


def expert_id_from_agent_id(agent_id: str) -> str:
    cleaned = agent_id.strip()
    if cleaned.startswith(_AGENT_PREFIX):
        return cleaned[len(_AGENT_PREFIX) :]
    return cleaned


def _stable_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _memory_config(*, vision: bool) -> dict[str, Any]:
    llm_model = settings.mem0_vision_model if vision else settings.selected_llm_model
    llm_api_key = (
        settings.cerebras_api_key if vision else settings.selected_llm_api_key
    )
    llm_base_url = (
        settings.cerebras_base_url if vision else settings.selected_llm_base_url
    )
    llm_config: dict[str, Any] = {
        "api_key": llm_api_key,
        "model": llm_model,
        "openai_base_url": llm_base_url,
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    if vision:
        llm_config.update(
            enable_vision=True,
            vision_details=settings.mem0_vision_details,
        )
    return {
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": settings.mem0_collection_name,
                "path": settings.mem0_chroma_path,
            },
        },
        "llm": {"provider": "openai", "config": llm_config},
        "embedder": {
            "provider": "openai",
            "config": {
                "api_key": settings.openai_api_key,
                "model": settings.mem0_embedding_model,
                "openai_base_url": settings.embedding_base_url,
            },
        },
        "history_db_path": settings.mem0_history_db_path,
        "custom_instructions": LANGUAGE_PRESERVATION_INSTRUCTIONS,
    }


def _row_metadata(row: dict[str, Any]) -> dict[str, Any]:
    nested = row.get("metadata")
    if isinstance(nested, dict):
        return nested
    ignored = {"id", "memory", "score", "created_at", "updated_at", "event"}
    return {key: value for key, value in row.items() if key not in ignored}


def _expert_id_from_row(row: dict[str, Any], metadata: dict[str, Any]) -> str:
    raw = metadata.get("agent_id") or row.get("agent_id") or ""
    return expert_id_from_agent_id(str(raw))


def _user_id_from_row(row: dict[str, Any], metadata: dict[str, Any]) -> str:
    return str(row.get("user_id") or metadata.get("user_id") or "")


def memory_belongs_to(
    hit: ExpertMemoryHit,
    *,
    customer_id: int,
    expert_id: str | None = None,
) -> bool:
    actual_user = hit.user_id or str(hit.metadata.get("user_id") or "")
    if actual_user != memory_user_id(customer_id):
        return False
    if expert_id and hit.expert_id != expert_id:
        return False
    return True


def _hit_from_row(
    row: dict[str, Any],
    *,
    expert_id: str = "",
    event: str = "",
) -> ExpertMemoryHit:
    metadata = _row_metadata(row)
    return ExpertMemoryHit(
        id=str(row.get("id") or ""),
        text=str(row.get("memory") or row.get("data") or ""),
        source=str(metadata.get("source") or row.get("source") or ""),
        metadata=metadata,
        expert_id=expert_id or _expert_id_from_row(row, metadata),
        user_id=_user_id_from_row(row, metadata),
        created_at=str(row.get("created_at") or metadata.get("created_at") or ""),
        updated_at=str(row.get("updated_at") or metadata.get("updated_at") or ""),
        event=event or str(row.get("event") or ""),
    )


def _rows_from_mem0(result: object) -> list[dict[str, Any]]:
    if isinstance(result, dict):
        rows = result.get("results", [])
    elif isinstance(result, list):
        rows = result
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def _hits_from_add_result(
    result: object,
    *,
    expert_id: str,
    source: str,
) -> list[ExpertMemoryHit]:
    hits: list[ExpertMemoryHit] = []
    for row in _rows_from_mem0(result):
        event = str(row.get("event") or "").upper()
        if event and event not in _SAVED_EVENTS:
            continue
        hit = _hit_from_row(row, expert_id=expert_id, event=event)
        if not hit.text:
            continue
        if not hit.source:
            hit = ExpertMemoryHit(
                id=hit.id,
                text=hit.text,
                source=source,
                metadata=hit.metadata,
                expert_id=hit.expert_id or expert_id,
                user_id=hit.user_id,
                created_at=hit.created_at,
                updated_at=hit.updated_at,
                event=hit.event,
            )
        hits.append(hit)
    return hits


def memory_image_sha256(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    raw = metadata.get("image_sha256")
    if not isinstance(raw, str):
        return None
    digest = raw.strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        return None
    return digest


def _attach_image_sha256(
    hit: ExpertMemoryHit, image_sha256: str | None
) -> ExpertMemoryHit:
    digest = memory_image_sha256({"image_sha256": image_sha256} if image_sha256 else {})
    if not digest or memory_image_sha256(hit.metadata) == digest:
        return hit
    return ExpertMemoryHit(
        id=hit.id,
        text=hit.text,
        source=hit.source,
        metadata={**hit.metadata, "image_sha256": digest},
        expert_id=hit.expert_id,
        user_id=hit.user_id,
        created_at=hit.created_at,
        updated_at=hit.updated_at,
        event=hit.event,
    )


class ExpertMemory:
    def __init__(self, text_client: Memory, vision_client: Memory) -> None:
        self._text_client = text_client
        self._vision_client = vision_client

    @classmethod
    def from_settings(cls) -> ExpertMemory:
        return cls(
            Memory.from_config(_memory_config(vision=False)),
            Memory.from_config(_memory_config(vision=True)),
        )

    @staticmethod
    def _filters(customer_id: int, expert_id: str) -> dict[str, str]:
        return {
            "user_id": memory_user_id(customer_id),
            "agent_id": memory_agent_id(expert_id),
        }

    def _query_from_image(self, query: str, image_sha256: str) -> str:
        data_url = image_data_url(image_sha256)
        cleaned = query.strip()
        if cleaned:
            messages: list[dict[str, Any]] = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": cleaned},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ]
        else:
            messages = [
                {
                    "role": "user",
                    "content": {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                }
            ]
        described = parse_vision_messages(
            messages,
            self._vision_client.llm,
            settings.mem0_vision_details,
        )
        parts = [
            str(item.get("content") or "").strip()
            for item in described
            if isinstance(item, dict)
        ]
        return "\n".join(part for part in parts if part) or cleaned

    async def search(
        self,
        *,
        customer_id: int,
        expert_id: str,
        query: str,
        sources: frozenset[str],
        image_sha256: str | None = None,
    ) -> list[ExpertMemoryHit]:
        cleaned = query.strip()
        if image_sha256:
            cleaned = await asyncio.to_thread(
                self._query_from_image, cleaned, image_sha256
            )
        if not cleaned:
            return []
        result = await asyncio.to_thread(
            self._text_client.search,
            cleaned,
            filters=self._filters(customer_id, expert_id),
            top_k=settings.mem0_search_limit,
        )
        hits = [
            _hit_from_row(row, expert_id=expert_id) for row in _rows_from_mem0(result)
        ]
        return [hit for hit in hits if hit.text and hit.source in sources]

    async def list_all(
        self,
        *,
        customer_id: int,
        expert_id: str,
    ) -> list[ExpertMemoryHit]:
        result = await asyncio.to_thread(
            self._text_client.get_all,
            filters=self._filters(customer_id, expert_id),
            top_k=1000,
        )
        return [
            _hit_from_row(row, expert_id=expert_id) for row in _rows_from_mem0(result)
        ]

    async def list_for_customer(
        self,
        *,
        customer_id: int,
    ) -> list[ExpertMemoryHit]:
        result = await asyncio.to_thread(
            self._text_client.get_all,
            filters={"user_id": memory_user_id(customer_id)},
            top_k=1000,
        )
        return [_hit_from_row(row) for row in _rows_from_mem0(result)]

    async def add_chat_turn(
        self,
        *,
        customer_id: int,
        expert_id: str,
        user_message: str,
        assistant_message: str,
        source: str,
        image_sha256: str | None = None,
        session_id: str | None = None,
    ) -> list[ExpertMemoryHit]:
        user_content: str | list[dict[str, Any]] = user_message.strip()
        client = self._text_client
        if image_sha256:
            parts: list[dict[str, Any]] = []
            if user_message.strip():
                parts.append({"type": "text", "text": user_message.strip()})
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": image_data_url(image_sha256)},
                }
            )
            user_content = parts
            client = self._vision_client
        metadata = {
            "source": source,
            "content_hash": _stable_hash(
                [user_message, assistant_message, image_sha256]
            ),
        }
        if image_sha256:
            metadata["image_sha256"] = image_sha256
        if session_id:
            metadata["session_id"] = session_id
        result = await asyncio.to_thread(
            client.add,
            [
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": assistant_message.strip()},
            ],
            user_id=memory_user_id(customer_id),
            agent_id=memory_agent_id(expert_id),
            metadata=metadata,
            prompt=LANGUAGE_PRESERVATION_INSTRUCTIONS,
        )
        hits = [
            _attach_image_sha256(hit, image_sha256)
            for hit in _hits_from_add_result(result, expert_id=expert_id, source=source)
        ]
        if image_sha256 and not hits:
            return await self._store_image_memory(
                customer_id=customer_id,
                expert_id=expert_id,
                user_message=user_message,
                image_sha256=image_sha256,
                source=source,
                session_id=session_id,
            )
        return hits

    async def _store_image_memory(
        self,
        *,
        customer_id: int,
        expert_id: str,
        user_message: str,
        image_sha256: str,
        source: str,
        session_id: str | None,
    ) -> list[ExpertMemoryHit]:
        described = await asyncio.to_thread(
            self._query_from_image, user_message.strip(), image_sha256
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
        result = await asyncio.to_thread(
            self._vision_client.add,
            [{"role": "user", "content": described}],
            user_id=memory_user_id(customer_id),
            agent_id=memory_agent_id(expert_id),
            metadata=metadata,
            infer=False,
            prompt=LANGUAGE_PRESERVATION_INSTRUCTIONS,
        )
        return [
            _attach_image_sha256(hit, image_sha256)
            for hit in _hits_from_add_result(result, expert_id=expert_id, source=source)
        ]

    async def add_intent(
        self,
        *,
        customer_id: int,
        expert_ids: Sequence[str],
        text: str,
        job_id: str,
    ) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        content_hash = _stable_hash(cleaned)
        for expert_id in expert_ids:
            existing = await self.list_all(
                customer_id=customer_id,
                expert_id=expert_id,
            )
            if any(
                hit.source == "intent_interview"
                and hit.metadata.get("content_hash") == content_hash
                for hit in existing
            ):
                continue
            await asyncio.to_thread(
                self._text_client.add,
                [{"role": "user", "content": cleaned}],
                user_id=memory_user_id(customer_id),
                agent_id=memory_agent_id(expert_id),
                metadata={
                    "source": "intent_interview",
                    "job_id": job_id,
                    "content_hash": content_hash,
                },
                prompt=LANGUAGE_PRESERVATION_INSTRUCTIONS,
            )

    async def add_research_receipt(
        self,
        *,
        customer_id: int,
        expert_id: str,
        question: str,
        knowledge_question_id: str,
        source_attempt_id: str,
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
        await asyncio.to_thread(
            self._text_client.add,
            [{"role": "assistant", "content": cleaned}],
            user_id=memory_user_id(customer_id),
            agent_id=memory_agent_id(expert_id),
            metadata={
                "source": "research_receipt",
                "knowledge_question_id": knowledge_question_id,
                "source_attempt_id": source_attempt_id,
                "content_hash": _stable_hash(
                    [knowledge_question_id, source_attempt_id, cleaned]
                ),
            },
            infer=False,
            prompt=LANGUAGE_PRESERVATION_INSTRUCTIONS,
        )

    async def replace_word_findings(
        self,
        *,
        customer_id: int,
        expert_id: str,
        doc_id: str,
        job_id: str,
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
            hit
            for hit in await self.list_all(
                customer_id=customer_id,
                expert_id=expert_id,
            )
            if hit.source == "word_findings"
            and hit.metadata.get("doc_id") == document_id
        ]
        if existing and all(
            hit.metadata.get("content_hash") == content_hash for hit in existing
        ):
            return
        for hit in existing:
            await asyncio.to_thread(self._text_client.delete, hit.id)
        await asyncio.to_thread(
            self._text_client.add,
            [{"role": "assistant", "content": "\n".join(cleaned)}],
            user_id=memory_user_id(customer_id),
            agent_id=memory_agent_id(expert_id),
            metadata={
                "source": "word_findings",
                "doc_id": document_id,
                "job_id": job_id,
                "content_hash": content_hash,
            },
            prompt=LANGUAGE_PRESERVATION_INSTRUCTIONS,
        )

    async def get(self, *, memory_id: str) -> ExpertMemoryHit | None:
        cleaned = memory_id.strip()
        if not cleaned:
            return None
        row = await asyncio.to_thread(self._text_client.get, cleaned)
        if not isinstance(row, dict):
            return None
        return _hit_from_row(row)

    async def update(self, *, memory_id: str, text: str) -> ExpertMemoryHit:
        cleaned_id = memory_id.strip()
        cleaned_text = text.strip()
        if not cleaned_id:
            raise ValueError("memory_id is required")
        if not cleaned_text:
            raise ValueError("text is required")
        await asyncio.to_thread(self._text_client.update, cleaned_id, text=cleaned_text)
        refreshed = await self.get(memory_id=cleaned_id)
        if refreshed is None:
            return ExpertMemoryHit(id=cleaned_id, text=cleaned_text, source="", metadata={})
        if refreshed.text == cleaned_text:
            return refreshed
        return ExpertMemoryHit(
            id=refreshed.id,
            text=cleaned_text,
            source=refreshed.source,
            metadata=refreshed.metadata,
            expert_id=refreshed.expert_id,
            user_id=refreshed.user_id,
            created_at=refreshed.created_at,
            updated_at=refreshed.updated_at,
            event="UPDATE",
        )

    async def delete(self, *, memory_id: str) -> None:
        cleaned = memory_id.strip()
        if not cleaned:
            raise ValueError("memory_id is required")
        await asyncio.to_thread(self._text_client.delete, cleaned)

    async def delete_all(
        self,
        *,
        customer_id: int,
        expert_id: str | None = None,
    ) -> None:
        cleaned_expert = (expert_id or "").strip()
        kwargs: dict[str, str] = {"user_id": memory_user_id(customer_id)}
        if cleaned_expert:
            kwargs["agent_id"] = memory_agent_id(cleaned_expert)
        await asyncio.to_thread(self._text_client.delete_all, **kwargs)


ExpertMemoryFactory = Callable[[], ExpertMemoryPort]
_factory_override: ExpertMemoryFactory | None = None


@cache
def _default_memory() -> ExpertMemory:
    return ExpertMemory.from_settings()


def set_expert_memory_factory(factory: ExpertMemoryFactory | None) -> None:
    global _factory_override
    _factory_override = factory
    _default_memory.cache_clear()


def get_expert_memory() -> ExpertMemoryPort:
    if _factory_override is not None:
        return _factory_override()
    return _default_memory()
