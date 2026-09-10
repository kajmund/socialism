"""Attempt.ready → frozen EvidenceSet → generic_panel → Attempt.completed."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Kund, PanelSession
from app.llm import set_structured_completer, set_text_completer, set_tools_completer
from app.services.execution import (
    ExecutionFrozenError,
    ExecutionStatusError,
    add_evidence_items,
    claim_attempt_running,
    clone_attempt,
    create_attempt,
    create_evidence_set,
    create_run,
    fail_attempt,
    freeze_evidence_set,
    get_attempt,
    get_attempt_result,
    get_evidence_set,
    list_evidence_items,
    mark_ready,
    mark_researching,
    persist_attempt_result,
)
from app.services.execution.snapshots import snapshot_research_evidence
from app.services.expert_tools import DEFAULT_EXPERT_TOOL_IDS, default_expert_tools
from app.services.panel.attempt_execution import (
    PanelAttemptError,
    execute_generic_panel_attempt,
)
from app.services.panel.engine import _expert_complete
from app.services.panel.research import empty_research_structured
from app.services.panel.schemas import PanelExpertSlot
from app.services.panel.synthesis import (
    GenericPanelSynthesis,
    SynthesizedClaim,
    filter_evidence_refs,
)
from app.services.prompt_catalog import default_prompts
from app.services.research.models import research_evidence

PROMPTS = default_prompts("sv")

PANEL_CONFIG = {
    "topic": "Vad gäller skattesatsen?",
    "brief": "Kommunal skattesats.",
    "max_rounds": 1,
    "expert_slots": [
        {
            "slot_id": "legal",
            "label": "Jurist",
            "profile": "Skatt",
            "tools": list(DEFAULT_EXPERT_TOOL_IDS),
        },
    ],
}


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as session:
        yield session, factory
    await engine.dispose()


async def _customer(session: AsyncSession, slug: str) -> Kund:
    kund = Kund(name=slug, slug=slug, available_modules=["dd"])
    session.add(kund)
    await session.flush()
    return kund


def _found(*, need: str, excerpt: str, locator: str, title: str = "Kommunens skattesats"):
    return research_evidence(
        research_need_id=need,
        source_type="customer_knowledge",
        status="found",
        title=title,
        excerpt=excerpt,
        locator=locator,
        source_id="doc-brief",
        source_url="https://example.test/brief.pdf",
        provider="supabase",
        score=0.91,
        retrieved_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        metadata={"document_id": "doc-brief", "version": "3", "content_hash": f"seen-{need}"},
    )


def _gap(*, need: str, status: str, source_type: str, title: str):
    return research_evidence(
        research_need_id=need,
        source_type=source_type,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        title=title,
        excerpt=None,
        locator=None,
        retrieved_at=datetime(2026, 4, 1, 12, 0, tzinfo=UTC),
        metadata={"reason": title},
    )


async def _ready_attempt(
    session: AsyncSession,
    *,
    slug: str = "acme",
    items: list | None = None,
    attempt_type: str = "generic_panel",
    config: dict | None = None,
    attach_evidence: bool = True,
):
    customer = await _customer(session, slug)
    run = await create_run(
        session,
        customer_id=customer.id,
        module="dd",
        title="Skattesats",
        context={"case_id": "case-1"},
    )
    evidence_set = await create_evidence_set(session, run_id=run.id)
    snapshots = items or [
        _found(need="research_1", excerpt="skattesats 32%", locator="p. 14"),
        _found(
            need="research_2",
            excerpt="jämförelse 2024",
            locator="p. 4",
            title="Jämförelse",
        ),
        _gap(
            need="research_3",
            status="not_found",
            source_type="customer_knowledge",
            title="Ingen kundpolicy",
        ),
        _gap(
            need="research_4",
            status="error",
            source_type="swedish_law",
            title="swedish_law timeout",
        ),
    ]
    stored = await add_evidence_items(
        session, evidence_set_id=evidence_set.id, items=snapshots
    )
    frozen = await freeze_evidence_set(session, evidence_set.id)
    attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type=attempt_type,
        configuration_snapshot=config or dict(PANEL_CONFIG),
        input_snapshot={"question": "Vad gäller skattesatsen?"},
        evidence_set_id=frozen.id if attach_evidence else None,
    )
    if attach_evidence:
        attempt = await mark_ready(session, attempt.id)
    await session.commit()
    return customer, run, frozen, stored, attempt


def _install_panel_llm(captured: list[list[dict]] | None = None):
    async def _complete(messages, *, model=None):
        if captured is not None:
            captured.append([dict(item) for item in messages])
        user = messages[-1]["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            return "JA"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return "Pad"
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            return "Skattesatsen är 32% enligt [E1]."
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Fri analys med [E1]."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen. Vad gäller skattesatsen?"
        return "Svar"

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    async def _structured(messages, response_model):
        if captured is not None:
            captured.append([dict(item) for item in messages])
        if response_model is GenericPanelSynthesis:
            return GenericPanelSynthesis(
                summary="Skattesatsen är 32%.",
                claims=[
                    SynthesizedClaim(
                        claim="Kommunalskatten är 32%.",
                        evidence="Fryst underlag [E1] och expertens tur.",
                        judgment="Bedömd slutsats.",
                        evidence_refs=["E1", "E99"],
                    )
                ],
                unanswered=["Svensk lag kunde inte hämtas."],
            )
        empty = empty_research_structured(response_model)
        if empty is not None:
            raise AssertionError("research-plan models must not run on this path")
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_completer(_complete)
    set_tools_completer(_tools)
    set_structured_completer(_structured)


def _blob(messages: list[list[dict]]) -> str:
    return "\n".join(item["content"] for batch in messages for item in batch)


@pytest.mark.asyncio
async def test_acceptance_ready_frozen_set_reaches_completed(db):
    session, _factory = db
    _customer_row, run, frozen, items, attempt = await _ready_attempt(session)
    captured: list[list[dict]] = []
    _install_panel_llm(captured)

    result = await execute_generic_panel_attempt(
        session, attempt_id=attempt.id, prompts=PROMPTS
    )

    reloaded = await get_attempt(session, attempt.id)
    evidence = await get_evidence_set(session, frozen.id)
    stored = await get_attempt_result(session, attempt.id)
    assert result.status == "completed"
    assert reloaded.status == "completed"
    assert reloaded.evidence_set_id == frozen.id
    assert evidence.status == "frozen"
    assert stored is not None
    assert stored.result_type == "generic_panel"
    assert result.panel_result is not None
    assert result.panel_result.protocol == "generic_panel"
    assert result.panel_result.claims[0].evidence_refs == ["E1"]
    assert stored.evidence_refs["E1"]["item_id"] == items[0].id
    assert stored.evidence_refs["E1"]["original_evidence_id"] == items[0].original_evidence_id
    assert "E99" not in stored.evidence_refs
    assert result.panel_session_id is not None

    blob = _blob(captured)
    assert "[E1] Kommunens skattesats" in blob
    assert "[E2] Jämförelse" in blob
    assert "Source type: customer_knowledge" in blob
    assert "Provider: supabase" in blob
    assert "Locator: p. 14" in blob
    assert 'Excerpt: "skattesats 32%"' in blob
    assert "No positive evidence was found." not in blob
    assert "Known gaps (not evidence):" in blob
    assert "not_found · customer_knowledge" in blob
    assert "error · swedish_law" in blob
    assert "do-not-leak" not in blob
    assert "document_id" not in blob
    assert "ResearchRouter" in blob
    assert blob.index("[E1]") < blob.index("[E2]")

    panel = await session.get(PanelSession, result.panel_session_id)
    assert panel is not None
    phases = [row["phase"] for row in panel.transcript]
    assert "research_need" not in phases
    assert "research_plan" not in phases
    assert "opening" in phases
    assert "expert" in phases
    assert run.id == reloaded.run_id
    stored_tools = panel.config["expert_slots"][0]["tools"]
    assert stored_tools == list(DEFAULT_EXPERT_TOOL_IDS)
    assert "search_companies" not in blob
    assert "search_duckduckgo" not in blob


def _install_forbidden_tool_paths(monkeypatch) -> list[str]:
    called: list[str] = []

    async def _raise_direct(*_args, **_kwargs):
        called.append("tool-path")
        raise AssertionError("frozen-evidence path must not call a tool completion")

    monkeypatch.setattr(
        "app.services.panel.engine.complete_text_with_company_tools",
        _raise_direct,
    )
    monkeypatch.setattr(
        "app.services.dd.company_mcp.complete_text_with_company_tools",
        _raise_direct,
    )
    monkeypatch.setattr(
        "app.services.dd.company_mcp.run_company_tool_loop",
        _raise_direct,
    )
    monkeypatch.setattr("app.llm.complete_with_tools", _raise_direct)
    return called


@pytest.mark.asyncio
async def test_frozen_evidence_path_does_not_run_expert_tools(db, monkeypatch):
    session, _factory = db
    captured: list[list[dict]] = []
    _install_panel_llm(captured)
    called = _install_forbidden_tool_paths(monkeypatch)
    _customer_row, _run, _frozen, _items, attempt = await _ready_attempt(
        session, slug="tools-co"
    )
    assert PANEL_CONFIG["expert_slots"][0]["tools"]

    result = await execute_generic_panel_attempt(
        session, attempt_id=attempt.id, prompts=PROMPTS
    )

    assert result.status == "completed"
    assert called == []
    panel = await session.get(PanelSession, result.panel_session_id)
    assert panel is not None
    assert panel.config["expert_slots"][0]["tools"] == list(DEFAULT_EXPERT_TOOL_IDS)
    blob = _blob(captured)
    assert "search_companies" not in blob
    assert "lookup_company" not in blob
    assert "search_duckduckgo" not in blob
    assert "search_wiki" not in blob


@pytest.mark.asyncio
async def test_standalone_expert_complete_still_uses_company_tools(monkeypatch):
    seen: list[frozenset[str] | None] = []

    async def record(messages, *, allowed_tools=None):
        seen.append(allowed_tools)
        return "tool-path"

    monkeypatch.setattr(
        "app.services.panel.engine.complete_text_with_company_tools",
        record,
    )
    slot = PanelExpertSlot(
        slot_id="legal",
        label="Jurist",
        tools=default_expert_tools(),
    )
    text = await _expert_complete(
        [{"role": "user", "content": "hi"}],
        slot,
        allow_expert_tools=True,
    )
    assert text == "tool-path"
    assert seen == [frozenset(DEFAULT_EXPERT_TOOL_IDS)]

    async def boom(*_args, **_kwargs):
        raise AssertionError("frozen complete must not use company tools")

    monkeypatch.setattr(
        "app.services.panel.engine.complete_text_with_company_tools",
        boom,
    )

    async def _plain(messages, *, model=None):
        return "plain-path"

    set_text_completer(_plain)
    text = await _expert_complete(
        [{"role": "user", "content": "hi"}],
        slot,
        allow_expert_tools=False,
    )
    assert text == "plain-path"
    assert slot.tools == list(DEFAULT_EXPERT_TOOL_IDS)


@pytest.mark.asyncio
async def test_empty_found_set_tells_experts_no_positive_evidence(db):
    session, _factory = db
    captured: list[list[dict]] = []
    _install_panel_llm(captured)
    _customer_row, _run, _frozen, _items, attempt = await _ready_attempt(
        session,
        slug="empty-co",
        items=[
            _gap(
                need="research_1",
                status="not_found",
                source_type="customer_knowledge",
                title="Ingen träff",
            )
        ],
    )
    await execute_generic_panel_attempt(session, attempt_id=attempt.id, prompts=PROMPTS)
    blob = _blob(captured)
    assert "No positive evidence was found." in blob
    assert "[E1] " not in blob
    assert "Known gaps (not evidence):" in blob


@pytest.mark.asyncio
async def test_completed_execution_is_idempotent(db):
    session, _factory = db
    _install_panel_llm()
    _customer_row, _run, _frozen, _items, attempt = await _ready_attempt(
        session, slug="idem-co"
    )
    first = await execute_generic_panel_attempt(
        session, attempt_id=attempt.id, prompts=PROMPTS
    )
    second = await execute_generic_panel_attempt(
        session, attempt_id=attempt.id, prompts=PROMPTS
    )
    assert first.result_id == second.result_id
    assert first.panel_session_id == second.panel_session_id
    rows = list((await session.execute(select(PanelSession))).scalars().all())
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_running_double_start_rejected(db):
    session, _factory = db
    _customer_row, _run, _frozen, _items, attempt = await _ready_attempt(
        session, slug="race-co"
    )
    await claim_attempt_running(session, attempt.id)
    await session.commit()
    with pytest.raises(ExecutionStatusError, match="already in progress"):
        await execute_generic_panel_attempt(
            session, attempt_id=attempt.id, prompts=PROMPTS
        )


@pytest.mark.asyncio
async def test_failed_and_pre_ready_statuses_rejected(db):
    session, _factory = db
    customer = await _customer(session, "status-co")
    run = await create_run(
        session, customer_id=customer.id, module="dd", title="S"
    )
    created = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot=dict(PANEL_CONFIG),
    )
    with pytest.raises(ExecutionStatusError, match="status=created"):
        await execute_generic_panel_attempt(
            session, attempt_id=created.id, prompts=PROMPTS
        )
    researching = await mark_researching(session, created.id)
    with pytest.raises(ExecutionStatusError, match="status=researching"):
        await execute_generic_panel_attempt(
            session, attempt_id=researching.id, prompts=PROMPTS
        )
    failed = await fail_attempt(session, researching.id)
    with pytest.raises(ExecutionStatusError, match="failed"):
        await execute_generic_panel_attempt(
            session, attempt_id=failed.id, prompts=PROMPTS
        )


@pytest.mark.asyncio
async def test_missing_or_unfrozen_evidence_rejected(db):
    session, _factory = db
    customer = await _customer(session, "scope-co")
    run = await create_run(session, customer_id=customer.id, module="dd", title="S")
    building = await create_evidence_set(session, run_id=run.id)
    no_set = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot=dict(PANEL_CONFIG),
    )
    no_set = await mark_ready(session, no_set.id)
    with pytest.raises(ExecutionStatusError, match="no attached EvidenceSet"):
        await execute_generic_panel_attempt(
            session, attempt_id=no_set.id, prompts=PROMPTS
        )

    attached = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot=dict(PANEL_CONFIG),
        evidence_set_id=building.id,
    )
    attached.status = "ready"
    await session.flush()
    with pytest.raises(ExecutionStatusError, match="must be frozen"):
        await execute_generic_panel_attempt(
            session, attempt_id=attached.id, prompts=PROMPTS
        )

    failed_set = await create_evidence_set(session, run_id=run.id)
    failed_set.status = "failed"
    failed_attempt = await create_attempt(
        session,
        run_id=run.id,
        attempt_type="generic_panel",
        configuration_snapshot=dict(PANEL_CONFIG),
        evidence_set_id=failed_set.id,
    )
    failed_attempt.status = "ready"
    await session.flush()
    with pytest.raises(ExecutionStatusError, match="must be frozen"):
        await execute_generic_panel_attempt(
            session, attempt_id=failed_attempt.id, prompts=PROMPTS
        )


@pytest.mark.asyncio
async def test_cross_run_evidence_rejected(db):
    session, _factory = db
    _customer_a, _run_a, frozen, _items, _attempt = await _ready_attempt(
        session, slug="alpha"
    )
    customer_b = await _customer(session, "beta")
    run_b = await create_run(
        session, customer_id=customer_b.id, module="dd", title="Annat"
    )
    other = await create_attempt(
        session,
        run_id=run_b.id,
        attempt_type="generic_panel",
        configuration_snapshot=dict(PANEL_CONFIG),
    )
    other.evidence_set_id = frozen.id
    other.status = "ready"
    await session.flush()
    with pytest.raises(Exception, match="same run"):
        await execute_generic_panel_attempt(
            session, attempt_id=other.id, prompts=PROMPTS
        )


@pytest.mark.asyncio
async def test_incompatible_attempt_type_rejected(db):
    session, _factory = db
    _customer_row, _run, _frozen, _items, attempt = await _ready_attempt(
        session, slug="word-co", attempt_type="word_review"
    )
    with pytest.raises(ExecutionStatusError, match="not compatible"):
        await execute_generic_panel_attempt(
            session, attempt_id=attempt.id, prompts=PROMPTS
        )


@pytest.mark.asyncio
async def test_panel_fatal_error_fails_attempt_and_keeps_evidence_frozen(db):
    session, _factory = db
    _customer_row, _run, frozen, stored_items, attempt = await _ready_attempt(
        session, slug="boom-co"
    )

    async def boom(*_args, **_kwargs):
        raise RuntimeError("llm down")

    with pytest.raises(PanelAttemptError, match="generic_panel failed"):
        await execute_generic_panel_attempt(
            session, attempt_id=attempt.id, prompts=PROMPTS, run_panel=boom
        )
    reloaded = await get_attempt(session, attempt.id)
    evidence = await get_evidence_set(session, frozen.id)
    assert reloaded.status == "failed"
    assert evidence.status == "frozen"
    assert await get_attempt_result(session, attempt.id) is None
    with pytest.raises(ExecutionFrozenError):
        await add_evidence_items(
            session,
            evidence_set_id=frozen.id,
            items=[
                snapshot_research_evidence(
                    _found(need="research_x", excerpt="ny", locator="p9")
                )
            ],
        )
    listed = await list_evidence_items(session, frozen.id)
    assert [row.id for row in listed] == [row.id for row in stored_items]


@pytest.mark.asyncio
async def test_clone_reuses_evidence_but_gets_independent_result(db):
    session, _factory = db
    _install_panel_llm()
    _customer_row, _run, frozen, _items, attempt = await _ready_attempt(
        session, slug="clone-co"
    )
    first = await execute_generic_panel_attempt(
        session, attempt_id=attempt.id, prompts=PROMPTS
    )
    clone = await clone_attempt(
        session,
        attempt.id,
        configuration_snapshot={**PANEL_CONFIG, "brief": "Ny brief"},
    )
    await session.commit()
    second = await execute_generic_panel_attempt(
        session, attempt_id=clone.id, prompts=PROMPTS
    )
    assert clone.evidence_set_id == frozen.id
    assert clone.parent_attempt_id == attempt.id
    assert first.result_id != second.result_id
    assert first.panel_session_id != second.panel_session_id
    source = await get_attempt(session, attempt.id)
    assert source.status == "completed"
    assert source.evidence_set_id == frozen.id


@pytest.mark.asyncio
async def test_completed_result_is_immutable(db):
    session, _factory = db
    _install_panel_llm()
    _customer_row, _run, _frozen, _items, attempt = await _ready_attempt(
        session, slug="immut-co"
    )
    await execute_generic_panel_attempt(session, attempt_id=attempt.id, prompts=PROMPTS)
    with pytest.raises(Exception, match="immutable"):
        await persist_attempt_result(
            session,
            attempt_id=attempt.id,
            result_type="generic_panel",
            schema_version="1",
            payload={"schema_version": "1", "protocol": "generic_panel", "summary": "x"},
        )


@pytest.mark.asyncio
async def test_cancellation_fails_running_attempt_and_keeps_set_frozen(db):
    session, _factory = db
    _customer_row, _run, frozen, _items, attempt = await _ready_attempt(
        session, slug="cancel-co"
    )
    started = asyncio.Event()

    async def blocking(*_args, **_kwargs):
        started.set()
        await asyncio.sleep(3600)
        raise RuntimeError("unreachable")

    task = asyncio.create_task(
        execute_generic_panel_attempt(
            session,
            attempt_id=attempt.id,
            prompts=PROMPTS,
            run_panel=blocking,
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    reloaded = await get_attempt(session, attempt.id)
    evidence = await get_evidence_set(session, frozen.id)
    assert reloaded.status == "failed"
    assert evidence.status == "frozen"


def test_unknown_evidence_refs_are_filtered():
    assert filter_evidence_refs(["E1", "E99", "nope"], allowed=frozenset({"E1"})) == ["E1"]
    assert filter_evidence_refs(["E1"], allowed=None) == []


@pytest.mark.asyncio
async def test_refs_resolve_only_to_attached_frozen_items(db):
    session, _factory = db
    _install_panel_llm()
    _customer_row, _run, frozen, items, attempt = await _ready_attempt(
        session, slug="map-co"
    )
    result = await execute_generic_panel_attempt(
        session, attempt_id=attempt.id, prompts=PROMPTS
    )
    stored = await get_attempt_result(session, attempt.id)
    assert stored is not None
    mapped_ids = {row["item_id"] for row in stored.evidence_refs.values()}
    attached_ids = {row.id for row in items if row.status == "found"}
    assert mapped_ids == attached_ids
    assert result.panel_result is not None
    for ref in result.panel_result.claims[0].evidence_refs:
        assert ref in stored.evidence_refs
        assert stored.evidence_refs[ref]["item_id"] in attached_ids
    listed = await list_evidence_items(session, frozen.id)
    assert [row.ordinal for row in listed] == sorted(row.ordinal for row in listed)
