"""Operator review intent is prepended to the panel brief."""

from app.services.panel.review_intent import (
    compose_brief_with_review_intent,
    render_review_intent_message,
    session_brief_for_llm,
)
from app.services.panel.schemas import PanelSessionConfig
from app.services.prompt_catalog import default_prompts


def test_empty_review_intent_leaves_brief_unchanged():
    prompts = default_prompts("sv")
    assert render_review_intent_message(prompts, "") == ""
    assert render_review_intent_message(prompts, "   ") == ""
    document = "Avtalstext."
    assert compose_brief_with_review_intent(
        prompts, brief=document, review_intent=""
    ) == document


def test_review_intent_is_prepended_and_guides_party_position():
    prompts = default_prompts("sv")
    document = "Avtalstext om parterna."
    intent = "Det är Devbrains som är motpart i avtalet."
    composed = compose_brief_with_review_intent(
        prompts, brief=document, review_intent=intent
    )
    assert composed.startswith("Granskningsavsikt")
    assert intent in composed
    assert composed.endswith(document)
    config = PanelSessionConfig(
        topic="Avtal",
        brief=document,
        review_intent=intent,
    )
    assert session_brief_for_llm(config, prompts) == composed


def test_review_intent_braces_are_not_treated_as_placeholders():
    prompts = default_prompts("sv")
    text = "Titta extra på klausul {2.1}."
    composed = compose_brief_with_review_intent(
        prompts, brief="Dokument.", review_intent=text
    )
    assert "klausul {2.1}." in composed
    assert "{{2.1}}" not in composed
