"""Answer lookup: multiple answers, old answers, superseded facts and tenant isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.knowledge.scope import customer_scope
from app.services.knowledge.scope import shared_scope
from app.services.overgraph.catalogs import require_knowledge
from app.services.overgraph.publish import AnswerPublish, publish_answer_fact
from app.services.overgraph.answers import (
    ANSWER_PREDICATE,
    answer_facts,
    current_fact,
    find_question,
)
from app.services.overgraph.research import update_fact

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
QUESTION = "Vad gäller uppsägningstiden?"
CUSTOMER = 7


def _publish(*, fact_id: str, identity: str, text: str, customer_id: int = CUSTOMER) -> None:
    publish_answer_fact(
        require_knowledge(),
        AnswerPublish(
            question_id=f"question-{customer_id}",
            question_text=QUESTION,
            scope=customer_scope(customer_id),
            identity=identity,
            evidence_set_id=f"set-{identity}",
            fact_id=fact_id,
            attributes={"knowledge_module": "dd", "answer_status": "sufficient"},
            basis=[{"title": text}],
            assessment={"sufficient": True},
            dependency_ids=(),
        ),
    )


def test_canonical_question_id_is_a_stable_entry_point():
    _publish(fact_id="fact-a", identity="a", text="Svar A")
    catalog = require_knowledge()
    question = find_question(catalog, f"question-{CUSTOMER}", CUSTOMER)
    assert question is not None
    facts = answer_facts(catalog, f"question-{CUSTOMER}", CUSTOMER)
    assert [fact.id for fact in facts] == ["fact-a"]
    assert facts[0].predicate == ANSWER_PREDICATE


def test_newest_answer_is_selected_first_when_several_answers_exist():
    _publish(fact_id="fact-older", identity="older", text="Äldre svar")
    _publish(fact_id="fact-newer", identity="newer", text="Nyare svar")
    catalog = require_knowledge()
    facts = answer_facts(catalog, f"question-{CUSTOMER}", CUSTOMER)
    assert [fact.id for fact in facts] == ["fact-newer", "fact-older"]


def test_superseded_answer_is_not_returned():
    _publish(fact_id="fact-live", identity="live", text="Live")
    _publish(fact_id="fact-dead", identity="dead", text="Död")
    catalog = require_knowledge()
    update_fact(catalog, "fact-dead", status="superseded")
    facts = answer_facts(catalog, f"question-{CUSTOMER}", CUSTOMER)
    assert [fact.id for fact in facts] == ["fact-live"]


def test_answer_outside_its_validity_window_is_not_current():
    _publish(fact_id="fact-future", identity="future", text="Framtid")
    _publish(fact_id="fact-past", identity="past", text="Dåtid")
    catalog = require_knowledge()
    update_fact(catalog, "fact-future", valid_at=NOW + timedelta(days=1))
    update_fact(catalog, "fact-past", invalid_at=NOW - timedelta(days=1))
    assert current_fact(catalog, "fact-future", f"customer:{CUSTOMER}", NOW) is False
    assert current_fact(catalog, "fact-past", f"customer:{CUSTOMER}", NOW) is False


def test_answer_from_another_tenant_is_not_visible():
    _publish(fact_id="fact-foreign", identity="foreign", text="Främmande", customer_id=99)
    catalog = require_knowledge()
    assert answer_facts(catalog, "question-99", CUSTOMER) == []
    assert [fact.id for fact in answer_facts(catalog, "question-99", 99)] == ["fact-foreign"]


def test_shared_answer_is_visible_to_every_customer():
    publish_answer_fact(
        require_knowledge(),
        AnswerPublish(
            question_id="question-shared",
            question_text=QUESTION,
            scope=shared_scope(),
            identity="shared-a",
            evidence_set_id="set-shared",
            fact_id="fact-shared",
            attributes={"knowledge_module": "dd", "answer_status": "sufficient"},
            basis=[{"title": "Delat svar"}],
            assessment={"sufficient": True},
            dependency_ids=(),
        ),
    )
    catalog = require_knowledge()
    assert [fact.id for fact in answer_facts(catalog, "question-shared", CUSTOMER)] == [
        "fact-shared"
    ]
    assert [fact.id for fact in answer_facts(catalog, "question-shared", 42)] == ["fact-shared"]


def test_unknown_question_id_returns_no_answers_without_vector_search():
    catalog = require_knowledge()
    assert answer_facts(catalog, "question-that-does-not-exist", CUSTOMER) == []


def test_limit_applies_after_filtering_so_history_cannot_hide_a_current_answer():
    catalog = require_knowledge()
    for index in range(205):
        _publish(fact_id=f"fact-old-{index}", identity=f"old-{index}", text=f"Gammalt {index}")
        update_fact(catalog, f"fact-old-{index}", invalid_at=NOW - timedelta(days=1))
    _publish(fact_id="fact-current", identity="current", text="Aktuellt svar")

    capped = answer_facts(catalog, f"question-{CUSTOMER}", CUSTOMER, limit=5, now=NOW)

    assert [fact.id for fact in capped] == ["fact-current"]
