"""Unit tests for the SME group voice state machine."""

from __future__ import annotations

import asyncio

from app.services.sme_group_voice import GroupVoiceSession
from app.services.sme_group_voice_names import correct_names
from app.services.sme_group_voice_turns import group_history, group_note, plain_group_reply


def _session() -> GroupVoiceSession:
    return GroupVoiceSession(
        panel_id="1",
        member_ids={"a", "b", "c"},
        member_names={"a": "Anna", "b": "Bo", "c": "Cecilia"},
    )


def test_name_address_uses_token_boundary():
    session = _session()
    assert session.address_by_name("Hej Bo, vad tycker du?") == "b"
    assert session.address_by_name("bolaget har problem") is None
    assert session.address_by_name("Anna och Cecilia") == "a"


def test_misheard_name_addresses_the_expert():
    session = GroupVoiceSession(
        panel_id="1",
        member_ids={"k", "s"},
        member_names={"k": "Klas Månsson", "s": "Cecilia Berg"},
    )
    assert session.address_by_name("Hej Claes, vad tycker du?") == "k"
    assert session.address_by_name("Carl sa inget") is None
    assert session.address_by_name("Sesilia, en kommentar") == "s"
    assert session.address_by_name("klasser av avtal") is None
    karl = GroupVoiceSession(panel_id="1", member_ids={"k"}, member_names={"k": "Karl"})
    assert karl.address_by_name("Hej Carl") == "k"


def test_ambiguous_mishearing_does_not_pick_an_expert():
    session = GroupVoiceSession(
        panel_id="1",
        member_ids={"k", "c"},
        member_names={"k": "Klas", "c": "Claes"},
    )
    assert session.address_by_name("Hej Claes") is None


def test_only_the_expert_who_wants_to_speak_raises_a_hand():
    session = _session()

    class Reply:
        def __init__(self, answers: dict) -> None:
            self.answers = answers

    class Jev:
        async def ask(self, **_kwargs):
            return Reply({"a": {"noul": 0.8}, "b": {"noul": 0.2}, "c": {"noul": 0.1}})

    winner = asyncio.run(session.decide_raise_hands("Vad tror ni?", jev=Jev()))  # type: ignore[arg-type]
    assert winner == "a"
    assert session.hands == {"a"}


def test_the_closest_expert_speaks_even_without_a_raised_hand():
    session = _session()

    class Reply:
        def __init__(self, answers: dict) -> None:
            self.answers = answers

    class Jev:
        async def ask(self, **_kwargs):
            return Reply({"a": {"noul": 0.1}, "b": {"noul": 0.2}, "c": {"noul": 0.4}})

    winner = asyncio.run(session.decide_raise_hands("Hej", jev=Jev()))  # type: ignore[arg-type]
    assert winner == "c"
    assert session.hands == {"c"}


def test_experts_close_to_the_point_raise_a_hand():
    session = _session()

    class Reply:
        def __init__(self, answers: dict) -> None:
            self.answers = answers

    class Jev:
        async def ask(self, **_kwargs):
            return Reply({"a": {"noul": 0.35}, "b": {"noul": 0.30}, "c": {"noul": 0.10}})

    winner = asyncio.run(session.decide_raise_hands("Vad tror ni?", jev=Jev()))  # type: ignore[arg-type]
    assert winner == "a"
    assert session.hands == {"a", "b"}


def test_automatic_floor_keeps_the_raised_hand():
    session = _session()
    session.raise_hand("a")
    session.grant_floor("a", lower_hand=False)
    assert session.floor == "a"
    assert session.floor_reason == "hand"
    assert "a" in session.hands


def test_the_speaker_is_told_they_raised_a_hand():
    session = _session()
    session.raise_hand("a")
    session.raise_hand("b")
    session.grant_floor("a", lower_hand=False)
    note = group_note(session)
    assert "något att tillägga om det som just sades" in note
    assert "Nämn inte handen" in note
    assert "Byt inte ämne" in note
    assert "Bo har också" not in note


def test_delivery_tags_stay_out_of_the_group_reply():
    assert plain_group_reply("[happy] Jag ville bara säga en sak. [laughs]") == "Jag ville bara säga en sak."


def test_a_named_speaker_is_not_told_they_raised_a_hand():
    session = _session()
    session.grant_floor("a")
    assert session.floor_reason == "name"
    assert "räckt upp handen" not in group_note(session)


def test_misheard_name_is_rewritten_to_the_expert_spelling():
    assert correct_names("Hej Claes, vad tycker du?", {"k": "Klas Månsson"}) == "Hej Klas, vad tycker du?"


def test_group_history_keeps_other_experts_named():
    session = GroupVoiceSession(
        panel_id="1",
        member_ids={"a", "b"},
        member_names={"a": "Klas", "b": "Sara"},
    )
    history = group_history(
        session,
        "a",
        [("user", None, "Hej"), ("assistant", "b", "Jag håller med"), ("assistant", "a", "Inte jag")],
    )
    assert history[0] == ("user", "Hej", None, None)
    assert history[1] == ("user", "Sara: Jag håller med", None, None)
    assert history[2] == ("assistant", "Inte jag", None, None)


def test_the_hand_comes_down_when_the_speaker_is_done():
    session = _session()
    session.raise_hand("a")
    session.raise_hand("b")
    session.grant_floor("a", lower_hand=False)
    assert "a" in session.hands
    session.release_floor()
    assert session.floor is None
    assert "a" not in session.hands
    assert "b" in session.hands


def test_grant_and_release_floor():
    session = _session()
    session.raise_hand("a")
    assert "a" in session.hands
    session.grant_floor("a")
    assert session.floor == "a"
    assert "a" not in session.hands
    session.release_floor()
    assert session.floor is None


def test_hand_while_someone_else_speaks():
    session = _session()
    session.grant_floor("a")
    session.raise_hand("b")
    assert session.floor == "a"
    assert "b" in session.hands
    session.raise_hand("a")  # already speaking
    assert "a" not in session.hands


def test_tool_result_raises_hand_and_marks_source():
    session = _session()
    session.attach_tool_result("b", "search", {"ok": True}, "found it")
    assert "b" in session.hands
    assert session.source_checked.get("b") is True
    assert len(session.shared_results) == 1
    snap = session.snapshot()
    assert snap["source_checked"] == ["b"]
    assert snap["shared_result_count"] == 1


def test_group_voice_prompt_is_loaded_for_the_customer(monkeypatch):
    from app.api import sme_group_voice_ws as ws

    seen: dict[str, object] = {}

    async def fake_require(_session, *, customer_id, module, language):
        seen["customer_id"] = customer_id
        seen["module"] = module
        seen["language"] = language
        return {"sme.group_voice.raise_hand": "Har {name} något att säga?"}

    class _Db:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr(ws, "require_active_prompts", fake_require)
    monkeypatch.setattr(ws.jobs_service, "job_session_factory", lambda: (lambda: _Db()))
    text = asyncio.run(
        ws._prompt("sme.group_voice.raise_hand", customer_id=7, language="sv")
    )
    assert text == "Har {name} något att säga?"
    assert seen == {"customer_id": 7, "module": "dd", "language": "sv"}


def test_failed_hand_decision_leaves_the_call_open():
    from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime, GroupVoiceAudioScope

    session = _session()
    events: list[dict] = []

    async def emit(payload: dict) -> None:
        events.append(payload)

    async def emit_audio(_pcm: bytes) -> None:
        return None

    async def boom(_text: str) -> None:
        raise RuntimeError("missing prompt")

    runtime = GroupVoiceAudioRuntime(
        session,
        GroupVoiceAudioScope(language="sv", voice_ids={}),
        emit_json=emit,
        emit_audio=emit_audio,
        on_unaddressed=boom,
    )

    async def run() -> None:
        await runtime._apply_final("Vad tror ni?", "1")
        assert runtime._hand_task is not None
        await runtime._hand_task
        await runtime._apply_final("En gång till", "2")

    asyncio.run(run())
    finals = [event["text"] for event in events if event.get("type") == "transcript.final"]
    assert finals == ["Vad tror ni?", "En gång till"]
    assert any(event.get("detail") == "hand_decision_failed" for event in events)
    assert any(event.get("type") == "listening" for event in events)


def test_speech_while_the_floor_is_held_still_raises_hands():
    from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime, GroupVoiceAudioScope

    session = _session()
    session.grant_floor("a")
    heard: list[str] = []

    async def emit(_payload: dict) -> None:
        return None

    async def emit_audio(_pcm: bytes) -> None:
        return None

    async def on_unaddressed(text: str) -> None:
        heard.append(text)

    runtime = GroupVoiceAudioRuntime(
        session,
        GroupVoiceAudioScope(language="sv", voice_ids={}),
        emit_json=emit,
        emit_audio=emit_audio,
        on_unaddressed=on_unaddressed,
    )

    async def run() -> None:
        await runtime._apply_final("En sak till", "1")
        assert runtime._hand_task is not None
        await runtime._hand_task

    asyncio.run(run())
    assert heard == ["En sak till"]
    assert session.floor == "a"


def test_a_new_utterance_drops_a_hand_that_no_longer_applies():
    session = _session()
    session.raise_hand("b")

    class Reply:
        def __init__(self, answers: dict) -> None:
            self.answers = answers

    class Jev:
        async def ask(self, **_kwargs):
            return Reply({"a": {"noul": 0.4}, "b": {"noul": 0.05}, "c": {"noul": 0.05}})

    asyncio.run(session.decide_raise_hands("Nytt ämne", jev=Jev()))  # type: ignore[arg-type]
    assert session.hands == {"a"}


def test_a_tool_result_hand_survives_the_next_utterance():
    session = _session()
    session.attach_tool_result("b", "search", {"ok": True}, "found it")

    class Reply:
        def __init__(self, answers: dict) -> None:
            self.answers = answers

    class Jev:
        async def ask(self, **_kwargs):
            return Reply({"a": {"noul": 0.4}, "b": {"noul": 0.05}, "c": {"noul": 0.05}})

    asyncio.run(session.decide_raise_hands("Nytt ämne", jev=Jev()))  # type: ignore[arg-type]
    assert "b" in session.hands
    assert "a" in session.hands


def test_unspoken_floor_is_released():
    from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime, GroupVoiceAudioScope

    session = _session()
    session.grant_floor("a")
    events: list[dict] = []

    async def emit(payload: dict) -> None:
        events.append(payload)

    async def emit_audio(_pcm: bytes) -> None:
        return None

    runtime = GroupVoiceAudioRuntime(
        session,
        GroupVoiceAudioScope(language="sv", voice_ids={}),
        emit_json=emit,
        emit_audio=emit_audio,
    )
    asyncio.run(runtime.release_unspoken("a"))
    assert session.floor is None
    assert any(event.get("type") == "assistant.done" for event in events)


def test_snapshot_includes_floor_name():
    session = _session()
    session.grant_floor("c")
    snap = session.snapshot()
    assert snap["floor"] == "c"
    assert snap["floor_name"] == "Cecilia"
    assert snap["hands"] == []


def test_group_voice_uses_the_same_vad_settings_as_a_single_expert():
    from app.config import settings
    from app.live_speech_settings import vad_client_config

    config = vad_client_config(settings)
    assert config == {
        "threshold": settings.live_speech_vad_threshold,
        "preroll_ms": settings.live_speech_vad_preroll_ms,
        "hangover_ms": settings.live_speech_vad_hangover_ms,
        "min_speech_ms": settings.live_speech_vad_min_speech_ms,
        "urgent_ms": settings.live_speech_vad_urgent_ms,
    }


def test_talking_over_an_expert_stops_them_and_waits_for_the_rest():
    from app.services.openai_live_transcription import TranscriptEvent
    from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime, GroupVoiceAudioScope

    session = _session()
    session.grant_floor("a", lower_hand=False)
    session.raise_hand("a")
    events: list[dict] = []
    heard: list[str] = []

    async def emit(payload: dict) -> None:
        events.append(payload)

    async def emit_audio(_pcm: bytes) -> None:
        return None

    async def on_unaddressed(text: str) -> None:
        heard.append(text)

    runtime = GroupVoiceAudioRuntime(
        session,
        GroupVoiceAudioScope(language="sv", voice_ids={}),
        emit_json=emit,
        emit_audio=emit_audio,
        on_unaddressed=on_unaddressed,
    )

    async def run() -> None:
        await runtime._on_transcript(TranscriptEvent(kind="partial", text="vänta"))
        assert session.floor is None
        assert heard == []
        await runtime._on_transcript(TranscriptEvent(kind="final", text="vänta vad gäller 36 paragrafen"))
        assert runtime._hand_task is not None
        await runtime._hand_task

    asyncio.run(run())
    assert any(event.get("type") == "assistant.cancelled" for event in events)
    assert heard == ["vänta vad gäller 36 paragrafen"]


def test_a_short_acknowledgement_does_not_stop_the_speaker():
    from app.services.openai_live_transcription import TranscriptEvent
    from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime, GroupVoiceAudioScope

    session = _session()
    session.grant_floor("a")
    events: list[dict] = []

    async def emit(payload: dict) -> None:
        events.append(payload)

    async def emit_audio(_pcm: bytes) -> None:
        return None

    runtime = GroupVoiceAudioRuntime(
        session,
        GroupVoiceAudioScope(language="sv", voice_ids={}),
        emit_json=emit,
        emit_audio=emit_audio,
    )
    asyncio.run(runtime._on_transcript(TranscriptEvent(kind="final", text="mm")))
    assert session.floor == "a"
    assert not any(event.get("type") == "assistant.cancelled" for event in events)


def test_the_open_agreement_is_given_to_the_speaker(monkeypatch):
    from types import SimpleNamespace

    from app.schemas.workspace import WorkspaceState
    from app.services.sme_group_voice_turns import run_floor_turn

    state = WorkspaceState()
    seen: dict = {}

    async def load(_factory, **kwargs):
        assert kwargs["workspace_id"] == "ws-1"
        assert kwargs["expert_id"] == "a"
        return state, "Dokument som visas:\n\nAvtal.pdf\nUppsägningstid sex månader."

    async def execute(_factory, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(reply="Sex månader.")

    async def lines(*_args, **_kwargs):
        return []

    async def accept(*_args, **_kwargs):
        return ("token", 1)

    async def store(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.sme_group_voice_turns.load_open_workspace", load)
    monkeypatch.setattr("app.services.sme_group_voice_turns.execute_expert_turn", execute)
    monkeypatch.setattr("app.services.sme_group_voice_turns._panel_lines", lines)
    monkeypatch.setattr("app.services.sme_group_voice_turns._accept", accept)
    monkeypatch.setattr("app.services.sme_group_voice_turns._store_exchange", store)
    session = GroupVoiceSession(panel_id="1", member_ids={"a"}, member_names={"a": "Anna"})
    session.grant_floor("a")
    spoken: list[tuple[str, str]] = []

    class Runtime:
        async def speak_as(self, persona_id, text):
            spoken.append((persona_id, text))

        async def release_unspoken(self, _persona_id):
            return None

    asyncio.run(run_floor_turn(
        session=session,
        runtime=Runtime(),  # type: ignore[arg-type]
        user_text="Vad står i avtalet?",
        user_id="user-one",
        customer_id=1,
        workspace_id="ws-1",
    ))
    assert seen["workspace_id"] == "ws-1"
    assert seen["workspace_state"] is state
    assert seen["group_note"].startswith("Du sitter i en expertpanel")
    assert spoken == [("a", "Sex månader.")]


def test_one_speaker_opens_the_agreement_once(monkeypatch):
    from types import SimpleNamespace

    from app.services.sme_group_voice_runtime import GroupVoiceAudioRuntime
    from app.services.sme_group_voice_turns import run_floor_turn

    opened: list[dict] = []

    async def load(_factory, **_kwargs):
        return None

    async def execute(_factory, **kwargs):
        await kwargs["on_client_tools"]([
            {"name": "show_document", "arguments": {"source_id": "avtal"}},
            {"name": "show_document", "arguments": {"source_id": "avtal"}},
        ])
        return SimpleNamespace(reply="Jag öppnar det.")

    async def lines(*_args, **_kwargs):
        return []

    async def accept(*_args, **_kwargs):
        return ("token", 1)

    async def store(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.sme_group_voice_turns.load_open_workspace", load)
    monkeypatch.setattr("app.services.sme_group_voice_turns.execute_expert_turn", execute)
    monkeypatch.setattr("app.services.sme_group_voice_turns._panel_lines", lines)
    monkeypatch.setattr("app.services.sme_group_voice_turns._accept", accept)
    monkeypatch.setattr("app.services.sme_group_voice_turns._store_exchange", store)
    session = GroupVoiceSession(panel_id="1", member_ids={"a"}, member_names={"a": "Anna"})
    session.grant_floor("a")

    class Runtime:
        async def speak_as(self, _persona_id, _text):
            return None

        async def release_unspoken(self, _persona_id):
            return None

        async def _emit_json(self, payload):
            opened.append(payload)

        emit_workspace_tool = GroupVoiceAudioRuntime.emit_workspace_tool

    asyncio.run(run_floor_turn(
        session=session,
        runtime=Runtime(),  # type: ignore[arg-type]
        user_text="Öppna avtalet",
        user_id="user-one",
        customer_id=1,
        workspace_id="ws-1",
    ))
    assert opened == [{
        "type": "workspace.tool",
        "name": "show_document",
        "arguments": {"source_id": "avtal"},
    }]
