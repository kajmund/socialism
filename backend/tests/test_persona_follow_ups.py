"""Follow-up question chips for library persona chat."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.base import Base
from app.database.models import Persona
from app.llm import set_structured_completer, set_text_streamer
from app.llm.chat import (
    format_follow_up_transcript,
    normalize_follow_up_questions,
    suggest_follow_up_questions,
)
from app.schemas.domain import EditablePersona, FollowUpQuestions, PersonaChatResponse
from app.services.persona_chat import ChatSuggestions, stream_library_chat_turn
from app.services.prompt_catalog import default_prompts
from app.services.prompt_store import ensure_default_configurations


def test_normalize_follow_up_questions_dedupes_and_caps():
    raw = [
        "  Hur mår du?  ",
        "Hur mår du?",
        "Vad tycker du om skolan i distriktet egentligen när du tänker på barnen och framtiden och allt det där som tar mer än etthundrafyrtio tecken totalt sett?",
        "",
        "Kan du ge ett exempel?",
        "En fjärde som inte ska med",
    ]
    out = normalize_follow_up_questions(raw)
    assert len(out) == 3
    assert out[0] == "Hur mår du?"
    assert len(out[1]) <= 140
    assert out[2] == "Kan du ge ett exempel?"


def test_follow_up_questions_truncates_extra_items():
    parsed = FollowUpQuestions.model_validate(
        {
            "questions": [
                "Ett?",
                "Två?",
                "Tre?",
                "Fyra?",
                "Fem som inte ska krascha?",
            ]
        }
    )
    assert parsed.questions == ["Ett?", "Två?", "Tre?", "Fyra?"]
    assert normalize_follow_up_questions(parsed.questions) == ["Ett?", "Två?", "Tre?"]


def test_follow_up_transcript_labels_speakers_by_name():
    text = format_follow_up_transcript(
        [
            ("user", "Vad tycker du om skolan?"),
            ("assistant", "Den är okej, men klasserna är för stora."),
        ],
        persona_name="Anna Lind",
    )
    assert text == (
        "Intervjuare: Vad tycker du om skolan?\n"
        "Anna Lind: Den är okej, men klasserna är för stora."
    )
    assert "Persona:" not in text
    assert "Analytiker:" not in text


def test_follow_up_transcript_in_character_uses_partner_label():
    text = format_follow_up_transcript(
        [
            ("user", "Läget?"),
            ("assistant", "Jo, just kommit från jobbet."),
        ],
        persona_name="Anna Lind",
        user_label="Samtalspartner",
    )
    assert text == (
        "Samtalspartner: Läget?\n"
        "Anna Lind: Jo, just kommit från jobbet."
    )
    assert "Intervjuare:" not in text


@pytest.mark.asyncio
async def test_suggest_follow_ups_in_character_uses_partner_voice():
    captured: list[str] = []

    async def _structured(messages: list[dict[str, str]], response_model: type):
        assert response_model is FollowUpQuestions
        captured.append(messages[0]["content"])
        return FollowUpQuestions(questions=["Läget?", "Fika?", "Vad gör du i kväll?"])

    set_structured_completer(_structured)
    try:
        questions = await suggest_follow_up_questions(
            EditablePersona(name="Anna Lind"),
            "character",
            [("user", "Hej"), ("assistant", "Tjena")],
            prompts=default_prompts("sv"),
        )
    finally:
        set_structured_completer(None)

    assert questions == ["Läget?", "Fika?", "Vad gör du i kväll?"]
    blob = captured[0]
    assert "Samtalspartner: Hej" in blob
    assert "Anna Lind: Tjena" in blob
    assert "Inte intervjufrågor" in blob
    assert "Intervjuare:" not in blob


@pytest.fixture
async def follow_up_sessions():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_factory() as seed_session:
        await ensure_default_configurations(seed_session)
        seed_session.add(
            Persona(
                id="p-follow",
                name="Test Persona",
                age=40,
                occ="Vård",
                district="Centrum",
                profile={"name": "Test Persona", "ort": "Centrum", "yrke": "Vård", "ålder": "40"},
            )
        )
        await seed_session.commit()
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_stream_library_chat_turn_yields_suggestions(follow_up_sessions):
    async def _stream(_messages: list[dict[str, str]]) -> AsyncIterator[str]:
        yield "Svar från persona."

    async def _structured(messages: list[dict[str, str]], response_model: type):
        assert response_model is FollowUpQuestions
        blob = "\n".join(m["content"] for m in messages)
        assert "Intervjuare: Hej" in blob
        assert "Test Persona: Svar från persona." in blob
        assert "du är inte Test Persona" in blob.casefold() or "inte Test Persona" in blob
        return FollowUpQuestions(questions=["Fråga A?", "Fråga B?", "Fråga C?"])

    set_text_streamer(_stream)
    set_structured_completer(_structured)
    try:
        async with follow_up_sessions() as session:
            items: list[object] = []
            async for item in stream_library_chat_turn(
                session,
                persona_id="p-follow",
                mode="interview",
                message="Hej",
            ):
                items.append(item)
        tokens = [i for i in items if isinstance(i, str)]
        done = next(i for i in items if isinstance(i, PersonaChatResponse))
        chips = next(i for i in items if isinstance(i, ChatSuggestions))
        assert tokens == ["Svar från persona."]
        assert done.reply == "Svar från persona."
        assert chips.questions == ["Fråga A?", "Fråga B?", "Fråga C?"]
    finally:
        set_text_streamer(None)
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_suggested_questions_endpoint(client):
    created = await client.post(
        "/personas",
        json={
            "name": "Chip Persona",
            "age": 41,
            "occ": "Lärare",
            "district": "Centrum",
            "quote": "saklig",
            "origin": "manuell",
        },
    )
    assert created.status_code == 201
    persona_id = created.json()["id"]

    res = await client.get(
        f"/personas/{persona_id}/suggested-questions",
        params={"mode": "interview"},
    )
    assert res.status_code == 200
    assert res.json()["questions"] == [
        "Hur påverkar det din vardag?",
        "Vad tänker du om partierna i frågan?",
        "Har du ändrat åsikt med åren?",
    ]


@pytest.mark.asyncio
async def test_suggested_questions_endpoint_omits_chips_when_llm_fails(client):
    created = await client.post(
        "/personas",
        json={
            "name": "Chip Fail",
            "age": 41,
            "occ": "Lärare",
            "district": "Centrum",
            "quote": "saklig",
            "origin": "manuell",
        },
    )
    assert created.status_code == 201
    persona_id = created.json()["id"]

    async def _boom(_messages: list[dict[str, str]], _response_model: type):
        raise RuntimeError("DeepSeek structured parse failed")

    set_structured_completer(_boom)
    try:
        res = await client.get(
            f"/personas/{persona_id}/suggested-questions",
            params={"mode": "character"},
        )
    finally:
        set_structured_completer(None)

    assert res.status_code == 200
    assert res.json()["questions"] == []
