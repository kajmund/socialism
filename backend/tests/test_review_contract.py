"""Language lock, moderator label, and real-world ownership."""

from __future__ import annotations

import pytest

from app.services.expertgranskning.actor_context import ActorContext
from app.services.expertgranskning.observation import bind_actor_attribution
from app.services.expertgranskning.report_html import render_expertgranskning_html
from app.services.expertgranskning.schemas import WordExpertObservation
from app.services.prompt_catalog import default_prompts
from app.services.review_contract import (
    compose_review_system_context,
    display_speaker_label,
    is_moderator_label,
    messages_with_output_contract,
    normalize_output_locale,
    output_contract_for_locale,
    real_world_action_owner,
    sanitize_recommended_action_owner,
)


def test_output_contract_loads_from_prompt_catalog_per_locale():
    sv = output_contract_for_locale("sv")
    en = output_contract_for_locale("en")
    nb = output_contract_for_locale("nb")
    assert sv == default_prompts("sv")["review.output_contract"]
    assert en == default_prompts("en")["review.output_contract"]
    assert nb == default_prompts("nb")["review.output_contract"]
    assert "på svenska" in sv
    assert "inte till engelska" in sv
    assert "in English" in en
    assert "Do not switch to Swedish" in en
    assert "norsk (bokmål)" in nb
    assert "på svenska" not in nb
    assert "in English" not in nb


def test_normalize_output_locale_does_not_relabel_norwegian():
    assert normalize_output_locale("nb") == "nb"
    assert normalize_output_locale("en") == "en"
    assert normalize_output_locale("sv") == "sv"
    with pytest.raises(ValueError, match="unsupported review locale"):
        normalize_output_locale("de")


def test_display_speaker_never_keeps_first_person_moderator_suffix():
    assert display_speaker_label("moderator") == "Moderator"
    assert display_speaker_label("Moderator (Jag)") == "Moderator"
    assert display_speaker_label("Moderator (I)") == "Moderator"
    assert display_speaker_label("Moderator (jag)") == "Moderator"
    assert display_speaker_label("Jurist") == "Jurist"
    assert is_moderator_label("Moderator (Jag)")


def test_moderator_cannot_own_real_world_action_when_actor_is_known():
    actor = ActorContext(
        user_role="Leverantören",
        counterpart_or_audience="Kunden",
        relationship="leverantör",
        review_goal="förhandla",
        output_perspective="leverantör",
        perspective_known=True,
    )
    assert real_world_action_owner("Moderator (Jag)", actor) == "Leverantören"
    assert real_world_action_owner("Moderator", actor) == "Leverantören"
    assert (
        sanitize_recommended_action_owner(
            "Moderator (Jag) bör kontakta motparten.", actor
        )
        == "Leverantören bör kontakta motparten."
    )


def test_unknown_actor_leaves_moderator_ownership_unassigned():
    actor = ActorContext(perspective_known=False)
    assert real_world_action_owner("Moderator (jag)", actor) == ""
    assert sanitize_recommended_action_owner(
        "Moderator should send the proposal.", actor
    ) == "should send the proposal."


def test_bind_actor_attribution_strips_moderator_action_ownership():
    actor = ActorContext(
        user_role="Leverantören",
        perspective_known=True,
    )
    bound = bind_actor_attribution(
        WordExpertObservation(
            issue="Betalning",
            analysis="Intern analys.",
            source_perspective="user",
            target_perspective="counterpart",
            statement_owner="Moderator",
            recommendation_recipient="Moderator (Jag)",
            consequence="Förhandlingen stannar.",
            recommended_action="Moderator (Jag) bör skicka ett reviderat förslag.",
        ),
        actor,
    )
    assert bound.statement_owner == "Leverantören"
    assert bound.recommended_action == "Leverantören bör skicka ett reviderat förslag."
    assert bound.recommendation_recipient == "user"


def test_report_html_never_renders_moderator_first_person_label():
    html = render_expertgranskning_html(
        title="Avtal",
        locale="sv",
        document_text="Text",
        summary="Vi bör justera räntan.",
        transcript=[
            {
                "speaker": "Moderator (Jag)",
                "phase": "analysis",
                "content": "Vi rekommenderar att leverantören tar kontakt.",
            }
        ],
        session_id="sess-1",
    )
    assert "Moderator (Jag)" not in html
    assert "Moderator (I)" not in html
    assert ">Moderator<" in html or ">Moderator</div>" in html
    assert "Vi rekommenderar" in html


def test_messages_with_output_contract_keep_language_and_role_rules():
    messages = messages_with_output_contract(
        [{"role": "user", "content": "Fråga"}],
        default_prompts("sv"),
    )
    assert messages[0]["role"] == "system"
    assert "Hårt utdataspråkskontrakt" in messages[0]["content"]
    assert "Moderator — aldrig Moderator (Jag)" in messages[0]["content"]
    combined = compose_review_system_context(
        prompts=default_prompts("en"),
        actor_context="Actor context",
    )
    assert "Hard output-language contract" in combined
    assert "Actor context" in combined
