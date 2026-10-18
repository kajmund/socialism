from app.services.conversation_controller import (
    ConversationController,
    wire_state,
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
