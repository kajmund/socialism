from app.services.expertgranskning.disposition import (
    batch_reviewable_paragraphs,
    build_disposition,
    clause_group_key,
    extract_written_number,
    normalize_number,
)
from app.services.expertgranskning.schemas import WordDocumentParagraph


def _p(
    index: int,
    text: str,
    *,
    style: str = "Normal",
    list_string: str | None = None,
) -> WordDocumentParagraph:
    return WordDocumentParagraph(
        index=index, text=text, style=style, list_string=list_string
    )


def test_clause_group_keeps_subpoints_together() -> None:
    assert clause_group_key(_p(0, "8.1 Avtal")) == "8"
    assert clause_group_key(_p(1, "text", list_string="8.2")) == "8"
    assert clause_group_key(_p(2, "8 Fristående")) == "8"


def test_batch_does_not_split_clause_subpoints() -> None:
    paragraphs = [
        _p(0, "7.1 Första", list_string="7.1."),
        _p(1, "7.2 Andra", list_string="7.2."),
        _p(2, "7.3 Tredje", list_string="7.3."),
        _p(3, "7.4 Fjärde", list_string="7.4."),
        _p(4, "8.1 Femte", list_string="8.1."),
        _p(5, "8.2 Sjätte", list_string="8.2."),
    ]
    batches = batch_reviewable_paragraphs(paragraphs, size=4)
    assert [[p.index for p in batch] for batch in batches] == [
        [0, 1, 2, 3],
        [4, 5],
    ]


def test_disposition_flags_written_number_mismatch() -> None:
    paragraphs = [
        _p(0, "Inledning", style="Heading 1"),
        _p(1, "8.1 Fel numrerad punkt", list_string="7.1."),
    ]
    text = build_disposition(paragraphs)
    assert "7.1." in text
    assert "8.1" in text
    assert "MISMATCH" in text


def test_extract_written_number() -> None:
    assert extract_written_number("8.1 Avtalstid") == "8.1"
    assert normalize_number("8.1.") == "8.1"
