"""Expert memory lines carry source and age so the memory block stays scannable."""

from datetime import datetime, timedelta, timezone

from app.services.expert_memory_context import expert_memory_context_line
from app.services.expertgranskning.memory import ExpertMemoryHit


def _hit(text: str, *, source: str = "persona_chat", created_at: str = "",
         metadata: dict | None = None) -> ExpertMemoryHit:
    return ExpertMemoryHit(
        id="m1", text=text, source=source, metadata=metadata or {}, created_at=created_at,
    )


def test_line_carries_source_and_age():
    created = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    assert expert_memory_context_line(_hit("Kunden gillar fisk", created_at=created)) == (
        "- Kunden gillar fisk [källa: chatt, 3 dagar sedan]"
    )


def test_line_without_timestamp_keeps_source_only():
    assert expert_memory_context_line(_hit("Kunden gillar fisk")) == "- Kunden gillar fisk [källa: chatt]"


def test_unknown_source_stays_verbatim():
    assert expert_memory_context_line(_hit("Kunden gillar fisk", source="okand_kalla")) == (
        "- Kunden gillar fisk [källa: okand_kalla]"
    )


def test_research_receipt_keeps_ids_and_adds_age():
    created = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    hit = ExpertMemoryHit(
        id="m1",
        text="Fryst evidens",
        source="research_receipt",
        metadata={"knowledge_question_id": "q1", "source_attempt_id": "a1"},
        created_at=created,
    )
    line = expert_memory_context_line(hit)
    assert line == (
        "- Fryst evidens "
        "[research_receipt; knowledge_question_id=q1; source_attempt_id=a1; igår]"
    )


def test_unparseable_timestamp_is_omitted():
    assert expert_memory_context_line(_hit("Text", created_at="not-a-date")) == "- Text [källa: chatt]"
