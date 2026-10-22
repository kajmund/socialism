"""Fail-first diagnostics for the live 0-found investigation (task-12).

These tests pin the broken behavior found in task-11 without changing
production. They stay xfail/skip until the fixes are approved separately:

* task-13 — citation/flow normalization in `research_source.py`;
* task-10/live — make the live measurement use Postgres or serial needs so
  SQLite write contention cannot masquerade as retrieval failures.

When a fix lands, the xfail marker must be removed and the assertion kept.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database.sqlite import async_engine_kwargs
from app.services.knowledge.units import TextUnit
from app.services.lagen_nu.passage_router import rank_text_units
from app.services.lagen_nu.research_source import (
    _resolution_query,
    select_lagen_nu_flow,
)
from app.services.research.models import ResearchNeed
from scripts.benchmark_research_loop import FakeEmbeddings

# Questions taken from the frozen live artifact's derived needs.
BARE_SECTION = (
    "Vilka specifika avtalsvillkor (t.ex. prisjusteringsklausuler, "
    "ansvarsbegränsningar, uppsägningsrättigheter) har i dessa "
    "domstolsavgöranden jämkats med stöd av 36 §?"
)
REVERSED_SECTION = (
    "Vilka rättsliga kriterier eller tester har domstolar använt för att "
    "avgöra om ett avtalsvillkor är föremål för jämkning enligt § 36?"
)


def _need(question: str) -> ResearchNeed:
    return ResearchNeed(
        id="diagnosis",
        question=question,
        why_needed="live diagnosis",
        requested_by=["task-12"],
        source_types=["swedish_case_law"],
    )


def test_resolution_query_refuses_bare_section_without_law() -> None:
    need = _need(BARE_SECTION)
    assert _resolution_query(need, "swedish_case_law") is None
    assert select_lagen_nu_flow(need) == "search"


def test_resolution_query_does_not_return_the_whole_question() -> None:
    need = _need(REVERSED_SECTION)
    assert _resolution_query(need, "swedish_case_law") is None


def test_reversed_marker_does_not_select_resolve_without_a_citation() -> None:
    assert select_lagen_nu_flow(_need(REVERSED_SECTION)) == "search"


@dataclass(frozen=True)
class _StoredVectors:
    vectors: dict[str, list[float]]

    async def get_text_unit_embeddings(
        self,
        *,
        document_id: str,
        document_version_id: str,
        text_unit_ids: list[str],
    ) -> dict[str, list[float]]:
        del document_id, document_version_id
        return {unit_id: self.vectors[unit_id] for unit_id in text_unit_ids}


def _unit(unit_id: str, ordinal: int, text: str) -> TextUnit:
    return TextUnit(
        id=unit_id,
        document_version_id="version-1",
        document_id="document-1",
        section_id=f"section-{ordinal}",
        ordinal=ordinal,
        text=text,
        content_hash=f"hash-{unit_id}",
    )


def test_constant_embeddings_are_degenerate_and_not_quality_input() -> None:
    """Fake embeddings rank every passage equally; live must use production embeddings."""
    units = [
        _unit("heading", 0, "## Sammanfattning"),
        _unit("body", 1, "36 § avtalslagen om jämkning av oskäliga avtalsvillkor."),
    ]

    async def run() -> list[tuple[float, TextUnit]]:
        embeddings = FakeEmbeddings()
        vectors = await embeddings.embed([unit.text for unit in units])
        stored = _StoredVectors(dict(zip([unit.id for unit in units], vectors, strict=True)))
        return await rank_text_units(BARE_SECTION, units, embeddings, stored)

    ranked = asyncio.run(run())
    assert len({score for score, _unit in ranked}) == 1


@pytest.mark.skip(
    reason=(
        "task-10/live: SQLite write contention is a live-harness environment "
        "issue (Postgres or serial needs will remove it), not a production "
        "fix; keep this reproduction for the next live diagnostic run"
    ),
)
def test_concurrent_sqlite_writers_raise_database_is_locked() -> None:
    async def run() -> None:
        url = f"sqlite+aiosqlite:///{Path(tempfile.mkdtemp()) / 'lock.sqlite'}"
        engine = create_async_engine(
            url,
            **async_engine_kwargs(url),
            connect_args={"check_same_thread": False, "timeout": 0.2},
        )
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.execute(text("create table t (id integer primary key, v text)"))
        first = factory()
        second = factory()
        try:
            await first.execute(text("insert into t(v) values ('first')"))
            with pytest.raises(OperationalError) as raised:
                await second.execute(text("insert into t(v) values ('second')"))
            assert "database is locked" in str(raised.value).casefold()
        finally:
            await first.rollback()
            await second.rollback()
            await first.close()
            await second.close()
            await engine.dispose()

    asyncio.run(run())
