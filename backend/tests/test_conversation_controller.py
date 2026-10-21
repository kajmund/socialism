import random

from app.services.conversation_controller import (
    ConversationController,
    ConversationEvent,
    EventKind,
    wire_state,
)

_KINDS: tuple[EventKind, ...] = (
    "user_vad_start",
    "user_vad_commit",
    "user_partial",
    "user_final",
    "ai_think",
    "ai_speak",
    "ai_idle",
    "barge_interrupt",
    "barge_amend",
    "barge_backchannel",
    "cancel",
    "session_reset",
)


def test_controller_starts_idle_and_projects_wire_state():
    controller = ConversationController()
    assert controller.state == "IDLE"
    assert wire_state(controller.state) == "listening"


def test_user_speaking_then_commit_reaches_thinking():
    controller = ConversationController()
    controller.user_speaking()
    assert controller.state == "USER_SPEAKING"
    controller.user_committed()
    assert controller.state == "AI_THINKING"
    controller.ai_speaking()
    assert wire_state(controller.state) == "speaking"


def test_interrupt_during_ai_marks_overlap_and_interruption():
    controller = ConversationController()
    controller.ai_speaking()
    controller.user_speaking()
    assert controller.state == "OVERLAPPING"
    controller.ai_interrupted()
    assert controller.state == "AI_INTERRUPTED"


def test_tracks_floor_user_speech_and_model_work_separately():
    controller = ConversationController()
    controller.handle(ConversationEvent(kind="ai_think", turn_id="t1"))
    controller.handle(ConversationEvent(kind="ai_speak", turn_id="t1"))
    assert controller.floor == "ai"
    assert controller.model_work == "speaking"
    assert controller.user_speech == "silent"
    snapshot = controller.handle(ConversationEvent(kind="user_vad_start", utterance_id="u1"))
    assert snapshot.state == "OVERLAPPING"
    assert snapshot.user_speech == "speaking"
    assert snapshot.model_work == "speaking"


def test_stale_turn_cannot_interrupt_a_newer_turn():
    controller = ConversationController()
    controller.handle(ConversationEvent(kind="user_vad_commit", sequence=1))
    controller.handle(ConversationEvent(kind="user_final", turn_id="new", sequence=1))
    rejected = controller.handle(
        ConversationEvent(kind="cancel", turn_id="old"),
    )
    assert rejected.accepted is False
    assert rejected.ignore_reason == "stale_turn"
    assert controller.turn_id == "new"
    assert controller.state == "AI_THINKING"


def test_late_final_after_a_newer_commit_is_ignored():
    controller = ConversationController()
    controller.handle(ConversationEvent(kind="user_vad_start", utterance_id="a"))
    controller.handle(ConversationEvent(kind="user_vad_commit", sequence=1))
    controller.handle(ConversationEvent(kind="user_vad_start", utterance_id="b"))
    controller.handle(ConversationEvent(kind="user_vad_commit", sequence=2))
    late = controller.handle(ConversationEvent(kind="user_final", sequence=1, turn_id="old"))
    assert late.accepted is False
    assert late.ignore_reason == "stale_final"
    current = controller.handle(ConversationEvent(kind="user_final", sequence=2, turn_id="new"))
    assert current.accepted is True
    assert controller.turn_id == "new"


def test_duplicate_partial_and_duplicate_final_are_ignored():
    controller = ConversationController()
    controller.handle(ConversationEvent(kind="user_vad_start", utterance_id="u"))
    first = controller.handle(
        ConversationEvent(kind="user_partial", utterance_id="u", sequence=3),
    )
    again = controller.handle(
        ConversationEvent(kind="user_partial", utterance_id="u", sequence=3),
    )
    assert first.accepted is True
    assert again.accepted is False
    assert again.ignore_reason == "duplicate_partial"
    controller.handle(ConversationEvent(kind="user_vad_commit", sequence=4))
    final = controller.handle(ConversationEvent(kind="user_final", sequence=4, turn_id="t"))
    duplicate = controller.handle(
        ConversationEvent(kind="user_final", sequence=4, turn_id="t"),
    )
    assert final.accepted is True
    assert duplicate.accepted is False
    assert duplicate.ignore_reason == "duplicate_final"


def test_backchannel_does_not_take_the_floor():
    controller = ConversationController()
    controller.handle(ConversationEvent(kind="ai_speak", turn_id="t"))
    snapshot = controller.handle(ConversationEvent(kind="barge_backchannel", turn_id="t"))
    assert snapshot.accepted is True
    assert snapshot.state == "AI_SPEAKING"
    assert snapshot.floor == "ai"


def test_amend_keeps_the_turn_and_model_work():
    controller = ConversationController()
    controller.handle(ConversationEvent(kind="user_vad_commit", sequence=1))
    controller.handle(ConversationEvent(kind="user_final", turn_id="t", sequence=1))
    controller.handle(ConversationEvent(kind="ai_speak", turn_id="t"))
    snapshot = controller.handle(ConversationEvent(kind="barge_amend", turn_id="t"))
    assert snapshot.accepted is True
    assert snapshot.turn_id == "t"
    assert snapshot.model_work == "thinking"
    assert snapshot.floor == "none"
    assert snapshot.state != "AI_INTERRUPTED"


def test_interrupt_from_idle_is_a_noop():
    controller = ConversationController()
    snapshot = controller.handle(ConversationEvent(kind="barge_interrupt"))
    assert snapshot.accepted is True
    assert snapshot.state == "IDLE"


def test_session_reset_is_fail_closed_and_bumps_epoch():
    controller = ConversationController()
    controller.handle(ConversationEvent(kind="ai_speak", turn_id="t"))
    first = controller.handle(ConversationEvent(kind="session_reset"))
    second = controller.handle(ConversationEvent(kind="session_reset"))
    assert first.state == "IDLE"
    assert first.turn_id is None
    assert first.session_epoch == 1
    assert second.session_epoch == 2
    assert controller.model_work == "idle"


def test_stale_utterance_partial_is_ignored():
    controller = ConversationController()
    controller.handle(ConversationEvent(kind="user_vad_start", utterance_id="one"))
    stale = controller.handle(
        ConversationEvent(kind="user_partial", utterance_id="zero", sequence=1),
    )
    assert stale.accepted is False
    assert stale.ignore_reason == "stale_utterance"


def test_model_based_random_sequences_preserve_invariants():
    rng = random.Random(400)
    for _ in range(200):
        controller = ConversationController()
        for _step in range(24):
            kind = rng.choice(_KINDS)
            turn = rng.choice((None, "t1", "t2", controller.turn_id))
            utterance = rng.choice((None, "u1", "u2", controller.utterance_id))
            sequence = rng.choice((None, 1, 2, controller._commit_seq))
            before_turn = controller.turn_id
            before_epoch = controller.session_epoch
            before_state = controller.state
            snapshot = controller.handle(
                ConversationEvent(
                    kind=kind,
                    turn_id=turn,
                    utterance_id=utterance,
                    sequence=sequence,
                )
            )
            if snapshot.ignore_reason == "stale_turn":
                assert controller.turn_id == before_turn
            if kind == "session_reset":
                assert snapshot.accepted is True
                assert controller.state == "IDLE"
                assert controller.session_epoch == before_epoch + 1
            if kind == "barge_backchannel" and snapshot.accepted:
                assert controller.state == before_state
            assert controller.floor in {"none", "user", "ai"}
            assert controller.user_speech in {"silent", "speaking", "paused"}
            assert controller.model_work in {"idle", "thinking", "speaking"}
