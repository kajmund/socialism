"""Deterministic Word anchors and resolver — no LLM or nearest-guess."""

from __future__ import annotations

from app.services.word.anchors import (
    WordAnchor,
    WordDocumentParagraphState,
    hash_word_text,
    normalize_word_text,
    resolve_word_anchor,
    reviewed_text_from_job_request,
    same_word_session,
    word_anchor_from_job_request,
)


def _doc(*rows: tuple[int, str] | tuple[int, str, str]) -> list[WordDocumentParagraphState]:
    states: list[WordDocumentParagraphState] = []
    for row in rows:
        if len(row) == 3:
            index, text, local_id = row
            states.append(
                WordDocumentParagraphState(
                    paragraph_index=index,
                    text=text,
                    unique_local_id=local_id,
                )
            )
        else:
            index, text = row
            states.append(WordDocumentParagraphState(paragraph_index=index, text=text))
    return states


def _request() -> dict:
    return {
        "sections": [
            {
                "heading": "Inledning",
                "heading_paragraph_index": 0,
                "heading_unique_local_id": "h-1",
                "paragraphs": [
                    {
                        "index": 1,
                        "text": "Första stycket.",
                        "unique_local_id": "p-1",
                    },
                    {
                        "index": 2,
                        "text": "Samma text.",
                        "unique_local_id": "p-2",
                    },
                    {
                        "index": 3,
                        "text": "Samma text.",
                        "unique_local_id": "p-3",
                    },
                    {
                        "index": 4,
                        "text": "Sista stycket.",
                        "unique_local_id": "p-4",
                    },
                ],
            }
        ]
    }


def test_hash_is_sha256_of_normalized_utf8() -> None:
    assert hash_word_text("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert hash_word_text("  Hej\r\n ") == hash_word_text("Hej")
    assert normalize_word_text("  Hej\r\n ") == "Hej"


def test_heading_and_paragraph_get_equivalent_anchor_fields() -> None:
    heading = word_anchor_from_job_request(_request(), 0)
    paragraph = word_anchor_from_job_request(_request(), 1)
    assert heading is not None
    assert paragraph is not None
    assert heading.unique_local_id == "h-1"
    assert paragraph.unique_local_id == "p-1"
    assert heading.reviewed_text == "Inledning"
    assert paragraph.reviewed_text == "Första stycket."
    assert heading.text_hash == hash_word_text("Inledning")
    assert paragraph.previous_text_hash == heading.text_hash
    assert heading.next_text_hash == paragraph.text_hash
    assert paragraph.next_text_hash == hash_word_text("Samma text.")


def test_reviewed_text_from_job_request_walks_sections() -> None:
    request = _request()
    assert reviewed_text_from_job_request(request, 0) == "Inledning"
    assert reviewed_text_from_job_request(request, 1) == "Första stycket."
    assert reviewed_text_from_job_request(request, 9) is None
    implicit = {
        "sections": [
            {
                "heading": "",
                "heading_paragraph_index": 0,
                "paragraphs": [{"index": 0, "text": "Ingress utan rubrik."}],
            }
        ]
    }
    assert reviewed_text_from_job_request(implicit, 0) == "Ingress utan rubrik."


def test_unchanged_same_index_resolves() -> None:
    anchor = word_anchor_from_job_request(_request(), 1)
    assert anchor is not None
    resolution = resolve_word_anchor(anchor, _doc((0, "Inledning"), (1, "Första stycket.")))
    assert resolution.status == "resolved"
    assert resolution.paragraph_index == 1


def test_moved_unchanged_paragraph_resolves() -> None:
    anchor = word_anchor_from_job_request(_request(), 1)
    assert anchor is not None
    resolution = resolve_word_anchor(
        WordAnchor(
            paragraph_index=anchor.paragraph_index,
            reviewed_text=anchor.reviewed_text,
            text_hash=anchor.text_hash,
            previous_text_hash=anchor.previous_text_hash,
            next_text_hash=anchor.next_text_hash,
        ),
        _doc((0, "Ny ingress"), (1, "Inledning"), (2, "Första stycket.")),
    )
    assert resolution.status == "resolved"
    assert resolution.paragraph_index == 2


def test_valid_local_id_and_unchanged_text_resolves() -> None:
    anchor = word_anchor_from_job_request(_request(), 1)
    assert anchor is not None
    resolution = resolve_word_anchor(
        anchor,
        _doc((4, "Första stycket.", "p-1"), (5, "Annat.")),
    )
    assert resolution.status == "resolved"
    assert resolution.paragraph_index == 4


def test_valid_local_id_and_changed_text_is_stale() -> None:
    anchor = word_anchor_from_job_request(_request(), 1)
    assert anchor is not None
    resolution = resolve_word_anchor(
        anchor,
        _doc((1, "Ändrad text.", "p-1"), (2, "Första stycket.")),
    )
    assert resolution.status == "stale"
    assert resolution.paragraph_index is None


def test_restart_without_local_id_uses_unique_exact_text() -> None:
    anchor = word_anchor_from_job_request(_request(), 1)
    assert anchor is not None
    restart = WordAnchor(
        paragraph_index=anchor.paragraph_index,
        reviewed_text=anchor.reviewed_text,
        text_hash=anchor.text_hash,
        previous_text_hash=anchor.previous_text_hash,
        next_text_hash=anchor.next_text_hash,
    )
    resolution = resolve_word_anchor(
        restart,
        _doc((0, "Ny ingress"), (1, "Inledning"), (2, "Första stycket.")),
    )
    assert resolution.status == "resolved"
    assert resolution.paragraph_index == 2


def test_duplicate_text_with_unique_context_resolves() -> None:
    anchor = word_anchor_from_job_request(_request(), 2)
    assert anchor is not None
    resolution = resolve_word_anchor(
        WordAnchor(
            paragraph_index=99,
            reviewed_text=anchor.reviewed_text,
            text_hash=anchor.text_hash,
            previous_text_hash=anchor.previous_text_hash,
            next_text_hash=anchor.next_text_hash,
        ),
        _doc(
            (0, "Inledning"),
            (1, "Första stycket."),
            (2, "Samma text."),
            (3, "Samma text."),
            (4, "Sista stycket."),
        ),
    )
    assert resolution.status == "resolved"
    assert resolution.paragraph_index == 2


def test_duplicate_ambiguous_context_is_ambiguous() -> None:
    anchor = word_anchor_from_job_request(_request(), 2)
    assert anchor is not None
    resolution = resolve_word_anchor(
        WordAnchor(
            paragraph_index=99,
            reviewed_text=anchor.reviewed_text,
            text_hash=anchor.text_hash,
            previous_text_hash=hash_word_text("okänd"),
            next_text_hash=hash_word_text("okänd"),
        ),
        _doc((0, "Samma text."), (1, "Samma text.")),
    )
    assert resolution.status == "ambiguous"
    assert resolution.paragraph_index is None


def test_deleted_target_is_missing() -> None:
    anchor = word_anchor_from_job_request(_request(), 1)
    assert anchor is not None
    resolution = resolve_word_anchor(anchor, _doc((0, "Inledning"), (1, "Kvar.")))
    assert resolution.status == "missing"


def test_restart_ignores_recycled_local_id_and_uses_unique_text() -> None:
    request = {**_request(), "word_session_id": "session-a"}
    anchor = word_anchor_from_job_request(request, 1)
    assert anchor is not None
    assert anchor.word_session_id == "session-a"
    resolution = resolve_word_anchor(
        anchor,
        _doc((0, "Ny ingress"), (1, "Ändrad text.", "p-1"), (2, "Första stycket.")),
        current_session_id="session-b",
    )
    assert resolution.status == "resolved"
    assert resolution.paragraph_index == 2


def test_same_session_local_id_with_changed_text_stays_stale() -> None:
    request = {**_request(), "word_session_id": "session-a"}
    anchor = word_anchor_from_job_request(request, 1)
    assert anchor is not None
    resolution = resolve_word_anchor(
        anchor,
        _doc((1, "Ändrad text.", "p-1"), (2, "Första stycket.")),
        current_session_id="session-a",
    )
    assert resolution.status == "stale"
    assert same_word_session("session-a", "session-a") is True
    assert same_word_session("session-a", "session-b") is False


def test_changed_text_never_falls_back_to_index() -> None:
    anchor = word_anchor_from_job_request(_request(), 1)
    assert anchor is not None
    resolution = resolve_word_anchor(
        WordAnchor(
            paragraph_index=anchor.paragraph_index,
            reviewed_text=anchor.reviewed_text,
            text_hash=anchor.text_hash,
        ),
        _doc((1, "Helt annan text.")),
    )
    assert resolution.status == "missing"
    assert resolution.paragraph_index is None
