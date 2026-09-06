from lagen_nu_mcp.document import parse_html_document, sfs_nr_from_url
from lagen_nu_mcp.http import HttpResponse
from lagen_nu_mcp.document import parse_response


def test_sfs_nr_from_canonical_url() -> None:
    assert sfs_nr_from_url("https://lagen.nu/2017:193") == "2017:193"
    assert sfs_nr_from_url("https://lagen.nu/dom/nja/2024s1") is None


def test_parse_html_extracts_andring_and_paragraphs(sfs_html: str) -> None:
    parsed = parse_html_document("https://lagen.nu/2017:193", sfs_html)
    assert parsed.format == "html"
    assert parsed.sfs_nr == "2017:193"
    assert parsed.amending_sfs == "2026:1735"
    anchors = [p.anchor for p in parsed.paragraphs]
    assert "P1" in anchors
    assert "P3a" in anchors
    p3a = next(p for p in parsed.paragraphs if p.anchor == "P3a")
    assert p3a.label == "3 a §"
    assert "nationellt program" in p3a.text


def test_html_response_is_used_when_json_is_not_offered(sfs_html: str) -> None:
    parsed = parse_response(
        "https://lagen.nu/2017:193",
        HttpResponse(
            url="https://lagen.nu/2017:193",
            status=200,
            content_type="text/html",
            body=sfs_html,
        ),
    )
    assert parsed.format == "html"
    assert parsed.amending_sfs == "2026:1735"
