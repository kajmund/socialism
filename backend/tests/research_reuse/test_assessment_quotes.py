"""Share literal legal quotations without changing grounding or suppressing counterevidence."""

import copy
import json
import logging
from dataclasses import replace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import BadRequestError
from sqlalchemy import text

from app.llm import StructuredOutputError
from app.llm.research_assessment import EvidenceSufficiencyModel, LlmResearchAssessor
from app.services.research.assessment import ResearchAssessmentError
from app.services.research.assessment_input import encode_assessment_input
from app.services.research.reuse_gate import assess_reuse
from tests.research_reuse.helpers import evidence, need, restore_legal_input

pytestmark = pytest.mark.research_reuse


def row(excerpt, analysis, *, source="A"):
    return {
        "evidence_id": f"original-{source}",
        "source_id": source,
        "source_url": f"https://example.test/{source}",
        "excerpt": excerpt,
        "legal_result": analysis,
    }


def assert_roundtrip(originals, payload):
    for original, packed in zip(originals, payload["evidence"], strict=True):
        source = "".join(payload["passages"][ref] for ref in packed["passage_ids"])
        assert source.encode("utf-8") == original["excerpt"].encode("utf-8")
        assert restore_legal_input(packed["legal_result"], payload) == original["legal_result"]


def test_overlapping_quotes_span_paragraphs_and_keep_repeated_unicode_verbatim():
    first = "A\u030a och å är olika byteföljder.\r\n\r\n" + "Domstolen avslog yrkandet. " * 8
    second = first[50:] + "Undantaget gäller konsumenter. " * 6
    source = "Inledning\n\n" + first + second[len(first[50:]) :] + "\n\n" + first
    legal = {
        "case_law": {
            "citations": [{"quote": first}, {"quote": second}],
            "positive_outcome": False,
            "court_reasoning": "Jämkning medgavs inte.",
        },
        "truncated": False,
    }
    originals = [row(source, legal)]
    before = copy.deepcopy(originals)
    payload = encode_assessment_input(originals).payload
    assert_roundtrip(originals, payload)
    assert originals == before
    assert (
        restore_legal_input(payload["evidence"][0]["legal_result"], payload)["case_law"][
            "positive_outcome"
        ]
        is False
    )
    assert sum(map(len, payload["passages"].values())) < len(source)


def test_identical_quotes_keep_independent_sources_spans_roles_and_temporal_warnings():
    quote = "Avtalsvillkoret bedöms mot förhållandena vid avtalets tillkomst. " * 5
    originals = [
        row(
            quote,
            {
                "citations": [
                    {
                        "quote": quote,
                        "source_uri": f"https://example.test/{source}",
                        "source_span_id": f"{source}:42",
                        "role": role,
                    }
                ],
                "valid_to": "2025-01-01" if source == "A" else None,
                "authority_warning": "Kontrollera originalet",
            },
            source=source,
        )
        for source, role in [("A", "support"), ("B", "counterevidence")]
    ]
    payload = encode_assessment_input(originals).payload
    assert_roundtrip(originals, payload)
    a, b = payload["evidence"]
    assert a["source_id"] != b["source_id"]
    assert a["passage_ids"] == b["passage_ids"]
    assert sum(map(len, payload["passages"].values())) == len(quote)


@pytest.mark.parametrize("quote", ["", "kort", "Annat fullständigt källcitat. " * 10])
def test_quote_outside_selected_excerpt_is_retained_in_full(quote):
    originals = [row("Valt källutdrag.", {"citations": [{"quote": quote}]})]
    payload = encode_assessment_input(originals).payload
    assert_roundtrip(originals, payload)
    assert (
        restore_legal_input(payload["evidence"][0]["legal_result"], payload)["citations"][0][
            "quote"
        ]
        == quote
    )


def test_quote_matching_does_not_normalize_unicode_or_whitespace():
    excerpt = "e\u0301\r\n" * 100
    quote = "é\n" * 100
    originals = [row(excerpt, {"quote": quote})]
    payload = encode_assessment_input(originals).payload
    assert_roundtrip(originals, payload)
    assert quote not in payload["passages"].values()
    assert payload["evidence"][0]["legal_result"]["values"][0] == quote


def test_large_unique_analyses_share_source_quotes_without_dropping_any_analysis():
    originals = []
    for index in range(79):
        quote = (f"Avgörande {index}: detta villkor jämkades inte. " * 70) + "\n\n"
        analysis = {
            "case_law": {
                "citations": [{"quote": quote}],
                "outcome": f"Negativt utfall {index}",
                "positive_outcome": False,
            }
        }
        originals.append(row("Bakgrund\n\n" + quote + "Slutsats.", analysis, source=str(index)))
    payload = encode_assessment_input(originals).payload
    assert_roundtrip(originals, payload)
    assert len(payload["evidence"]) == len(originals)
    # Each analysis is unique; whole-object deduplication would not eliminate the repeated quote.
    assert (
        len(json.dumps(payload, ensure_ascii=False))
        < len(json.dumps(originals, ensure_ascii=False)) * 0.6
    )


@pytest.mark.parametrize("code", ["context_length_exceeded", "invalid_request_error"])
async def test_provider_failure_preserves_cause_releases_database_and_logs_only_safe_fields(
    reuse_db,
    caplog,
    code,
):
    error = BadRequestError(
        "sensitive request body must not appear in logs",
        response=httpx.Response(400, request=httpx.Request("POST", "https://example.test")),
        body={"code": code},
    )

    async def complete(_messages, _response_model):
        async with reuse_db() as other:
            assert await other.scalar(text("SELECT 1")) == 1
        raise error

    adapter = LlmResearchAssessor(
        completer=complete,
        system_prompt="Mock boundary",
        user_prompt="{evidence_json}",
    )
    message = "context limit exceeded" if code == "context_length_exceeded" else "model call failed"
    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ResearchAssessmentError, match=message) as raised,
    ):
        await assess_reuse(adapter, need(), [evidence()])
    assert raised.value.__cause__ is error
    assert "research.assessment.failed" in caplog.text
    assert "evidence_count=1 review_group_count=1" in caplog.text
    assert "sensitive request body" not in caplog.text
    async with reuse_db() as other:
        assert await other.scalar(text("SELECT 1")) == 1


async def test_request_json_omits_formatting_whitespace_but_preserves_source_spaces():
    source = "  Fullständig källtext med blanksteg.  "
    completer = AsyncMock(
        return_value=EvidenceSufficiencyModel(result="insufficient", rationale="Mock")
    )
    adapter = LlmResearchAssessor(
        completer=completer,
        system_prompt="Mock boundary",
        user_prompt="{evidence_json}",
    )
    await assess_reuse(adapter, need(), [replace(evidence(), excerpt=source)])
    packed = completer.call_args.args[0][1]["content"]
    assert packed == json.dumps(json.loads(packed), ensure_ascii=False, separators=(",", ":"))
    assert source in json.loads(packed)["passages"].values()


@pytest.mark.parametrize(
    "error,reason,message",
    [
        (TimeoutError(), "timeout", "timed out"),
        (
            StructuredOutputError("length", finish_reason="length"),
            "output_length_exceeded",
            "output limit",
        ),
    ],
)
async def test_timeout_and_truncated_output_have_distinct_visible_errors(
    error, reason, message, caplog
):
    completer = AsyncMock(side_effect=error)
    adapter = LlmResearchAssessor(
        completer=completer,
        system_prompt="Mock boundary",
        user_prompt="{evidence_json}",
    )
    with (
        caplog.at_level(logging.ERROR),
        pytest.raises(ResearchAssessmentError, match=message) as raised,
    ):
        await assess_reuse(adapter, need(), [evidence()])
    assert raised.value.__cause__ is error
    assert f"reason={reason}" in caplog.text
    assert completer.await_count == 1


def test_schema_sharing_keeps_field_order_empty_values_unknown_fields_and_negative_outcomes():
    first = {
        "negative": False,
        "not_known": None,
        "citations": [],
        "confidence": 0,
        "extension": {"future_warning": "Oprövad rättsfråga"},
    }
    second = dict(reversed(list(first.items())))
    originals = [row("Text A", first), row("Text B", second, source="B")]
    payload = encode_assessment_input(originals).payload
    assert_roundtrip(originals, payload)
    for packed, original in zip(payload["evidence"], originals, strict=True):
        assert list(restore_legal_input(packed["legal_result"], payload)) == list(
            original["legal_result"]
        )
