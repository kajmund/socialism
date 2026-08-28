from app.services.report.markdown_html import markdown_to_html


def test_markdown_to_html_renders_headings_lists_and_emphasis():
    html = markdown_to_html(
        "### Styrkor\n"
        "- **Stabil** marginal\n"
        "- *Mogen* marknad\n"
        "\n"
        "1. Nästa steg\n"
        "\n"
        "Slutsats med <script>alert(1)</script> [[ref:mottagande]]"
    )
    assert "<h3>Styrkor</h3>" in html
    assert "<strong>Stabil</strong>" in html
    assert "<em>Mogen</em>" in html
    assert "<ol><li>Nästa steg</li></ol>" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html
    assert "[[ref:mottagande]]" not in html


def test_markdown_to_html_empty():
    assert markdown_to_html("  \n") == ""
