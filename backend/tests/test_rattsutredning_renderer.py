from __future__ import annotations

from pathlib import Path

from app.services.report.rattsutredning import (
    ForarbeteRef,
    LagtextRef,
    PraxisRef,
    RattsutredningPayload,
    render_rattsutredning_html,
    render_rattsutredning_markdown,
    write_rattsutredning_artifacts,
)


def _payload() -> RattsutredningPayload:
    return RattsutredningPayload(
        fraga="Måste en myndighet behandla anbudsgivare lika?",
        lagtext=[
            LagtextRef(
                sfs_id="2016:1145",
                rubrik="Lag om offentlig upphandling",
                utdrag="4 kap. 1 § likabehandling",
            )
        ],
        praxis=[
            PraxisRef(
                referens="HFD 2019 ref. 65",
                instans="HFD",
                utdrag="förfrågningsunderlag får inte otillbörligt gynna",
            )
        ],
        forarbeten=[
            ForarbeteRef(
                referens="prop. 2015/16:195",
                titel="Nytt ramverk",
                utdrag="samma förutsättningar",
            )
        ],
        sammanfattning="Ja, likabehandlingsprincipen gäller. [[ref:2016:1145]]",
        sourcing_status="complete",
    )


def test_markdown_has_legal_memo_headings():
    md = render_rattsutredning_markdown(_payload(), locale="sv")
    assert "## Tillämplig lagstiftning" in md
    assert "## Praxis" in md
    assert "## Förarbeten" in md
    assert "## Bedömning" in md
    assert "2016:1145" in md
    assert "HFD 2019 ref. 65" in md
    assert "prop. 2015/16:195" in md


def test_html_uses_same_headings_not_scores():
    html = render_rattsutredning_html(_payload(), title="PM", locale="sv")
    assert "Tillämplig lagstiftning" in html
    assert "Praxis" in html
    assert "Förarbeten" in html
    assert "Bedömning" in html
    assert "sub-question" not in html.lower()
    assert "delfråga" not in html.lower()


def test_write_artifacts(tmp_path: Path):
    html_path, slots_path, doc = write_rattsutredning_artifacts(
        _payload(),
        out_dir=tmp_path,
        title="PM",
        locale="sv",
        source_type="rattsunderlag",
        session_id="job_1",
        mode="rattsunderlag",
    )
    assert html_path.is_file()
    assert slots_path.is_file()
    assert doc["report_format"] == "rattsutredning"
    assert "Tillämplig lagstiftning" in html_path.read_text(encoding="utf-8")
