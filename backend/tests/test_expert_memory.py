from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.database.models import Persona
from app.services.dd.expert_keys import expert_role_key
from app.services.expertgranskning.memory import (
    LANGUAGE_PRESERVATION_INSTRUCTIONS,
    ExpertMemory,
    ExpertMemoryHit,
    MEM0_PGVECTOR_MAXCONN,
    MEM0_PGVECTOR_MINCONN,
    _default_memory,
    _memory_config,
    close_default_expert_memory,
    memory_belongs_to,
    memory_image_sha256,
    memory_user_id,
    set_expert_memory_factory,
)
from app.services.expertgranskning.memory_view import serialize_memory_hit
from app.services.persona_chat import expert_memory_context
from app.services.prompt_catalog import default_prompts


class ListingMemory:
    def __init__(self, hits: list[ExpertMemoryHit]) -> None:
        self.hits = hits

    async def search(self, **_kwargs) -> list[ExpertMemoryHit]:
        return []

    async def list_all(self, **kwargs) -> list[ExpertMemoryHit]:
        expert_id = kwargs["expert_id"]
        return [hit for hit in self.hits if hit.expert_id == expert_id]

    async def list_for_customer(self, **_kwargs) -> list[ExpertMemoryHit]:
        return list(self.hits)

    async def add_chat_turn(self, **_kwargs) -> list[ExpertMemoryHit]:
        return []

    async def add_intent(self, **_kwargs) -> None:
        return None

    async def replace_word_findings(self, **_kwargs) -> None:
        return None

    async def get(self, **kwargs) -> ExpertMemoryHit | None:
        memory_id = kwargs["memory_id"]
        return next((hit for hit in self.hits if hit.id == memory_id), None)

    async def update(self, **kwargs) -> ExpertMemoryHit:
        memory_id = kwargs["memory_id"]
        text = kwargs["text"]
        updated = []
        found = None
        for hit in self.hits:
            if hit.id != memory_id:
                updated.append(hit)
                continue
            found = ExpertMemoryHit(
                id=hit.id,
                text=text,
                source=hit.source,
                metadata=hit.metadata,
                expert_id=hit.expert_id,
                user_id=hit.user_id,
                created_at=hit.created_at,
                updated_at=hit.updated_at,
                event="UPDATE",
            )
            updated.append(found)
        if found is None:
            raise ValueError(f"Memory with id {memory_id} not found")
        self.hits = updated
        return found

    async def delete(self, **kwargs) -> None:
        memory_id = kwargs["memory_id"]
        remaining = [hit for hit in self.hits if hit.id != memory_id]
        if len(remaining) == len(self.hits):
            raise ValueError(f"Memory with id {memory_id} not found")
        self.hits = remaining

    async def delete_all(self, **kwargs) -> None:
        customer_id = kwargs["customer_id"]
        expert_id = kwargs.get("expert_id")
        expected_user = memory_user_id(customer_id)
        remaining: list[ExpertMemoryHit] = []
        for hit in self.hits:
            if hit.user_id and hit.user_id != expected_user:
                remaining.append(hit)
                continue
            if expert_id and hit.expert_id != expert_id:
                remaining.append(hit)
                continue
        self.hits = remaining


class _DescribeLlm:
    def __init__(self, text: str = "rising chart") -> None:
        self.text = text
        self.calls: list[object] = []

    def generate_response(self, messages=None, **_kwargs) -> str:
        self.calls.append(messages)
        return self.text


class FakeMem0Client:
    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        add_result: dict[str, object] | None = None,
        vision_description: str = "rising chart",
    ) -> None:
        self.rows = rows or []
        self.add_result = add_result
        self.adds: list[tuple[object, dict[str, Any]]] = []
        self.deletes: list[str] = []
        self.delete_alls: list[dict[str, Any]] = []
        self.searches: list[str] = []
        self.events: list[str] = []
        self.llm = _DescribeLlm(vision_description)

    def search(self, _query: str, **_kwargs) -> dict[str, object]:
        if not str(_query).strip():
            raise ValueError("Invalid query: cannot be empty or whitespace-only.")
        self.searches.append(_query)
        return {"results": self.rows}

    def get_all(self, **_kwargs) -> dict[str, object]:
        return {"results": self.rows}

    def add(self, messages: object, **kwargs) -> dict[str, object]:
        self.events.append("add")
        self.adds.append((messages, kwargs))
        if kwargs.get("infer") is False:
            content = ""
            if isinstance(messages, list) and messages:
                raw = messages[0].get("content") if isinstance(messages[0], dict) else ""
                content = raw if isinstance(raw, str) else "image"
            return {
                "results": [
                    {
                        "id": "img-memory",
                        "memory": content,
                        "event": "ADD",
                        "metadata": dict(kwargs.get("metadata") or {}),
                    }
                ]
            }
        if self.add_result is not None:
            return self.add_result
        return {"results": []}

    def delete(self, memory_id: str) -> None:
        self.events.append("delete")
        self.deletes.append(memory_id)
        self.rows = [row for row in self.rows if str(row.get("id")) != memory_id]

    def get(self, memory_id: str) -> dict[str, Any] | None:
        return next((row for row in self.rows if str(row.get("id")) == memory_id), None)

    def update(self, memory_id: str, text: str | None = None, **_kwargs) -> dict[str, str]:
        for row in self.rows:
            if str(row.get("id")) != memory_id:
                continue
            if text is not None:
                row["memory"] = text
            return {"message": "Memory updated successfully!"}
        raise ValueError(f"Memory with id {memory_id} not found")

    def delete_all(self, **kwargs) -> dict[str, str]:
        self.delete_alls.append(kwargs)
        user_id = kwargs.get("user_id")
        agent_id = kwargs.get("agent_id")
        remaining = []
        for row in self.rows:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            row_user = str(row.get("user_id") or metadata.get("user_id") or "")
            row_agent = str(row.get("agent_id") or metadata.get("agent_id") or "")
            if user_id and row_user and row_user != user_id:
                remaining.append(row)
                continue
            if agent_id and row_agent and row_agent != agent_id:
                remaining.append(row)
                continue
        self.rows = remaining
        return {"message": "Memories deleted successfully!"}


@pytest.mark.asyncio
async def test_word_findings_replace_existing_document_memories():
    text = FakeMem0Client(
        [
            {
                "id": "old",
                "memory": "old finding",
                "metadata": {
                    "source": "word_findings",
                    "doc_id": "doc-1",
                    "content_hash": "old-hash",
                },
            },
            {
                "id": "other-doc",
                "memory": "keep",
                "metadata": {
                    "source": "word_findings",
                    "doc_id": "doc-2",
                },
            },
        ]
    )
    memory = ExpertMemory(text, FakeMem0Client())  # type: ignore[arg-type]

    await memory.replace_word_findings(
        customer_id=1,
        expert_id="legal",
        doc_id="doc-1",
        job_id="job-2",
        findings=["Klargör ansvarsfördelningen."],
    )

    assert text.deletes == ["old"]
    assert len(text.adds) == 1
    assert text.events == ["add", "delete"]
    _messages, kwargs = text.adds[0]
    assert kwargs["metadata"]["doc_id"] == "doc-1"
    assert kwargs["metadata"]["source"] == "word_findings"
    assert kwargs["prompt"] == LANGUAGE_PRESERVATION_INSTRUCTIONS


@pytest.mark.asyncio
async def test_word_findings_preserves_existing_when_add_fails():
    text = FakeMem0Client(
        [
            {
                "id": "old",
                "memory": "old finding",
                "metadata": {
                    "source": "word_findings",
                    "doc_id": "doc-1",
                    "content_hash": "old-hash",
                },
            }
        ]
    )

    class FailOnAddClient(FakeMem0Client):
        def add(self, *args, **kwargs):
            raise RuntimeError("embedding unavailable")

    failing = FailOnAddClient(text.rows)
    memory = ExpertMemory(failing, FakeMem0Client())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="embedding unavailable"):
        await memory.replace_word_findings(
            customer_id=1,
            expert_id="legal",
            doc_id="doc-1",
            job_id="job-2",
            findings=["Ny slutsats."],
        )

    assert failing.deletes == []
    assert failing.rows[0]["id"] == "old"


@pytest.mark.asyncio
async def test_word_findings_skip_unchanged_content():
    text = FakeMem0Client()
    memory = ExpertMemory(text, FakeMem0Client())  # type: ignore[arg-type]
    await memory.replace_word_findings(
        customer_id=1,
        expert_id="legal",
        doc_id="doc-1",
        job_id="job-1",
        findings=["Samma slutsats."],
    )
    content_hash = text.adds[0][1]["metadata"]["content_hash"]
    text.adds.clear()
    text.rows = [
        {
            "id": "current",
            "memory": "Samma slutsats.",
            "metadata": {
                "source": "word_findings",
                "doc_id": "doc-1",
                "content_hash": content_hash,
            },
        }
    ]

    await memory.replace_word_findings(
        customer_id=1,
        expert_id="legal",
        doc_id="doc-1",
        job_id="job-2",
        findings=["Samma slutsats."],
    )

    assert text.adds == []
    assert text.deletes == []


@pytest.mark.asyncio
async def test_image_chat_turn_uses_vision_client(monkeypatch):
    text = FakeMem0Client()
    vision = FakeMem0Client()
    memory = ExpertMemory(text, vision)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "app.services.expertgranskning.memory.image_data_url",
        lambda digest: f"data:image/png;base64,{digest}",
    )

    await memory.add_chat_turn(
        customer_id=1,
        expert_id="visual",
        user_message="Vad visar diagrammet?",
        assistant_message="Det visar en stigande trend.",
        source="persona_chat",
        image_sha256="a" * 64,
    )

    assert text.adds == []
    messages, kwargs = vision.adds[0]
    assert messages[0]["content"][1]["image_url"]["url"].startswith(
        "data:image/png;base64,"
    )
    assert kwargs["metadata"]["image_sha256"] == "a" * 64
    assert kwargs["prompt"] == LANGUAGE_PRESERVATION_INSTRUCTIONS


@pytest.mark.asyncio
async def test_image_chat_turn_stamps_image_on_extracted_hits(monkeypatch):
    text = FakeMem0Client()
    vision = FakeMem0Client(
        add_result={
            "results": [
                {"id": "m1", "memory": "Patienten visade ett rött utslag.", "event": "ADD"}
            ]
        }
    )
    memory = ExpertMemory(text, vision)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "app.services.expertgranskning.memory.image_data_url",
        lambda digest: f"data:image/png;base64,{digest}",
    )

    hits = await memory.add_chat_turn(
        customer_id=1,
        expert_id="visual",
        user_message="Vad syns?",
        assistant_message="Ett rött utslag.",
        source="persona_chat",
        image_sha256="a" * 64,
    )

    assert [hit.text for hit in hits] == ["Patienten visade ett rött utslag."]
    assert memory_image_sha256(hits[0].metadata) == "a" * 64
    assert serialize_memory_hit(hits[0]).image_sha256 == "a" * 64
    assert all(kwargs.get("infer") is not False for _messages, kwargs in vision.adds)


@pytest.mark.asyncio
async def test_image_chat_turn_stores_description_when_nothing_extracted(monkeypatch):
    text = FakeMem0Client()
    vision = FakeMem0Client(vision_description="rött utslag på underarmen")
    memory = ExpertMemory(text, vision)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "app.services.expertgranskning.memory.image_data_url",
        lambda digest: f"data:image/png;base64,{digest}",
    )

    hits = await memory.add_chat_turn(
        customer_id=1,
        expert_id="visual",
        user_message="",
        assistant_message="Jag ser ett utslag.",
        source="persona_chat",
        image_sha256="b" * 64,
    )

    assert [hit.text for hit in hits] == ["rött utslag på underarmen"]
    assert memory_image_sha256(hits[0].metadata) == "b" * 64
    assert vision.adds[-1][1]["infer"] is False
    assert text.adds == []


@pytest.mark.asyncio
async def test_search_skips_empty_query():
    text = FakeMem0Client(
        rows=[{"id": "m1", "memory": "Should not be returned.", "source": "persona_chat"}]
    )
    memory = ExpertMemory(text, FakeMem0Client())  # type: ignore[arg-type]

    hits = await memory.search(
        customer_id=1,
        expert_id="legal",
        query="   ",
        sources=frozenset({"persona_chat"}),
    )

    assert hits == []


@pytest.mark.asyncio
async def test_search_describes_image_then_queries_text_index(monkeypatch):
    text = FakeMem0Client(
        rows=[{"id": "m1", "memory": "Kunden visade en stigande kurva.", "source": "persona_chat"}]
    )
    vision = FakeMem0Client(vision_description="stigande kurva i diagram")
    memory = ExpertMemory(text, vision)  # type: ignore[arg-type]
    monkeypatch.setattr(
        "app.services.expertgranskning.memory.image_data_url",
        lambda digest: f"data:image/png;base64,{digest}",
    )

    hits = await memory.search(
        customer_id=1,
        expert_id="visual",
        query="",
        image_sha256="a" * 64,
        sources=frozenset({"persona_chat"}),
    )

    assert text.searches == ["stigande kurva i diagram"]
    assert vision.llm.calls
    assert [hit.text for hit in hits] == ["Kunden visade en stigande kurva."]


@pytest.mark.asyncio
async def test_expert_memory_context_accepts_image_only_message(monkeypatch):
    text = FakeMem0Client(
        rows=[
            {
                "id": "m1",
                "memory": "Patienten visade en bild av utslaget.",
                "source": "persona_chat",
            }
        ]
    )
    vision = FakeMem0Client(vision_description="rött utslag på underarmen")
    memory = ExpertMemory(text, vision)  # type: ignore[arg-type]
    set_expert_memory_factory(lambda: memory)
    monkeypatch.setattr(
        "app.services.expertgranskning.memory.image_data_url",
        lambda digest: f"data:image/png;base64,{digest}",
    )
    persona = Persona(
        id="exp_1_legal",
        customer_id=1,
        kind="expert",
        name="Juristen",
        occ="Jurist",
        district="Stockholm",
        profile={},
    )

    context = await expert_memory_context(
        persona, "", default_prompts("sv"), image_sha256="a" * 64
    )

    assert "Patienten visade en bild" in context
    assert text.searches == ["rött utslag på underarmen"]


@pytest.mark.asyncio
async def test_expert_chat_context_includes_all_memory_sources():
    class FakeExpertMemory:
        async def search(self, **kwargs):
            assert kwargs["expert_id"] == "legal"
            assert kwargs["sources"] == frozenset(
                {
                    "persona_chat",
                    "panel_chat",
                        "expert_consult",
                    "intent_interview",
                    "word_findings",
                    "research_receipt",
                }
            )
            return [
                ExpertMemoryHit(
                    id="m1",
                    text="Jag betonade tidigare att ansvar måste preciseras.",
                    source="research_receipt",
                    metadata={
                        "knowledge_question_id": "question-1",
                        "source_attempt_id": "attempt-1",
                    },
                )
            ]

    set_expert_memory_factory(FakeExpertMemory)
    persona = Persona(
        id="exp_1_legal",
        customer_id=1,
        kind="expert",
        name="Juristen",
        occ="Jurist",
        district="Stockholm",
        profile={},
    )

    context = await expert_memory_context(
        persona,
        "Vad tycker du om utlåtandet?",
        default_prompts("sv"),
    )

    assert "ansvar måste preciseras" in context
    assert "knowledge_question_id=question-1" in context
    assert "source_attempt_id=attempt-1" in context
    assert "tidigare chattar" in context


@pytest.mark.asyncio
async def test_add_chat_turn_returns_saved_memories():
    text = FakeMem0Client(
        add_result={
            "results": [
                {"id": "m1", "memory": "Ansvar måste preciseras.", "event": "ADD"},
                {"id": "m2", "memory": "Gammal slutsats.", "event": "NONE"},
                {"id": "m3", "memory": "Uppdaterad slutsats.", "event": "UPDATE"},
            ]
        }
    )
    memory = ExpertMemory(text, FakeMem0Client())  # type: ignore[arg-type]

    hits = await memory.add_chat_turn(
        customer_id=1,
        expert_id="legal",
        user_message="Vad saknas?",
        assistant_message="Ansvar måste preciseras.",
        source="persona_chat",
    )

    assert [hit.text for hit in hits] == [
        "Ansvar måste preciseras.",
        "Uppdaterad slutsats.",
    ]
    assert hits[0].event == "ADD"
    assert hits[1].event == "UPDATE"
    assert hits[0].expert_id == "legal"


@pytest.mark.asyncio
async def test_list_all_and_customer_scope():
    text = FakeMem0Client(
        [
            {
                "id": "m1",
                "memory": "Från chatten.",
                "created_at": "2026-09-14T10:00:00Z",
                "metadata": {"source": "persona_chat", "agent_id": "expert:legal"},
            },
            {
                "id": "m2",
                "memory": "Från panelen.",
                "agent_id": "expert:finance",
                "metadata": {"source": "panel_chat"},
            },
        ]
    )
    memory = ExpertMemory(text, FakeMem0Client())  # type: ignore[arg-type]

    one = await memory.list_all(customer_id=1, expert_id="legal")
    assert [hit.id for hit in one] == ["m1", "m2"]
    assert one[0].expert_id == "legal"

    all_hits = await memory.list_for_customer(customer_id=1)
    assert {hit.expert_id for hit in all_hits} == {"legal", "finance"}


@pytest.mark.asyncio
async def test_expert_memory_api_lists_and_scopes(client, user_token, admin_token):
    created = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "name": "Minnesjurist",
            "occ": "Jurist",
            "district": "—",
            "quote": "Granskar avtal.",
            "profile": {
                "name": "Minnesjurist",
                "initials": "MJ",
                "kompetensomrade": "Legal risk",
                "radgivningsstil": "Försiktig",
                "yrkesbakgrund": "Jurist",
                "professionell_anekdot": "Har granskat LOI:er.",
                "beskrivning": "Granskar avtal.",
            },
        },
    )
    assert created.status_code == 201, created.text
    persona = created.json()
    catalog_key = expert_role_key(persona["name"])
    kunder = await client.get("/kunder")
    assert kunder.status_code == 200
    customer_id = next(
        row["id"] for row in kunder.json() if row["slug"] == "bolag-demo"
    )
    set_expert_memory_factory(
        lambda: ListingMemory(
            [
                ExpertMemoryHit(
                    id="m1",
                    text="Ansvar måste preciseras.",
                    source="persona_chat",
                    metadata={},
                    expert_id=catalog_key,
                    created_at="2026-09-14T10:00:00Z",
                    event="ADD",
                )
            ]
        )
    )

    listed = await client.get(
        "/expert-memory",
        params={"customer_id": customer_id, "expert_id": catalog_key},
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["count"] == 1
    assert body["memories"][0]["text"] == "Ansvar måste preciseras."
    assert body["memories"][0]["expert_name"] == persona["name"]

    by_expert = await client.get(f"/personas/{persona['id']}/memories")
    assert by_expert.status_code == 200
    assert by_expert.json()["count"] == 1
    assert by_expert.json()["memories"][0]["persona_id"] == persona["id"]

    client.headers["Authorization"] = f"Bearer {user_token}"
    denied = await client.get("/expert-memory")
    assert denied.status_code == 403
    client.headers["Authorization"] = f"Bearer {admin_token}"


def test_memory_config_includes_language_preservation(monkeypatch):
    monkeypatch.setattr(
        "app.services.expertgranskning.memory.settings.database_url",
        "postgresql+psycopg://user:pass@example.test/postgres",
    )
    config = _memory_config(vision=False)
    assert config["custom_instructions"] == LANGUAGE_PRESERVATION_INSTRUCTIONS
    assert "Never translate memories into English" in LANGUAGE_PRESERVATION_INSTRUCTIONS
    assert config["vector_store"]["provider"] == "pgvector"
    assert config["vector_store"]["config"]["embedding_model_dims"] == 1536
    assert config["vector_store"]["config"]["minconn"] == MEM0_PGVECTOR_MINCONN
    assert config["vector_store"]["config"]["maxconn"] == MEM0_PGVECTOR_MAXCONN
    assert config["history_db_path"].startswith("postgresql://")


def test_close_default_expert_memory_is_noop_when_unused():
    assert _default_memory.cache_info().currsize == 0
    close_default_expert_memory()
    assert _default_memory.cache_info().currsize == 0


def test_expert_memory_close_closes_mem0_clients():
    text = MagicMock()
    vision = MagicMock()
    text._entity_store = None
    text._telemetry_vector_store = None
    vision._entity_store = None
    vision._telemetry_vector_store = None
    ExpertMemory(text, vision).close()
    text.vector_store.connection_pool.close.assert_called_once()
    vision.vector_store.connection_pool.close.assert_called_once()
    text.close.assert_called_once()
    vision.close.assert_called_once()


@pytest.mark.asyncio
async def test_add_chat_turn_passes_language_instructions():
    text = FakeMem0Client()
    memory = ExpertMemory(text, FakeMem0Client())  # type: ignore[arg-type]
    await memory.add_chat_turn(
        customer_id=1,
        expert_id="legal",
        user_message="Ansvar måste preciseras.",
        assistant_message="Ja, i klausulen.",
        source="persona_chat",
    )
    assert text.adds[0][1]["prompt"] == LANGUAGE_PRESERVATION_INSTRUCTIONS


@pytest.mark.asyncio
async def test_research_receipt_is_structured_and_idempotent():
    text = FakeMem0Client()
    memory = ExpertMemory(text, FakeMem0Client())  # type: ignore[arg-type]

    await memory.add_research_receipt(
        customer_id=1,
        expert_id="legal",
        question="Vilka rekvisit gäller enligt 36 § avtalslagen?",
        knowledge_question_id="question-1",
        source_attempt_id="attempt-1",
    )
    _messages, kwargs = text.adds[0]
    text.rows = [
        {
            "id": "receipt-1",
            "memory": "Vilka rekvisit gäller enligt 36 § avtalslagen?",
            "metadata": dict(kwargs["metadata"]),
        }
    ]
    await memory.add_research_receipt(
        customer_id=1,
        expert_id="legal",
        question="Vilka rekvisit gäller enligt 36 § avtalslagen?",
        knowledge_question_id="question-1",
        source_attempt_id="attempt-1",
    )

    assert len(text.adds) == 1
    assert kwargs["infer"] is False
    assert kwargs["metadata"]["source"] == "research_receipt"
    assert kwargs["metadata"]["knowledge_question_id"] == "question-1"
    assert kwargs["metadata"]["source_attempt_id"] == "attempt-1"


@pytest.mark.asyncio
async def test_update_and_delete_memory_roundtrip():
    text = FakeMem0Client(
        [
            {
                "id": "m1",
                "memory": "Gammal text.",
                "user_id": "kund:1",
                "agent_id": "expert:legal",
                "metadata": {"source": "persona_chat"},
            }
        ]
    )
    memory = ExpertMemory(text, FakeMem0Client())  # type: ignore[arg-type]
    updated = await memory.update(memory_id="m1", text="Ny text på svenska.")
    assert updated.text == "Ny text på svenska."
    assert memory_belongs_to(updated, customer_id=1, expert_id="legal")
    await memory.delete(memory_id="m1")
    assert text.deletes == ["m1"]
    assert await memory.get(memory_id="m1") is None


@pytest.mark.asyncio
async def test_expert_memory_api_updates_and_deletes(
    client, user_token, admin_token, bolag_token
):
    created = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "name": "Minnesredigerare",
            "occ": "Jurist",
            "district": "—",
            "quote": "Granskar avtal.",
            "profile": {
                "name": "Minnesredigerare",
                "initials": "MR",
                "kompetensomrade": "Legal risk",
                "radgivningsstil": "Försiktig",
                "yrkesbakgrund": "Jurist",
                "professionell_anekdot": "Har granskat LOI:er.",
                "beskrivning": "Granskar avtal.",
            },
        },
    )
    assert created.status_code == 201, created.text
    persona = created.json()
    catalog_key = expert_role_key(persona["name"])
    kunder = await client.get("/kunder")
    assert kunder.status_code == 200
    customer_id = next(
        row["id"] for row in kunder.json() if row["slug"] == "bolag-demo"
    )
    store = ListingMemory(
        [
            ExpertMemoryHit(
                id="m-edit",
                text="Ansvar måste preciseras.",
                source="persona_chat",
                metadata={"user_id": memory_user_id(customer_id)},
                expert_id=catalog_key,
                user_id=memory_user_id(customer_id),
                created_at="2026-09-14T10:00:00Z",
            )
        ]
    )
    set_expert_memory_factory(lambda: store)

    patched = await client.patch(
        "/expert-memory/m-edit",
        json={"text": "  Klausulen måste preciseras.  "},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["text"] == "Klausulen måste preciseras."

    client.headers["Authorization"] = f"Bearer {user_token}"
    forbidden = await client.patch(
        "/expert-memory/m-edit",
        json={"text": "Ska inte gå."},
    )
    assert forbidden.status_code == 403
    scoped_out = await client.patch(
        f"/personas/{persona['id']}/memories/m-edit",
        json={"text": "Fel kund."},
    )
    assert scoped_out.status_code == 403

    client.headers["Authorization"] = f"Bearer {bolag_token}"
    via_persona = await client.patch(
        f"/personas/{persona['id']}/memories/m-edit",
        json={"text": "Uppdaterat från chatten."},
    )
    assert via_persona.status_code == 200, via_persona.text
    assert via_persona.json()["text"] == "Uppdaterat från chatten."

    missing = await client.patch(
        f"/personas/{persona['id']}/memories/other",
        json={"text": "Finns inte."},
    )
    assert missing.status_code == 404

    deleted = await client.delete(f"/personas/{persona['id']}/memories/m-edit")
    assert deleted.status_code == 204
    assert store.hits == []

    client.headers["Authorization"] = f"Bearer {admin_token}"
    gone = await client.delete("/expert-memory/m-edit")
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_delete_all_scopes_customer_and_expert():
    text = FakeMem0Client(
        [
            {
                "id": "keep-other-kund",
                "memory": "Annat bolag.",
                "user_id": "kund:9",
                "agent_id": "expert:legal",
            },
            {
                "id": "drop",
                "memory": "Denna raderas.",
                "user_id": "kund:1",
                "agent_id": "expert:legal",
            },
            {
                "id": "keep-other-expert",
                "memory": "Annan expert.",
                "user_id": "kund:1",
                "agent_id": "expert:finance",
            },
        ]
    )
    memory = ExpertMemory(text, FakeMem0Client())  # type: ignore[arg-type]
    await memory.delete_all(customer_id=1, expert_id="legal")
    assert text.delete_alls == [{"user_id": "kund:1", "agent_id": "expert:legal"}]
    assert {row["id"] for row in text.rows} == {"keep-other-kund", "keep-other-expert"}


@pytest.mark.asyncio
async def test_expert_memory_api_clears_scope(client, user_token, admin_token, bolag_token):
    created = await client.post(
        "/personas",
        json={
            "kind": "expert",
            "name": "Minnesrensare",
            "occ": "Jurist",
            "district": "—",
            "quote": "Granskar avtal.",
            "profile": {
                "name": "Minnesrensare",
                "initials": "MR",
                "kompetensomrade": "Legal risk",
                "radgivningsstil": "Försiktig",
                "yrkesbakgrund": "Jurist",
                "professionell_anekdot": "Har granskat LOI:er.",
                "beskrivning": "Granskar avtal.",
            },
        },
    )
    assert created.status_code == 201, created.text
    persona = created.json()
    catalog_key = expert_role_key(persona["name"])
    kunder = await client.get("/kunder")
    assert kunder.status_code == 200
    customer_id = next(
        row["id"] for row in kunder.json() if row["slug"] == "bolag-demo"
    )
    store = ListingMemory(
        [
            ExpertMemoryHit(
                id="m-clear",
                text="Ska rensas.",
                source="persona_chat",
                metadata={"user_id": memory_user_id(customer_id)},
                expert_id=catalog_key,
                user_id=memory_user_id(customer_id),
            ),
            ExpertMemoryHit(
                id="m-keep",
                text="Annan expert.",
                source="persona_chat",
                metadata={"user_id": memory_user_id(customer_id)},
                expert_id="other-expert",
                user_id=memory_user_id(customer_id),
            ),
        ]
    )
    set_expert_memory_factory(lambda: store)

    client.headers["Authorization"] = f"Bearer {user_token}"
    denied = await client.delete("/expert-memory")
    assert denied.status_code == 403

    client.headers["Authorization"] = f"Bearer {bolag_token}"
    cleared = await client.delete(f"/personas/{persona['id']}/memories")
    assert cleared.status_code == 204
    assert [hit.id for hit in store.hits] == ["m-keep"]

    client.headers["Authorization"] = f"Bearer {admin_token}"
    store.hits.append(
        ExpertMemoryHit(
            id="m-again",
            text="Ny rad.",
            source="persona_chat",
            metadata={"user_id": memory_user_id(customer_id)},
            expert_id=catalog_key,
            user_id=memory_user_id(customer_id),
        )
    )
    wiped = await client.delete(
        "/expert-memory",
        params={"customer_id": customer_id, "expert_id": catalog_key},
    )
    assert wiped.status_code == 204
    assert [hit.id for hit in store.hits] == ["m-keep"]
