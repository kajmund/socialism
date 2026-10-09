"""Original quote geometry follows visual text order and preserves punctuation."""

from io import BytesIO
from types import SimpleNamespace

import pdfplumber
import pytest

from app.services.document_knowledge import _quote_rects
from app.services.pdf_quote_anchors import _normalized, first_quote_page, quote_rects
from app.services.workspace.search import _pdf_quote_rects
from app.services.workspace.tool_arguments import FocusPassageArguments
from app.services.workspace_quote_focus import _locate_quote, matching_quote

QUOTE = "Period: 2031-02-03 09:00 2031-02-03 10:00"


def _synthetic_pdf(*, amount_line="Other page without the quote.") -> bytes:
    streams = [
        "BT /F1 12 Tf 72 720 Td (Period:) Tj ET\n"
        "BT /F1 12 Tf 72 680 Td (2031-02-03 10:00) Tj ET\n"
        "BT /F1 12 Tf 72 640 Td (Unrelated fee: 43.50 SEK.) Tj ET\n"
        "BT /F1 12 Tf 72 700 Td (2031-02-03 09:00) Tj ET\n",
        f"BT /F1 12 Tf 72 720 Td ({amount_line}) Tj ET\n",
    ]
    objects = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: "<< /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, stream in zip((4, 6), streams, strict=True):
        objects[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {page_id + 1} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        objects[page_id + 1] = f"<< /Length {len(stream)} >>\nstream\n{stream}endstream"
    output, offsets = bytearray(b"%PDF-1.1\n"), []
    for identity, value in objects.items():
        offsets.append(len(output))
        output.extend(f"{identity} 0 obj\n{value}\nendobj\n".encode())
    xref = len(output)
    output.extend(b"xref\n0 8\n0000000000 65535 f \n")
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer << /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def test_multiline_quote_uses_visual_order_even_when_draw_stream_differs():
    data = _synthetic_pdf()
    with pdfplumber.open(BytesIO(data)) as pdf:
        page = pdf.pages[0]
        drawn = " ".join(word["text"] for word in page.extract_words(use_text_flow=True))
        visual = " ".join(word["text"] for word in page.extract_words(use_text_flow=False))
        assert QUOTE not in drawn and QUOTE in visual
        rects = _quote_rects(pdf, 1, QUOTE)
        assert len(rects) == 3
        assert [rect["y"] for rect in rects] == sorted(rect["y"] for rect in rects)
        assert all(rect["x"] == pytest.approx(72 / page.width) for rect in rects)
        fee_top = next(word["top"] for word in page.extract_words() if word["text"] == "Unrelated")
        assert all(rect["y"] + rect["height"] < fee_top / page.height for rect in rects)
    assert _pdf_quote_rects(data, 1, QUOTE) == rects


@pytest.mark.parametrize("quote", [
    "Period; 2031-02-03 09:00 2031-02-03 10:00",
    "Period: 2031/02/03 09:00 2031/02/03 10:00",
    "Period: 2031-02-03 09:00 2031-02-03 11:00",
    "Period: 2031-02-03 10:00",  # Cannot skip the earlier line.
    "Period: 2031-02-03 10:00 Unrelated fee: 43.50 SEK. 2031-02-03 09:00",  # Draw order is not reading order.
    "", " \n\t",
])
def test_changed_or_noncontiguous_original_quote_has_no_geometry(quote):
    assert _pdf_quote_rects(_synthetic_pdf(), 1, quote) == []


@pytest.mark.parametrize("page_number", [0, 2, 3])
def test_quote_on_another_or_missing_page_has_no_geometry(page_number):
    assert _pdf_quote_rects(_synthetic_pdf(), page_number, QUOTE) == []


def test_existing_case_and_whitespace_normalization_is_preserved():
    data = _synthetic_pdf()
    assert _pdf_quote_rects(data, 1, QUOTE.swapcase().replace(" ", "\n\t ")) == _pdf_quote_rects(data, 1, QUOTE)


def test_whole_word_amount_match_selects_later_exact_amount():
    data = _synthetic_pdf(amount_line="150 SEK 50 SEK")
    with pdfplumber.open(BytesIO(data)) as pdf:
        words = pdf.pages[1].extract_words()
        rect, = _quote_rects(pdf, 2, "50 SEK")
        assert rect["x"] == pytest.approx(words[2]["x0"] / pdf.pages[1].width)
        assert rect["width"] == pytest.approx((words[3]["x1"] - words[2]["x0"]) / pdf.pages[1].width)


@pytest.mark.parametrize("quote", ["50 SE", "150 SE", "50 SEK."])
def test_quote_cannot_end_inside_word_or_change_punctuation(quote):
    assert _pdf_quote_rects(_synthetic_pdf(amount_line="150 SEK 50 SEK"), 2, quote) == []


def test_identical_quotes_on_same_page_fail_closed_without_position_discriminator():
    assert _pdf_quote_rects(_synthetic_pdf(amount_line="50 SEK 50 SEK"), 2, "50 SEK") == []


def test_longer_request_marks_the_verbatim_span():
    found = matching_quote(f"Inledning. {QUOTE} Avslutning.", f"Jag tror att {QUOTE} och något som inte står här.")
    assert found is not None
    assert _normalized(found) == _normalized(QUOTE)
    located = _locate_quote(_synthetic_pdf(), f"Ovidkommande {QUOTE}")
    assert located is not None
    page, rects, exact = located
    assert page == 1 and rects
    assert _normalized(exact) == _normalized(QUOTE)
    FocusPassageArguments(source_id="source-one", quote=("avtal " * 300).strip())


def test_repeated_phrase_still_marks_the_first_occurrence():
    with pdfplumber.open(BytesIO(_synthetic_pdf())) as pdf:
        located = first_quote_page(pdf, "2031-02-03")
        assert located is not None
        page, rects = located
        assert page == 1 and rects
        assert quote_rects(pdf, 1, "2031-02-03") == []


@pytest.mark.parametrize("x0,x1,top,bottom,expected", [
    (-10, 120, -5, 110, [{"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}]),
    (90, 120, 80, 110, [{"x": .9, "y": .8, "width": .1, "height": .2}]),
    (110, 120, 10, 20, []),
    (10, 20, -20, -10, []),
])
def test_clipped_pdf_word_geometry_stays_inside_page(x0, x1, *, top, bottom, expected):
    word = {"text": "Synthetic", "x0": x0, "x1": x1, "top": top, "bottom": bottom}
    page = SimpleNamespace(width=100, height=100, extract_words=lambda **_kwargs: [word])
    rects = quote_rects(SimpleNamespace(pages=[page]), 1, "Synthetic")
    assert len(rects) == len(expected)
    for actual, wanted in zip(rects, expected, strict=True):
        assert actual == pytest.approx(wanted)
        assert actual["x"] + actual["width"] <= 1 and actual["y"] + actual["height"] <= 1
