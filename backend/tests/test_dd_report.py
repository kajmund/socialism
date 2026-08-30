"""Tests for DD report generation from dd_panel sessions."""

from __future__ import annotations

import asyncio
import json

import pytest
from httpx import AsyncClient

from app.llm import set_text_completer
from app.services import jobs as jobs_service
from app.services.dd.schemas import DdAccountFigure, DdAccountYear, DdCandidateCompany
from app.services.dd.source_attribution import SourceBadge
from app.services.panel.schemas import (
    DdDissensusNote,
    DdExpertScore,
    DdPanelResult,
    DdUnansweredNote,
)
from app.services.report.dd_report import (
    generate_dd_report_html,
    render_dd_html,
    render_dd_html_from_artifact,
)


def _sample_result(
    *, with_dissensus: bool = True, with_unanswered: bool = False
) -> DdPanelResult:
    candidate = DdCandidateCompany(
        id="cand_1",
        namn="Testbolaget AB",
        organisationsnummer="556677-8899",
        alder_ar=14,
        omrade="Stockholm",
        resultat="vinst",
        omsattning_sek=12_500_000,
        anstallda=42,
        beskrivning="Nischad B2B-leverantör.",
        rakenskaper=[
            DdAccountYear(
                year="2025",
                omsattning_sek=14_000_000,
                resultat_sek=2_100_000,
                ebitda_sek=3_400_000,
                utdelning_sek=500_000,
                anstallda=48,
                eget_kapital_sek=8_000_000,
                soliditet_pct="52.0",
                poster=[
                    DdAccountFigure(kod="EK", namn="Avskrivningar", enhet="sek", sek=900_000),
                ],
            ),
            DdAccountYear(
                year="2024",
                omsattning_sek=11_500_000,
                resultat_sek=-400_000,
                ebitda_sek=1_200_000,
                anstallda=42,
                eget_kapital_sek=6_200_000,
                soliditet_pct="47.5",
            ),
            DdAccountYear(
                year="2023",
                omsattning_sek=9_800_000,
                resultat_sek=800_000,
                ebitda_sek=1_600_000,
                anstallda=38,
                eget_kapital_sek=5_400_000,
            ),
        ],
    )
    scores = [
        DdExpertScore(
            expert_slot_id="finansiell_analytiker",
            expert_label="Finansiell analytiker",
            sub_question_id="finansiell_halsa",
            sub_question_label="Finansiell hälsa",
            score=8,
            motivation="Stabil marginal.",
            source=SourceBadge(kind="web", label="Webb", detail="Bolagsverket"),
        ),
        DdExpertScore(
            expert_slot_id="jurist",
            expert_label="Jurist",
            sub_question_id="legal_risk",
            sub_question_label="Legal risk",
            score=4,
            motivation="Pågående tvist.",
            source=SourceBadge(kind="web", label="Webb", detail="Allabolag"),
        ),
        DdExpertScore(
            expert_slot_id="marknadsanalytiker",
            expert_label="Marknadsanalytiker",
            sub_question_id="marknadsposition",
            sub_question_label="Marknadsposition",
            score=6,
            motivation="Mogen marknad.",
            source=SourceBadge(kind="llm", label="Modellbedömning", detail=""),
        ),
    ]
    dissensus = []
    if with_dissensus:
        dissensus = [
            DdDissensusNote(
                sub_question_id="legal_risk",
                sub_question_label="Legal risk",
                min_score=4,
                max_score=7,
                spread=3,
            )
        ]
    unanswered = []
    if with_unanswered:
        unanswered = [
            DdUnansweredNote(
                sub_question_id="integrationsrisk",
                sub_question_label="Integrationsrisk",
                moderator_note="Kräver extern integrationskompetens.",
            )
        ]
    return DdPanelResult(
        candidate=candidate,
        scores=scores,
        dissensus=dissensus,
        unanswered=unanswered,
        summary="**Blandad bild** — legal risk sticker ut.\n\n### Risker\n- Pågående tvist\n",
    )


def test_render_dd_html_includes_summary_matrix_and_dissensus():
    result = _sample_result()
    html = render_dd_html(
        result,
        title="DD Test",
        locale="sv",
        session_id="panel_abc",
        candidate_id="cand_1",
    )
    assert "<strong>Blandad bild</strong>" in html
    assert "<h3>Risker</h3>" in html
    assert "<li>Pågående tvist</li>" in html
    assert "**Blandad bild**" not in html
    assert "Testbolaget AB" in html
    assert "556677-8899" in html
    assert "poängmatris" in html
    assert "Dissensus" in html
    assert 'class="badge web"' in html
    assert 'class="badge single"' in html
    assert "OKF-manual" not in html
    assert 'class="badge confirmed"' not in html
    assert "Källbilaga" in html
    assert 'id="rakenskaper"' in html
    assert 'class="dd-accounts-grid"' in html
    assert 'aria-label="Omsättning:' in html
    assert 'aria-label="Resultat:' in html
    assert "<strong>2025</strong> —" not in html
    assert "<th>2023</th>" in html
    assert "<th>2024</th>" in html
    assert "<th>2025</th>" in html
    assert "14 000 000 SEK" in html
    assert "−400 000 SEK" in html or "-400 000 SEK" in html


def test_render_dd_html_includes_unanswered():
    result = _sample_result(with_dissensus=False, with_unanswered=True)
    html = render_dd_html(
        result,
        title="DD Test",
        locale="sv",
        session_id="panel_abc",
        candidate_id="cand_1",
    )
    assert 'id="obesvarade"' in html
    assert "Obesvarade delfrågor" in html
    assert "Integrationsrisk" in html
    assert "extern integrationskompetens" in html
    assert "unanswered-col" in html


def test_render_dd_html_omits_unanswered_when_empty():
    result = _sample_result(with_dissensus=False)
    html = render_dd_html(
        result,
        title="DD Test",
        locale="sv",
        session_id="panel_abc",
        candidate_id="cand_1",
    )
    assert 'id="obesvarade"' not in html
    assert "Obesvarade delfrågor" not in html


def test_render_dd_html_remaps_okf_badges():
    result = _sample_result(with_dissensus=False)
    result.scores[0].source = SourceBadge.model_validate(
        {"kind": "okf", "label": "OKF-manual", "detail": "Byta gränssnittsspråk"}
    )
    html = render_dd_html(
        result,
        title="DD Test",
        locale="sv",
        session_id="panel_abc",
        candidate_id="cand_1",
    )
    assert "OKF-manual" not in html
    assert "badge confirmed" not in html
    assert "Modellbedömning" in html
    assert 'class="badge single"' in html


@pytest.mark.asyncio
async def test_render_dd_html_from_artifact_drops_okf(tmp_path):
    result = _sample_result(with_dissensus=False)
    result.scores[0].source = SourceBadge.model_validate(
        {"kind": "okf", "label": "OKF-manual", "detail": "Byta gränssnittsspråk"}
    )
    out_dir = tmp_path / "rpt_okf"
    await generate_dd_report_html(
        result,
        session_id="panel_abc",
        candidate_id="cand_1",
        out_dir=out_dir,
        title="DD Test",
    )
    (out_dir / "report.html").write_text(
        '<span class="badge confirmed">OKF-manual</span>',
        encoding="utf-8",
    )
    html = render_dd_html_from_artifact(out_dir, title="DD Test")
    assert html is not None
    assert "OKF-manual" not in html
    assert "badge confirmed" not in html
    assert "Modellbedömning" in html


@pytest.mark.asyncio
async def test_generate_dd_report_html_writes_artifacts(tmp_path):
    result = _sample_result(with_unanswered=True)
    html_path, slots_path, slots_doc, dd_doc = await generate_dd_report_html(
        result,
        session_id="panel_abc",
        candidate_id="cand_1",
        out_dir=tmp_path / "rpt_test",
        title="DD Test",
    )
    assert html_path.is_file()
    assert slots_path.is_file()
    assert (tmp_path / "rpt_test" / "report.dd.json").is_file()
    assert dd_doc["mode"] == "dd"
    assert slots_doc["mode"] == "dd"
    assert dd_doc["unanswered"][0]["sub_question_id"] == "integrationsrisk"
    assert "Obesvarade delfrågor" in html_path.read_text(encoding="utf-8")
    assert "Sammanfattning" in html_path.read_text(encoding="utf-8")


@pytest.fixture
def mock_dd_panel_llm():
    score_counter = {"n": 0}

    async def _complete(messages, *, model=None):
        user = messages[-1]["content"]
        if "ENDAST JA eller NEJ" in user or "ONLY YES or NO" in user:
            return "JA"
        if "Ingen av experterna" in user or "None of the experts" in user:
            return "Panelen saknar rätt kompetens för frågan."
        if "ENDAST med JSON" in user or "ONLY with JSON" in user:
            score_counter["n"] += 1
            score = 5 + (score_counter["n"] % 4)
            return json.dumps({"score": score, "motivation": f"Bedömning {score_counter['n']}"})
        if "Poängtabell" in user or "Score table" in user:
            return "Sammanfattning: blandad bild med tydlig dissensus kring legal risk."
        if "Nuvarande delfråga" in user or "Current sub-question" in user:
            return "Vi går vidare till nästa delfråga."
        if "Öppna panelen" in user or "Open briefly" in user:
            return "Välkommen till DD-panelen."
        return "OK"

    set_text_completer(_complete)
    yield
    set_text_completer(None)


@pytest.mark.asyncio
async def test_dd_report_end_to_end_from_panel_session(
    client: AsyncClient,
    mock_dd_panel_llm,
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "app.services.dd.source_attribution.search_duckduckgo",
        lambda query, number_of_result_pages=5: [],
    )

    create = await client.post(
        "/dd/campaigns",
        json={"title": "DD Report", "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""}},
    )
    assert create.status_code == 201
    campaign_id = create.json()["id"]

    sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    assert sourced.status_code == 200
    candidate_id = sourced.json()["candidates"][0]["id"]

    session_resp = await client.post(
        f"/dd/campaigns/{campaign_id}/panel-sessions",
        json={"campaign_id": campaign_id, "candidate_id": candidate_id},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["id"]

    panel_done = asyncio.Event()

    def _schedule_panel(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            panel_done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule_panel)
    run_panel = await client.post(f"/panel/sessions/{session_id}/run")
    assert run_panel.status_code == 202
    await asyncio.wait_for(panel_done.wait(), timeout=20)

    panel = await client.get(f"/panel/sessions/{session_id}")
    assert panel.json()["status"] == "succeeded"
    assert panel.json()["result"] is not None

    report_done = asyncio.Event()

    def _schedule_report(job_id: str) -> None:
        async def _run() -> None:
            await jobs_service._run_job(job_id)
            report_done.set()

        asyncio.create_task(_run())

    jobs_service.set_schedule_hook(_schedule_report)
    create_report = await client.post(
        "/reports",
        json={
            "sources": [
                {
                    "type": "dd_session",
                    "session_id": session_id,
                    "candidate_id": candidate_id,
                }
            ],
            "title": "DD rapport test",
        },
    )
    assert create_report.status_code == 202, create_report.text
    report_body = create_report.json()
    assert report_body["mode"] == "dd"
    report_id = report_body["id"]

    await asyncio.wait_for(report_done.wait(), timeout=20)
    jobs_service.set_schedule_hook(None)

    got = await client.get(f"/reports/{report_id}")
    assert got.status_code == 200
    data = got.json()
    assert data["status"] == "succeeded"
    assert data["mode"] == "dd"

    html = await client.get(f"/reports/{report_id}/html")
    assert html.status_code == 200
    content = html.content.decode("utf-8")
    assert "Sammanfattning" in content
    assert "poängmatris" in content or "Poängmatris" in content.lower()
    assert "Dissensus" in content
    assert data["sources"][0]["type"] == "dd_session"


@pytest.mark.asyncio
async def test_dd_report_rejects_unfinished_panel(client: AsyncClient):
    create = await client.post(
        "/dd/campaigns",
        json={"title": "Draft panel", "criteria": {"alder_min": 0, "alder_max": 50, "omrade": ""}},
    )
    campaign_id = create.json()["id"]
    sourced = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    candidate_id = sourced.json()["candidates"][0]["id"]
    session_resp = await client.post(
        f"/dd/campaigns/{campaign_id}/panel-sessions",
        json={"campaign_id": campaign_id, "candidate_id": candidate_id},
    )
    session_id = session_resp.json()["id"]

    resp = await client.post(
        "/reports",
        json={
            "sources": [
                {
                    "type": "dd_session",
                    "session_id": session_id,
                    "candidate_id": candidate_id,
                }
            ],
        },
    )
    assert resp.status_code == 400
    assert "succeeded" in resp.json()["detail"].lower()
