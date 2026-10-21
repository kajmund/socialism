"""Swedish golden conversation scenarios for Fas 1 live speech."""

from __future__ import annotations

from time import perf_counter

from app.services.conversation_controller import ConversationController, ConversationEvent
from app.services.latency_stats import percentiles
from app.services.live_speech_backchannel import classify_utterance, utterance_barge

SCENARIOS: list[tuple[str, str, str, str]] = [
    ("backchannel_mm", "mm", "backchannel", "ignore"),
    ("backchannel_ja", "ja", "backchannel", "ignore"),
    ("backchannel_precis", "precis", "backchannel", "ignore"),
    ("backchannel_just_det", "just det", "backchannel", "ignore"),
    ("backchannel_jajust", "jajust", "backchannel", "ignore"),
    ("backchannel_ja_precis", "ja precis", "backchannel", "ignore"),
    ("stop_word", "stopp", "interruption", "barge"),
    ("no_word", "nej", "interruption", "barge"),
    ("wait_word", "vänta", "interruption", "barge"),
    ("english_stop", "stop", "interruption", "barge"),
    ("amend_fast", "fast det gäller avtalet", "amend", "barge"),
    ("amend_men", "men läs om förlängningen", "amend", "barge"),
    ("new_question", "vad betyder det?", "new_question", "barge"),
    ("new_question_hur", "hur länge gäller avtalet", "new_question", "barge"),
    ("short_nej_not_ignored", "nej", "interruption", "barge"),
    ("repeated_stop", "stopp stopp", "interruption", "barge"),
    ("echo_of_reply", "omsättningen är tolv miljoner", "backchannel", "ignore"),
    ("uncertain_long", "vi diskuterade avtalet igår", "uncertain", "wait"),
    ("double_question_first", "kan du öppna avtalet", "new_question", "barge"),
    ("correction_alltså", "alltså tre år", "amend", "barge"),
]


def test_golden_utterances_match_barge_policy() -> None:
    assert len(SCENARIOS) >= 20
    for _name, text, kind, action in SCENARIOS:
        echoed = "Omsättningen är tolv miljoner i år." if "echo" in _name else None
        assert classify_utterance(text, echoed=echoed) == kind, _name
        expected_action = action if action != "wait" else "wait"
        if kind in {"interruption", "new_question", "amend"}:
            expected_action = "barge"
        elif kind == "backchannel":
            expected_action = "ignore"
        assert utterance_barge(text, final=False, echoed=echoed)[0] == expected_action, _name


def test_golden_turn_sequences() -> None:
    cases = [
        ("overlap_then_stop", ["ai_speak", "user_vad_start", "barge_interrupt"], "AI_INTERRUPTED"),
        ("backchannel_keeps_floor", ["ai_speak", "barge_backchannel"], "AI_SPEAKING"),
        ("amend_keeps_turn", ["user_vad_commit", "user_final", "ai_speak", "barge_amend"], "AI_THINKING"),
        ("reset_fail_closed", ["ai_speak", "session_reset"], "IDLE"),
        ("paused_then_think", ["user_vad_start", "user_vad_commit"], "AI_THINKING"),
        ("rapid_switch", ["ai_speak", "user_vad_start", "user_vad_commit"], "AI_THINKING"),
        ("idle_after_reply", ["ai_speak", "ai_idle"], "IDLE"),
        ("thinking_during_research", ["ai_think"], "AI_THINKING"),
        ("double_question_turn", ["user_vad_commit", "user_final", "cancel", "user_vad_commit", "user_final"], "AI_THINKING"),
        ("stale_cancel_ignored", ["user_vad_commit", "user_final", "cancel"], "AI_THINKING"),
    ]
    assert len(SCENARIOS) + len(cases) >= 30
    for name, kinds, expected in cases:
        controller = ConversationController()
        turn = "t1"
        seq = 0
        for kind in kinds:
            if kind == "user_vad_commit":
                seq += 1
            event_turn = turn if kind in {"ai_speak", "ai_think", "barge_amend", "barge_interrupt", "barge_backchannel", "ai_idle"} else None
            if kind == "user_final":
                event_turn = turn
            if kind == "cancel" and name == "stale_cancel_ignored":
                controller.handle(ConversationEvent(kind="cancel", turn_id="old"))
                continue
            if kind == "cancel":
                event_turn = turn
            controller.handle(
                ConversationEvent(kind=kind, turn_id=event_turn, sequence=seq if kind in {"user_vad_commit", "user_final"} else None),
            )
            if kind == "cancel":
                turn = "t2"
        assert controller.state == expected, name


def test_rule_classification_is_under_a_millisecond() -> None:
    samples: list[float] = []
    texts = ("mm", "precis", "stopp", "nej", "vänta", "fast det", "vad betyder det?")
    for _ in range(400):
        started = perf_counter()
        for text in texts:
            classify_utterance(text)
            utterance_barge(text, final=False)
        samples.append((perf_counter() - started) * 1000 / len(texts))
    p50, p95, p99 = percentiles(samples)
    assert p50 < 1
    assert p95 < 1
    assert p99 < 2
