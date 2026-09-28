"""Jev passage routing in front of LegalInterpreter. No KeepAll in production."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Kund, TextUnitRecord
from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.knowledge.models import EmbeddedKnowledgeChunk, KnowledgeChunk
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.models import SearchResults
from app.services.lagen_nu.passage_router import (
    JevPassageRouter,
    PassageRoutingError,
    clip_passage_texts,
    clip_text_to_budget,
    expand_selected_neighbors,
    rank_text_units,
)
from app.services.lagen_nu.research_source import LagenNuResearchSource
from tests.knowledge_fakes import FakeEmbeddingProvider, fake_embed_text
from tests.test_lagen_nu_provider import (
    FakeLagenNuClient,
    FakeLegalInterpreter,
    PassthroughLagenNuSelector,
    _document,
    _hit,
)
from tests.test_research import _context, _need

URI = "https://lagen.nu/dom/nja/2005s142"
REASONING = (
    "Högsta domstolen ogillade yrkandet om jämkning enligt 36 §. "
    "Avtalsvillkoret lämnades utan avseende."
)
BACKGROUND = (
    "Leasingavtalet tecknades år 1998 och avsåg en personbil. Parterna åt lunch i Göteborg."
)
NEIGHBOR = "Parterna undertecknade handlingen samma dag i Göteborg."
OTHER_SECTION = "Skatteverket beslutade om eftertaxering för inkomståret."
MULTI_UNIT_TEXT = f"# Domskäl\n\n{REASONING}\n\n# Sakomständigheter\n\n{BACKGROUND}"
_SECTION_FILL = "bakgrund utan rättsfråga. "
NEIGHBOR_DOC = (
    f"# Domskäl\n\n{NEIGHBOR} {_SECTION_FILL * 30}\n\n"
    f"{REASONING} {_SECTION_FILL * 30}\n\n"
    f"# Annan avdelning\n\n{OTHER_SECTION}"
)


def _unit(
    unit_id: str,
    text: str,
    *,
    section_id: str = "s1",
    ordinal: int = 0,
    document_id: str = "d1",
    document_version_id: str = "v1",
) -> TextUnitRecord:
    return TextUnitRecord(
        id=unit_id,
        document_version_id=document_version_id,
        document_id=document_id,
        customer_id=1,
        section_id=section_id,
        ordinal=ordinal,
        text=text,
        content_hash=unit_id,
    )


async def _store_for(units: list[TextUnitRecord]) -> MemoryKnowledgeVectorStore:
    store = MemoryKnowledgeVectorStore()
    await store.upsert_chunks(
        [
            EmbeddedKnowledgeChunk(
                chunk=KnowledgeChunk(
                    document_id=unit.document_id,
                    chunk_id=unit.id,
                    text=unit.text,
                    customer_id=7,
                    case_id=None,
                    module=None,
                    title=unit.id,
                    metadata={
                        "document_version_id": unit.document_version_id,
                        "text_unit_id": unit.id,
                    },
                ),
                embedding=fake_embed_text(unit.text),
            )
            for unit in units
        ]
    )
    return store


def _jev_result(answers: dict[str, Any]) -> JevSystemOneResult:
    return JevSystemOneResult(
        answers=answers,
        model="jev-test",
        latency_ms=1.0,
        input_chars=10,
        usage=JevUsage(),
        raw={"answers": answers},
    )


class ScriptedPassageJev:
    def __init__(self, nouls: dict[str, float] | float | Exception) -> None:
        self.nouls = nouls
        self.asks: list[object] = []

    async def ask(
        self,
        *,
        state: object,
        questions: dict[str, Any],
        model: str,
        timeout_seconds: float,
    ) -> JevSystemOneResult:
        del model, timeout_seconds
        self.asks.append(state)
        if isinstance(self.nouls, Exception):
            raise self.nouls
        if isinstance(self.nouls, float):
            return _jev_result({key: {"noul": self.nouls} for key in questions})
        return _jev_result({key: {"noul": self.nouls[key]} for key in questions})


class ContainsPassageJev:
    def __init__(self, needle: str, *, keep: float = 0.9, drop: float = 0.1) -> None:
        self.needle = needle.casefold()
        self.keep = keep
        self.drop = drop
        self.asks: list[object] = []

    async def ask(
        self,
        *,
        state: object,
        questions: dict[str, Any],
        model: str,
        timeout_seconds: float,
    ) -> JevSystemOneResult:
        del model, timeout_seconds
        self.asks.append(state)
        rows = state["passages"] if isinstance(state, dict) else []
        answers: dict[str, Any] = {}
        for index, item in enumerate(rows):
            text = str(item["text"])
            noul = self.keep if self.needle in text.casefold() else self.drop
            answers[f"relevant_{index}"] = {"noul": noul}
        return _jev_result(answers)


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db:
        db.add(Kund(id=7, name="acme", slug="acme", available_modules=["dd"]))
        await db.flush()
        yield db
    await engine.dispose()


def _research_source(
    session: AsyncSession,
    client: FakeLagenNuClient,
    *,
    jev: ScriptedPassageJev | ContainsPassageJev,
    interpreter=None,
    embeddings: FakeEmbeddingProvider | None = None,
    vector_store: MemoryKnowledgeVectorStore | None = None,
) -> LagenNuResearchSource:
    return LagenNuResearchSource(
        source_type="swedish_case_law",
        client=client,
        selector=PassthroughLagenNuSelector(),
        interpreter=interpreter or FakeLegalInterpreter(),
        session=session,
        embeddings=embeddings or FakeEmbeddingProvider(),
        vector_store=vector_store or MemoryKnowledgeVectorStore(),
        passage_router=JevPassageRouter(jev, top_k=4, adjacent=1),
    )


def _client(text: str = MULTI_UNIT_TEXT) -> FakeLagenNuClient:
    hit = _hit(uri=URI, pinpoint=None, source="dv", highlight="jämkning")
    return FakeLagenNuClient(
        search=SearchResults(query="", total=1, results=(hit,)),
        documents={URI: _document(uri=URI, pinpoint=None, text=text, source="dv")},
    )


async def test_rank_prefers_token_overlap():
    units = [
        _unit("bg", BACKGROUND, ordinal=0),
        _unit("reason", REASONING, ordinal=1),
    ]
    embeddings = FakeEmbeddingProvider()
    ranked = await rank_text_units(
        "Jämkades villkoret enligt 36 §?",
        units,
        embeddings,
        await _store_for(units),
    )
    assert next(unit.id for _score, unit in ranked) == "reason"
    assert embeddings.calls == [("Jämkades villkoret enligt 36 §?",)]


def test_expand_keeps_same_section_neighbors_only():
    units = [
        _unit("a", "first", section_id="s1", ordinal=0),
        _unit("b", "second", section_id="s1", ordinal=1),
        _unit("c", "other", section_id="s2", ordinal=0),
    ]
    expanded = expand_selected_neighbors([units[1]], units, adjacent=1)
    assert [unit.id for unit in expanded] == ["a", "b"]


async def test_jev_sees_seeds_then_same_section_neighbor_is_expanded():
    units = [
        _unit("left", NEIGHBOR, section_id="s1", ordinal=0),
        _unit("reason", REASONING, section_id="s1", ordinal=1),
        _unit("other", OTHER_SECTION, section_id="s2", ordinal=0),
    ]
    jev = ContainsPassageJev("jämkning")
    routed = await JevPassageRouter(jev, top_k=1, adjacent=1).route(
        question="Jämkades villkoret enligt 36 §?",
        units=units,
        embeddings=FakeEmbeddingProvider(),
        stored=await _store_for(units),
    )
    first = jev.asks[0]
    assert isinstance(first, dict)
    offered = [item["id"] for item in first["passages"]]
    assert offered == ["reason"]
    assert routed.candidate_ids == ("reason",)
    assert routed.kept_ids == ("reason",)
    assert [unit.id for unit in routed.units] == ["left", "reason"]
    assert routed.expanded_ids == ("left", "reason")
    assert "personbil" not in routed.interpreter_text
    assert OTHER_SECTION not in routed.interpreter_text
    assert NEIGHBOR in routed.interpreter_text
    assert "jämkning" in routed.interpreter_text


async def test_other_section_is_not_expanded_after_jev():
    units = [
        _unit("reason", REASONING, section_id="s1", ordinal=0),
        _unit("other", OTHER_SECTION, section_id="s2", ordinal=0),
    ]
    routed = await JevPassageRouter(ContainsPassageJev("jämkning"), top_k=1, adjacent=1).route(
        question="Jämkades villkoret enligt 36 §?",
        units=units,
        embeddings=FakeEmbeddingProvider(),
        stored=await _store_for(units),
    )
    assert routed.expanded_ids == ("reason",)
    assert OTHER_SECTION not in routed.interpreter_text


async def test_jev_keeps_relevant_passages_and_drops_the_rest():
    units = [
        _unit("bg", BACKGROUND, section_id="s1", ordinal=0),
        _unit("reason", REASONING, section_id="s2", ordinal=0),
    ]
    jev = ContainsPassageJev("jämkning")
    routed = await JevPassageRouter(jev, top_k=2, adjacent=0).route(
        question="Jämkades villkoret enligt 36 §?",
        units=units,
        embeddings=FakeEmbeddingProvider(),
        stored=await _store_for(units),
    )
    assert [unit.id for unit in routed.units] == ["reason"]
    assert routed.kept_ids == ("reason",)
    assert routed.candidate_ids == ("bg", "reason") or routed.candidate_ids == (
        "reason",
        "bg",
    )
    assert routed.router == "jev"
    assert jev.asks


async def test_jev_empty_keep_is_irrelevant_relation():
    units = [_unit("bg", BACKGROUND)]
    with pytest.raises(PassageRoutingError, match="kept no passage") as exc:
        await JevPassageRouter(ContainsPassageJev("jämkning")).route(
            question="Jämkades villkoret enligt 36 §?",
            units=units,
            embeddings=FakeEmbeddingProvider(),
            stored=await _store_for(units),
        )
    assert exc.value.category == "irrelevant_relation"
    assert exc.value.seed_ids == ("bg",)


async def test_jev_error_is_selection_failed():
    units = [_unit("reason", REASONING)]
    jev = ScriptedPassageJev(JevClientError("TYPESAFE_API_KEY is not configured", category="auth"))
    with pytest.raises(PassageRoutingError, match="TYPESAFE_API_KEY") as exc:
        await JevPassageRouter(jev).route(
            question="Jämkades villkoret enligt 36 §?",
            units=units,
            embeddings=FakeEmbeddingProvider(),
            stored=await _store_for(units),
        )
    assert exc.value.category == "selection_failed"


async def test_budget_clipping_is_deterministic(caplog: pytest.LogCaptureFixture):
    long_left = "vänster " * 80
    long_reason = f"{REASONING} {'x' * 400}"
    units = [
        _unit("left", long_left, ordinal=0),
        _unit("reason", long_reason, ordinal=1),
    ]
    jev = ScriptedPassageJev(0.9)
    router = JevPassageRouter(
        jev,
        top_k=2,
        adjacent=0,
        jev_char_budget=60,
        interpreter_char_budget=40,
    )
    first = await router.route(
        question="Jämkades villkoret enligt 36 §?",
        units=units,
        embeddings=FakeEmbeddingProvider(),
        stored=await _store_for(units),
    )
    second = await router.route(
        question="Jämkades villkoret enligt 36 §?",
        units=units,
        embeddings=FakeEmbeddingProvider(),
        stored=await _store_for(units),
    )
    offered = jev.asks[0]
    assert isinstance(offered, dict)
    texts = [str(item["text"]) for item in offered["passages"]]
    assert sum(len(text) for text in texts) <= 60
    assert first.jev_clipped is True
    assert first.interpreter_clipped is True
    assert first.interpreter_text == second.interpreter_text
    assert len(first.interpreter_text) == 40
    assert first.interpreter_text == first.interpreter_text[:40]
    assert "passage_router_clipped" in caplog.text
    assert jev.asks[0] == jev.asks[1]


def test_clip_helpers_are_prefix_and_stable():
    assert clip_text_to_budget("abcdef", 4) == ("abcd", True)
    assert clip_text_to_budget("ab", 4) == ("ab", False)
    first, clipped = clip_passage_texts(
        [{"id": "a", "text": "12345"}, {"id": "b", "text": "xyz"}],
        budget=6,
    )
    assert clipped is True
    assert [row["text"] for row in first] == ["12345", "x"]
    again, _clipped = clip_passage_texts(
        [{"id": "a", "text": "12345"}, {"id": "b", "text": "xyz"}],
        budget=6,
    )
    assert first == again


async def test_research_interprets_only_expanded_kept_units(session: AsyncSession):
    client = _client()
    evidence = await _research_source(
        session,
        client,
        jev=ContainsPassageJev("jämkning"),
    ).research(
        _need("swedish_case_law", question="Jämkades villkoret enligt 36 §?"),
        _context(),
    )
    assert [item.status for item in evidence] == ["found"]
    raw = evidence[0].legal_result.raw_text
    assert "jämkning" in raw
    assert "personbil" not in raw
    assert evidence[0].metadata["passage_router"] == "jev"
    assert evidence[0].metadata["text_unit_ids"]
    assert evidence[0].metadata["passage_candidate_ids"]
    assert evidence[0].metadata["passage_kept_ids"]
    assert set(evidence[0].metadata["passage_kept_ids"]).issubset(
        set(evidence[0].metadata["text_unit_ids"])
    )


async def test_research_expands_low_relevance_same_section_neighbor(session: AsyncSession):
    client = _client(NEIGHBOR_DOC)
    evidence = await _research_source(
        session,
        client,
        jev=ContainsPassageJev("jämkning"),
    ).research(
        _need("swedish_case_law", question="Jämkades villkoret enligt 36 §?"),
        _context(),
    )
    assert [item.status for item in evidence] == ["found"]
    raw = evidence[0].legal_result.raw_text
    assert "jämkning" in raw
    assert "undertecknade" in raw
    assert "eftertaxering" not in raw
    assert len(evidence[0].metadata["text_unit_ids"]) >= 2
    assert len(evidence[0].metadata["passage_kept_ids"]) == 1


async def test_stored_embeddings_are_reused_across_research_needs(session: AsyncSession):
    client = _client()
    embeddings = FakeEmbeddingProvider()
    store = MemoryKnowledgeVectorStore()
    source = _research_source(
        session,
        client,
        jev=ContainsPassageJev("jämkning"),
        embeddings=embeddings,
        vector_store=store,
    )
    first_need = _need("swedish_case_law", question="Jämkades villkoret enligt 36 §?")
    second_need = _need("swedish_case_law", question="Lämnades villkoret utan avseende?")
    first = await source.research(first_need, _context())
    ingest_calls = list(embeddings.calls)
    second = await source.research(second_need, _context())
    assert [item.status for item in first] == ["found"]
    assert [item.status for item in second] == ["found"]
    assert len(ingest_calls) >= 2
    assert all(len(call) > 1 for call in ingest_calls[:-1]) or len(ingest_calls[0]) > 1
    assert embeddings.calls[-2] == (first_need.question,)
    assert embeddings.calls[-1] == (second_need.question,)
    assert all(len(call) == 1 for call in embeddings.calls[1:])
    assert store.chunks
    assert first[0].metadata["document_version_id"] == second[0].metadata["document_version_id"]


async def test_research_empty_keep_is_not_found(session: AsyncSession):
    client = _client()
    evidence = await _research_source(
        session,
        client,
        jev=ContainsPassageJev("this-token-is-absent"),
    ).research(
        _need("swedish_case_law", question="Jämkades villkoret enligt 36 §?"),
        _context(),
    )
    assert [item.status for item in evidence] == ["not_found"]
    assert evidence[0].metadata["failure_category"] == "irrelevant_relation"
    assert evidence[0].legal_result is None
    assert evidence[0].metadata["passage_candidate_ids"]


async def test_research_jev_failure_is_error_not_full_document(session: AsyncSession):
    client = _client()
    interpreter = FakeLegalInterpreter()
    evidence = await _research_source(
        session,
        client,
        jev=ScriptedPassageJev(
            JevClientError("TYPESAFE_API_KEY is not configured", category="auth")
        ),
        interpreter=interpreter,
    ).research(
        _need("swedish_case_law", question="Jämkades villkoret enligt 36 §?"),
        _context(),
    )
    assert [item.status for item in evidence] == ["error"]
    assert evidence[0].metadata["failure_category"] == "selection_failed"
    assert evidence[0].legal_result is None


async def test_production_router_fails_loud_without_typesafe_key(session: AsyncSession):
    client = _client()
    source = LagenNuResearchSource(
        source_type="swedish_case_law",
        client=client,
        selector=PassthroughLagenNuSelector(),
        interpreter=FakeLegalInterpreter(),
        session=session,
        embeddings=FakeEmbeddingProvider(),
        vector_store=MemoryKnowledgeVectorStore(),
    )
    evidence = await source.research(
        _need("swedish_case_law", question="Jämkades villkoret enligt 36 §?"),
        _context(),
    )
    assert [item.status for item in evidence] == ["error"]
    assert evidence[0].metadata["failure_category"] == "selection_failed"
    assert "TYPESAFE_API_KEY" in str(evidence[0].metadata["detail"])
