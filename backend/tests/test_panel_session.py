"""Tests for panel engine generic_panel sessions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.llm import set_structured_completer, set_text_completer, set_tools_completer
from app.services import jobs as jobs_service
from app.services.panel.engine import (
    _expert_raise_hand,
    _expert_scratchpad,
    _expert_turn,
    _moderator_analysis,
    _moderator_opening,
    run_generic_panel,
)
from app.services.panel.schemas import PanelSessionCreate, PanelSessionConfig, PanelExpertSlot
from app.services.panel.sessions import create_panel_session, get_panel_session
from app.services.panel.research import empty_research_structured
from app.services.panel.synthesis import GenericPanelSynthesis, SynthesizedClaim
from app.services.prompt_catalog import default_prompts


@pytest.fixture
def mock_panel_llm():
    counters = {"n": 0}
    seen_tools: list[list[str]] = []

    async def _complete(messages, *, model=None):
        counters["n"] += 1
        user = messages[-1]["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            return "JA"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return f"Anteckning {counters['n']}"
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            return f"Inlägg {counters['n']}"
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Syntes: panelen enades om fortsatt DD."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen till panelen."
        if "Det här är delfråga" in user or "This is sub-question" in user:
            return f"Delfråga {counters['n']}: hur håller underlaget?"
        return f"Svar {counters['n']}"

    async def _tools(messages, tools=None):
        if tools:
            seen_tools.append(
                [item["function"]["name"] for item in tools if item.get("function")]
            )
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    async def _structured(messages, response_model):
        if response_model is GenericPanelSynthesis:
            return GenericPanelSynthesis(
                summary="Panelen bedömde att DD bör fortsätta.",
                claims=[
                    SynthesizedClaim(
                        claim="Fortsatt DD är motiverad.",
                        evidence="Experterna pekade på samma luckor i underlaget.",
                        judgment="Bedömd slutsats.",
                    )
                ],
            )
        empty_research = empty_research_structured(response_model)
        if empty_research is not None:
            return empty_research
        raise RuntimeError(f"Unexpected structured model {response_model}")

    set_text_completer(_complete)
    set_tools_completer(_tools)
    set_structured_completer(_structured)
    yield {"seen_tools": seen_tools}
    set_text_completer(None)
    set_tools_completer(None)
    set_structured_completer(None)


@pytest.mark.asyncio
async def test_panel_session_run_job(client: AsyncClient, mock_panel_llm):
    done = asyncio.Event()

    def _schedule(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule)

    create = await client.post(
        "/panel/sessions",
        json={
            "config": {
                "protocol": "generic_panel",
                "module": "politik",
                "topic": "Förvärv av målbolag X",
                "brief": "Demo-session",
                "max_rounds": 1,
                "expert_slots": [
                    {"slot_id": "fin", "label": "Finansiell analytiker", "profile": "Siffror"},
                    {"slot_id": "legal", "label": "Jurist", "profile": "Avtal"},
                ],
            }
        },
    )
    assert create.status_code == 201
    session_id = create.json()["id"]

    run = await client.post(f"/panel/sessions/{session_id}/run")
    assert run.status_code == 202
    job_id = run.json()["job_id"]

    await asyncio.wait_for(done.wait(), timeout=10)

    job = await client.get(f"/jobs/{job_id}")
    assert job.status_code == 200
    assert job.json()["status"] == "succeeded"

    session = await client.get(f"/panel/sessions/{session_id}")
    assert session.status_code == 200
    body = session.json()
    assert body["status"] == "succeeded"
    assert body["analysis"]
    factory = jobs_service.job_session_factory()
    assert factory is not None
    async with factory() as db:
        row = await get_panel_session(db, session_id)
        assert row is not None
        assert row.result is not None
        assert row.result["protocol"] == "generic_panel"
        assert body["analysis"]
        assert row.result["summary"] == "Panelen bedömde att DD bör fortsätta."
        assert row.result["summary"] != body["analysis"]
        assert row.result["claims"][0]["claim_id"] == "claim_1"
        assert row.result["claims"][0]["score"] is None
    assert len(body["transcript"]) >= 4
    assert any(t["phase"] == "opening" for t in body["transcript"])
    assert any(t["phase"] == "research_need" for t in body["transcript"])
    assert any(t["phase"] == "research_plan" for t in body["transcript"])
    assert body["research_plan"] == {"needs": []}
    assert any(t["phase"] == "expert" for t in body["transcript"])
    assert mock_panel_llm["seen_tools"]
    offered = mock_panel_llm["seen_tools"][0]
    assert "search_companies" in offered
    assert "search_duckduckgo" in offered
    assert "search_wiki" in offered

    jobs_service.set_schedule_hook(None)


@pytest.mark.asyncio
async def test_generic_panel_second_round_waits_for_moderator_question(
    client: AsyncClient, mock_panel_llm
):
    done = asyncio.Event()

    def _schedule(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule)
    create = await client.post(
        "/panel/sessions",
        json={
            "config": {
                "protocol": "generic_panel",
                "module": "expertgranskning",
                "topic": "Granska utkastet",
                "brief": "1. Är tonen rätt?\n2. Är fakta korrekta?",
                "max_rounds": 2,
                "expert_slots": [
                    {"slot_id": "fin", "label": "Finansiell analytiker", "profile": "Siffror"},
                ],
            }
        },
    )
    assert create.status_code == 201
    session_id = create.json()["id"]
    run = await client.post(f"/panel/sessions/{session_id}/run")
    assert run.status_code == 202
    await asyncio.wait_for(done.wait(), timeout=10)
    jobs_service.set_schedule_hook(None)

    session = await client.get(f"/panel/sessions/{session_id}")
    transcript = session.json()["transcript"]
    phases = [(row["phase"], row.get("round_index"), row["speaker"]) for row in transcript]
    second_question = next(
        i
        for i, (phase, round_index, speaker) in enumerate(phases)
        if phase == "sub_question" and round_index == 2 and speaker == "moderator"
    )
    first_round_two_expert = next(
        i
        for i, (phase, round_index, _speaker) in enumerate(phases)
        if phase in {"raise_hand", "expert", "scratchpad"} and round_index == 2
    )
    assert second_question < first_round_two_expert
    assert "Delfråga" in transcript[second_question]["content"]


@pytest.mark.asyncio
async def test_panel_session_config_validation():
    cfg = PanelSessionConfig(
        topic="Test",
        expert_slots=[PanelExpertSlot(slot_id="a", label="Expert A")],
    )
    assert cfg.protocol == "generic_panel"
    assert PanelSessionCreate(config=cfg).config.max_rounds == 2


@pytest.mark.asyncio
async def test_generic_panel_turns_include_brief_as_system_message():
    """Document brief must stay visible after the opening — not just topic."""
    seen: list[list[dict]] = []

    async def _complete(messages, *, model=None):
        seen.append([dict(item) for item in messages])
        user = messages[-1]["content"]
        if "JA eller NEJ" in user or "YES or NO" in user:
            return "JA"
        return "ok"

    async def _tools(messages, tools=None):
        seen.append([dict(item) for item in messages])
        return SimpleNamespace(content="ok", tool_calls=None)

    set_text_completer(_complete)
    set_tools_completer(_tools)
    document = (
        "Första raden som annars blir topic.\n\n"
        "Andra stycket måste synas i varje tur, inte bara öppningen."
    )
    try:
        prompts = default_prompts("sv")
        config = PanelSessionConfig(
            topic="Första raden som annars blir topic.",
            brief=document,
            expert_slots=[
                PanelExpertSlot(slot_id="a", label="Expert A", profile="Profil"),
            ],
        )
        slot = config.expert_slots[0]
        transcript: list = []
        await _moderator_opening(config, prompts)
        await _expert_raise_hand(slot, config, transcript, "", prompts)
        await _expert_scratchpad(slot, config, transcript, "", prompts)
        await _expert_turn(slot, config, transcript, "", prompts)
        await _moderator_analysis(config, transcript, prompts)
        assert len(seen) == 5
        for messages in seen:
            system_texts = [item["content"] for item in messages if item["role"] == "system"]
            assert document in system_texts
            assert system_texts[0] != document
    finally:
        set_text_completer(None)
        set_tools_completer(None)


def _expert_label_from_messages(messages: list[dict[str, str]]) -> str:
    for item in messages:
        if item.get("role") != "system":
            continue
        content = item["content"]
        marker = "Du deltar som "
        tail = " i en expertpanel."
        if marker in content and tail in content:
            start = content.index(marker) + len(marker)
            return content[start : content.index(tail, start)]
    return ""


def _install_generic_panel_llm(wants_turn):
    """wants_turn(label, raise_index) -> bool. raise_index is 0-based per expert."""
    raise_counts: dict[str, int] = {}

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        label = _expert_label_from_messages(messages)
        if "JA eller NEJ" in user or "YES or NO" in user:
            idx = raise_counts.get(label, 0)
            raise_counts[label] = idx + 1
            return "JA" if wants_turn(label, idx) else "NEJ"
        if "privata anteckningar" in user or "private notes" in user.lower():
            return f"Pad:{label}"
        if "offentliga inlägg" in user or "public contribution" in user.lower():
            return f"Turn:{label}"
        if "strukturerad syntes" in user or "structured synthesis" in user.lower():
            return "Syntes: panelen summerade utan tvångsdeltagande."
        if "Öppna panelen" in user or "Open the panel" in user:
            return "Välkommen till panelen."
        if "Det här är delfråga" in user or "This is sub-question" in user:
            return "Delfråga: hur håller underlaget?"
        return "Svar"

    async def _tools(messages, tools=None):
        return SimpleNamespace(content=await _complete(messages), tool_calls=None)

    set_text_completer(_complete)
    set_tools_completer(_tools)


def _generic_config(*, slots: list[PanelExpertSlot], max_rounds: int = 1) -> PanelSessionConfig:
    return PanelSessionConfig(
        protocol="generic_panel",
        module="politik",
        topic="Förvärv av målbolag X",
        brief="Demo-session",
        max_rounds=max_rounds,
        expert_slots=slots,
    )


def _turns_by_phase(transcript: list[dict], phase: str, *, round_index: int | None = None):
    return [
        row
        for row in transcript
        if row["phase"] == phase
        and (round_index is None or row.get("round_index") == round_index)
    ]


async def _run_engine_panel(factory, config: PanelSessionConfig, *, scratchpads: dict[str, str] | None = None):
    prompts = default_prompts("sv")
    async with factory() as db:
        created = await create_panel_session(db, PanelSessionCreate(config=config))
        row = await get_panel_session(db, created.id)
        assert row is not None
        if scratchpads is not None:
            row.scratchpads = dict(scratchpads)
        await run_generic_panel(db, row, prompts)
        await db.commit()
        return row


@pytest.mark.asyncio
async def test_generic_panel_raiser_gets_scratchpad_and_expert_turn(client_db):
    _client, factory = client_db
    _install_generic_panel_llm(lambda _label, _idx: True)
    row = await _run_engine_panel(
        factory,
        _generic_config(
            slots=[PanelExpertSlot(slot_id="fin", label="Raiser", profile="Siffror")]
        ),
    )
    transcript = row.transcript
    raise_hands = _turns_by_phase(transcript, "raise_hand")
    scratchpads = _turns_by_phase(transcript, "scratchpad")
    experts = _turns_by_phase(transcript, "expert")
    assert [turn["slot_id"] for turn in raise_hands] == ["fin"]
    assert [turn["content"] for turn in raise_hands] == ["JA"]
    assert [turn["slot_id"] for turn in scratchpads] == ["fin"]
    assert scratchpads[0]["content"] == "Pad:Raiser"
    assert [turn["slot_id"] for turn in experts] == ["fin"]
    assert experts[0]["content"] == "Turn:Raiser"
    assert row.scratchpads["fin"] == "Pad:Raiser"


@pytest.mark.asyncio
async def test_generic_panel_abstainer_skips_scratchpad_and_expert_turn(client_db):
    _client, factory = client_db
    _install_generic_panel_llm(lambda _label, _idx: False)
    row = await _run_engine_panel(
        factory,
        _generic_config(
            slots=[PanelExpertSlot(slot_id="legal", label="Abstainer", profile="Avtal")]
        ),
    )
    transcript = row.transcript
    raise_hands = _turns_by_phase(transcript, "raise_hand")
    assert [turn["slot_id"] for turn in raise_hands] == ["legal"]
    assert [turn["content"] for turn in raise_hands] == ["NEJ"]
    assert _turns_by_phase(transcript, "scratchpad") == []
    assert _turns_by_phase(transcript, "expert") == []
    assert row.scratchpads["legal"] == ""


@pytest.mark.asyncio
async def test_generic_panel_mixed_panel_only_raisers_keep_queue_order(client_db):
    _client, factory = client_db
    raisers = {"Andra", "Tredje"}
    _install_generic_panel_llm(lambda label, _idx: label in raisers)
    row = await _run_engine_panel(
        factory,
        _generic_config(
            slots=[
                PanelExpertSlot(slot_id="first", label="Första", profile="A"),
                PanelExpertSlot(slot_id="second", label="Andra", profile="B"),
                PanelExpertSlot(slot_id="third", label="Tredje", profile="C"),
                PanelExpertSlot(slot_id="fourth", label="Fjärde", profile="D"),
            ]
        ),
    )
    transcript = row.transcript
    raise_hands = _turns_by_phase(transcript, "raise_hand")
    assert [turn["slot_id"] for turn in raise_hands] == [
        "first",
        "second",
        "third",
        "fourth",
    ]
    assert [turn["content"] for turn in raise_hands] == ["NEJ", "JA", "JA", "NEJ"]
    assert [turn["slot_id"] for turn in _turns_by_phase(transcript, "scratchpad")] == [
        "second",
        "third",
    ]
    assert [turn["slot_id"] for turn in _turns_by_phase(transcript, "expert")] == [
        "second",
        "third",
    ]


@pytest.mark.asyncio
async def test_generic_panel_empty_raise_hand_queue_still_runs_analysis(client_db):
    _client, factory = client_db
    _install_generic_panel_llm(lambda _label, _idx: False)
    row = await _run_engine_panel(
        factory,
        _generic_config(
            slots=[
                PanelExpertSlot(slot_id="fin", label="Raiser", profile="Siffror"),
                PanelExpertSlot(slot_id="legal", label="Abstainer", profile="Avtal"),
            ],
            max_rounds=2,
        ),
    )
    transcript = row.transcript
    assert row.status == "succeeded"
    assert row.error is None
    assert row.analysis == "Syntes: panelen summerade utan tvångsdeltagande."
    assert row.result["protocol"] == "generic_panel"
    assert row.result["claims"] == []
    assert row.result["summary"] != row.analysis
    assert _turns_by_phase(transcript, "opening")
    assert _turns_by_phase(transcript, "sub_question", round_index=2)
    assert len(_turns_by_phase(transcript, "raise_hand", round_index=1)) == 2
    assert len(_turns_by_phase(transcript, "raise_hand", round_index=2)) == 2
    assert _turns_by_phase(transcript, "scratchpad") == []
    assert _turns_by_phase(transcript, "expert") == []
    assert any(turn["phase"] == "analysis" for turn in transcript)


@pytest.mark.asyncio
async def test_generic_panel_expert_can_abstain_then_raise_later_round(client_db):
    _client, factory = client_db
    _install_generic_panel_llm(lambda _label, idx: idx == 1)
    row = await _run_engine_panel(
        factory,
        _generic_config(
            slots=[PanelExpertSlot(slot_id="fin", label="Raiser", profile="Siffror")],
            max_rounds=2,
        ),
    )
    transcript = row.transcript
    raise_hands = _turns_by_phase(transcript, "raise_hand")
    assert [turn["round_index"] for turn in raise_hands] == [1, 2]
    assert [turn["content"] for turn in raise_hands] == ["NEJ", "JA"]
    assert _turns_by_phase(transcript, "scratchpad", round_index=1) == []
    assert _turns_by_phase(transcript, "expert", round_index=1) == []
    scratch_r2 = _turns_by_phase(transcript, "scratchpad", round_index=2)
    expert_r2 = _turns_by_phase(transcript, "expert", round_index=2)
    assert [turn["slot_id"] for turn in scratch_r2] == ["fin"]
    assert [turn["slot_id"] for turn in expert_r2] == ["fin"]
    assert row.status == "succeeded"


@pytest.mark.asyncio
async def test_generic_panel_abstainer_scratchpad_is_not_modified(client_db):
    _client, factory = client_db
    _install_generic_panel_llm(lambda label, _idx: label == "Raiser")
    seeded = {"legal": "ORIGINAL PAD", "fin": ""}
    row = await _run_engine_panel(
        factory,
        _generic_config(
            slots=[
                PanelExpertSlot(slot_id="fin", label="Raiser", profile="Siffror"),
                PanelExpertSlot(slot_id="legal", label="Abstainer", profile="Avtal"),
            ]
        ),
        scratchpads=seeded,
    )
    assert row.scratchpads["legal"] == "ORIGINAL PAD"
    assert row.scratchpads["fin"] == "Pad:Raiser"
    assert [turn["slot_id"] for turn in _turns_by_phase(row.transcript, "scratchpad")] == [
        "fin"
    ]


