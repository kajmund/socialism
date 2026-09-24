"""Jev passage routing in front of LegalInterpreter. No KeepAll in production."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Kund, TextUnitRecord
from app.jev.system import JevClientError, JevSystemOneResult, JevUsage
from app.services.knowledge.vector_store import MemoryKnowledgeVectorStore
from app.services.lagen_nu.models import SearchResults
from app.services.lagen_nu.passage_router import (
    JevPassageRouter,
    PassageRoutingError,
    expand_selected_neighbors,
    rank_text_units,
)
from app.services.lagen_nu.research_source import LagenNuResearchSource
from tests.knowledge_fakes import FakeEmbeddingProvider
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
    "Leasingavtalet tecknades år 1998 och avsåg en personbil. "
    "Parterna åt lunch i Göteborg."
)
MULTI_UNIT_TEXT = f"# Domskäl\n\n{REASONING}\n\n# Sakomständigheter\n\n{BACKGROUND}"


def _unit(
    unit_id: str,
    text: str,
    *,
    section_id: str = "s1",
    ordinal: int = 0,
) -> TextUnitRecord:
    return TextUnitRecord(
        id=unit_id,
        document_version_id="v1",
        document_id="d1",
        section_id=section_id,
        ordinal=ordinal,
        text=text,
        content_hash=unit_id,
    )


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
) -> LagenNuResearchSource:
    return LagenNuResearchSource(
        source_type="swedish_case_law",
        client=client,
        selector=PassthroughLagenNuSelector(),
        interpreter=interpreter or FakeLegalInterpreter(),
        session=session,
        embeddings=FakeEmbeddingProvider(),
        vector_store=MemoryKnowledgeVectorStore(),
        passage_router=JevPassageRouter(jev, top_k=4, adjacent=1),
    )


def _client() -> FakeLagenNuClient:
    hit = _hit(uri=URI, pinpoint=None, source="dv", highlight="jämkning")
    return FakeLagenNuClient(
        search=SearchResults(query="", total=1, results=(hit,)),
        documents={URI: _document(uri=URI, pinpoint=None, text=MULTI_UNIT_TEXT, source="dv")},
    )


async def test_rank_prefers_token_overlap():
    units = [
        _unit("bg", BACKGROUND, ordinal=0),
        _unit("reason", REASONING, ordinal=1),
    ]
    ranked = await rank_text_units(
        "Jämkades villkoret enligt 36 §?",
        units,
        FakeEmbeddingProvider(),
    )
    assert next(unit.id for _score, unit in ranked) == "reason"


def test_expand_keeps_same_section_neighbors_only():
    units = [
        _unit("a", "first", section_id="s1", ordinal=0),
        _unit("b", "second", section_id="s1", ordinal=1),
        _unit("c", "other", section_id="s2", ordinal=0),
    ]
    expanded = expand_selected_neighbors([units[1]], units, adjacent=1)
    assert [unit.id for unit in expanded] == ["a", "b"]


async def test_ranked_neighbors_are_offered_to_jev():
    units = [
        _unit("left", "neighbor left", section_id="s1", ordinal=0),
        _unit("reason", REASONING, section_id="s1", ordinal=1),
        _unit("right", "neighbor right", section_id="s1", ordinal=2),
    ]
    jev = ScriptedPassageJev(0.9)
    routed = await JevPassageRouter(jev, top_k=1, adjacent=1).route(
        question="Jämkades villkoret enligt 36 §?",
        units=units,
        embeddings=FakeEmbeddingProvider(),
    )
    first = jev.asks[0]
    assert isinstance(first, dict)
    offered = [item["id"] for item in first["passages"]]
    assert offered == ["left", "reason", "right"]
    assert [unit.id for unit in routed.units] == ["left", "reason", "right"]


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
    )
    assert [unit.id for unit in routed.units] == ["reason"]
    assert routed.kept_ids == ("reason",)
    assert routed.router == "jev"
    assert jev.asks


async def test_jev_empty_keep_is_irrelevant_relation():
    units = [_unit("bg", BACKGROUND)]
    with pytest.raises(PassageRoutingError, match="kept no passage") as exc:
        await JevPassageRouter(ContainsPassageJev("jämkning")).route(
            question="Jämkades villkoret enligt 36 §?",
            units=units,
            embeddings=FakeEmbeddingProvider(),
        )
    assert exc.value.category == "irrelevant_relation"


async def test_jev_error_is_selection_failed():
    units = [_unit("reason", REASONING)]
    jev = ScriptedPassageJev(
        JevClientError("TYPESAFE_API_KEY is not configured", category="auth")
    )
    with pytest.raises(PassageRoutingError, match="TYPESAFE_API_KEY") as exc:
        await JevPassageRouter(jev).route(
            question="Jämkades villkoret enligt 36 §?",
            units=units,
            embeddings=FakeEmbeddingProvider(),
        )
    assert exc.value.category == "selection_failed"


async def test_research_interprets_only_jev_kept_units(session: AsyncSession):
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
    assert len(evidence[0].metadata["text_unit_ids"]) == 1
    assert len(evidence[0].metadata["passage_candidate_ids"]) >= 1


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
