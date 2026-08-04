"""Unit tests for report metrics, charts, sanitize, classify, and generate (dry-run)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.report.bundles import RunBundle
from app.services.report.charts import prefill_chart_slots, render_agents_html, render_sec02_charts
from app.services.report.classify import (
    BundleClassification,
    TopicPack,
    classify_topics,
    fallback_topic_packs,
    tone_shares_heuristic,
)
from app.services.report.agent import (
    SlotBatchResponse,
    fill_slot_batch,
    group_questions_into_batches,
)
from app.services.report.generate import _load_questions, fill_narrative_slots, generate_report_html
from app.services.report.metrics import STYLE_UNCLASSIFIED, compute_report_metrics
from app.services.report.render import apply_slots
from app.services.report.sanitize import sanitize_slot_output
from app.services.report.tools import ReportToolBundle, call_tool
from app.llm import set_structured_completer


def _bundle(
    *,
    label: str = "A",
    agents: int = 5,
    posts: list[dict] | None = None,
    comments: list[dict] | None = None,
    injection_texts: list[str] | None = None,
    include_injector: bool = False,
) -> RunBundle:
    agent_rows: list[dict] = []
    if include_injector:
        agent_rows.append(
            {"index": 0, "member_name": "Partikonto", "role": "injector"}
        )
        start = 1
    else:
        start = 0
    for i in range(start, start + agents):
        agent_rows.append(
            {"index": i, "member_name": f"Person {i}", "role": "population"}
        )
    return RunBundle(
        label=label,
        run_id=1,
        run_name="Testkörning",
        attempt_id="att_1",
        seed="42",
        engine="oasis",
        agents=agent_rows,
        posts=posts
        or [
            {
                "post_id": 1,
                "user_id": start,
                "content": "Belysningen på landsbygden är avgörande för tryggheten.",
                "num_likes": 4,
            },
            {
                "post_id": 2,
                "user_id": start + 1,
                "content": "Enligt rapporten behövs mer data om trygghet.",
                "num_likes": 2,
            },
        ],
        comments=comments
        or [
            {
                "comment_id": 1,
                "post_id": 1,
                "user_id": start + 2,
                "content": "Bra förslag, konkret lösning behövs för belysning.",
                "num_likes": 1,
            },
            {
                "comment_id": 2,
                "post_id": 2,
                "user_id": start + 3,
                "content": "Skandal hur dåligt det skötts — rent valfläsk.",
                "num_likes": 0,
            },
        ],
        ticks_run=3,
        injection_texts=injection_texts
        or [
            "Socialdemokraterna vill stoppa nedsläckningen av vägbelysning "
            "i byar. Belysningen är avgörande för tryggheten."
        ],
    )


def _clf_for(bundle: RunBundle) -> BundleClassification:
    packs = fallback_topic_packs(bundle.injection_texts)
    texts = [
        str(p.get("content") or "")
        for p in [*bundle.posts, *bundle.comments]
        if p.get("content")
    ]
    return BundleClassification(
        topic_packs=packs,
        topic_shares=classify_topics(texts, packs),
        tone_shares=tone_shares_heuristic(texts),
        tone_mode="heuristic",
    )


def test_fallback_topics_belysning_not_aldreomsorg():
    packs = fallback_topic_packs(
        [
            "Socialdemokraterna vill stoppa nedsläckningen av vägbelysning "
            "i byar. Belysningen är avgörande för tryggheten för barn och äldre."
        ]
    )
    assert packs
    assert packs[0].label == "Budskap"
    assert "belysning" in packs[0].keywords or "vägbelysning" in packs[0].keywords
    texts = [
        "Belysningen ska vara kvar i byarna för tryggheten.",
        "Valfläsk om lampor igen.",
        "24 grader över hela Sverige.",
        "Äldreomsorgen behöver mer resurser.",  # should NOT match belysning pack via 'äldre' alone
    ]
    # Ensure pack keywords do not include bare 'äldre' as elderly-care topic
    shares = classify_topics(texts, packs)
    assert "Äldreomsorg" not in shares
    assert shares.get("Budskap", 0) > 0
    assert shares.get("Övrigt", 0) > 0


def test_tone_heuristic_neutral_default():
    shares = tone_shares_heuristic(
        [
            "Lamporna är släckta i Skarphagen.",
            "Skandal och valfläsk från politikerna.",
            "Bra hopp om framtiden.",
        ]
    )
    assert shares["Neutral / oklassad"] > 0
    assert shares["Kritisk / uppgiven"] > 0
    assert shares["Positiv / hoppfull"] > 0


def test_style_unclassified_not_personal_default():
    b = _bundle(
        comments=[
            {
                "comment_id": 1,
                "post_id": 1,
                "user_id": 2,
                "content": "Lamporna i Klocket är släckta varje kväll.",
                "num_likes": 11,
            }
        ],
        posts=[
            {
                "post_id": 1,
                "user_id": 0,
                "content": "Vägbelysning i byarna.",
                "num_likes": 0,
            }
        ],
    )
    m = compute_report_metrics([b], [_clf_for(b)])
    by_style = dict(m.aggregate.style_avg_likes)
    assert by_style.get(STYLE_UNCLASSIFIED, 0) > 0
    # Unmatched texts must not inflate Personlig
    personal = by_style.get("Personlig + hjärtlig berättelse", 0)
    assert personal == 0.0


def test_population_excludes_injectors():
    b = _bundle(agents=3, include_injector=True)
    m = compute_report_metrics([b], [_clf_for(b)])
    assert m.aggregate.agent_count == 3


def test_compute_metrics_single_bundle():
    b = _bundle()
    m = compute_report_metrics([b], [_clf_for(b)])
    assert m.n_runs == 1
    assert m.aggregate.agent_count >= 1
    assert m.aggregate.post_count == 2
    assert "Budskap" in m.aggregate.topic_shares or "Övrigt" in m.aggregate.topic_shares
    assert "Neutral / oklassad" in m.aggregate.tone_shares
    assert m.cross_table[0]["label"] == "A"


def test_compute_metrics_two_bundles():
    a, b = _bundle(label="A"), _bundle(label="B", agents=4)
    m = compute_report_metrics([a, b], [_clf_for(a), _clf_for(b)])
    assert m.n_runs == 2
    assert len(m.bundles) == 2
    assert len(m.cross_table) == 2


def test_chart_slots_contain_donut_and_hbars():
    b = _bundle()
    metrics = compute_report_metrics([b], [_clf_for(b)])
    slots = prefill_chart_slots(metrics)
    assert "donut" in slots["sec02_charts_html"]
    assert "hbar" in slots["sec03_bars_html"] or "hbar-chart" in slots["sec03_bars_html"]
    assert "topic-race" in slots["sec04_topic_race_html"]
    assert "app-grid" in slots["appendix_grid_html"]
    assert 'class="ag-quote"' in render_agents_html(metrics) or "Opinionsröst" in slots[
        "sec05_agents_html"
    ]
    charts = render_sec02_charts(metrics)
    assert "Engagemang" in charts
    assert "Neutral" in charts or "Heuristisk" in charts


def test_sanitize_strips_fences_and_chatter():
    raw = "```html\nLåt mig tänka\n<p>Hej</p>\n```"
    assert sanitize_slot_output("cover_box1_html", raw) == "<p>Hej</p>"
    # Text slots keep prose only (escaped later at render) — no injected tags.
    assert sanitize_slot_output("sec02_intro", "text **fet** här") == "text fet här"


def test_sanitize_converts_markdown_bold_in_html_slots():
    raw = (
        "**Ämnesdrift/agenda:** Diskussionen drivs från de angivna sakfrågorna "
        "(äldreomsorg 18 %, trafik 0 %) till ett dominerande \"Övrigt\"-spår (82 %)."
    )
    out = sanitize_slot_output("sec04_explainer_html", raw)
    assert out.startswith("<strong>Ämnesdrift/agenda:</strong>")
    assert "**" not in out


def test_sanitize_strips_markdown_from_title_slots():
    out = sanitize_slot_output("sec04_h2", "**Ämnesdrift/agenda:** Kort rubrik.")
    assert "**" not in out
    assert out.startswith("Ämnesdrift/agenda:")


def test_sanitize_strips_script_from_html_slots():
    raw = '<p>Hej</p><script>alert(1)</script><div class="fc neu" onclick="x()">ok</div>'
    out = sanitize_slot_output("sec02_findings_html", raw)
    assert "<script" not in out.lower()
    assert "onclick" not in out.lower()
    assert "<p>Hej</p>" in out
    assert 'class="fc neu"' in out


def test_apply_slots_escapes_text_but_keeps_html_slots():
    html = "<title>@@SLOT_page_title@@</title><div>@@SLOT_body_html@@</div>"
    out = apply_slots(
        html,
        {
            "page_title": "</title><script>alert(1)</script><title>",
            "body_html": "<p>ok</p>",
        },
    )
    assert "<script>" not in out
    assert "&lt;/title&gt;&lt;script&gt;alert(1)&lt;/script&gt;&lt;title&gt;" in out
    assert "<p>ok</p>" in out


def test_sanitize_html_slot_hygiene():
    mstep = sanitize_slot_output(
        "method_steps_html",
        '<div class="mstep" mstep-num="1"><h4>A</h4><p>B</p></div>',
    )
    assert 'mstep-num="' not in mstep
    assert '<div class="mstep-num">1</div>' in mstep

    findings = sanitize_slot_output(
        "sec06_findings_html",
        '<div class="fc-neu"><p>x</p></div><div class="fc-cau"><p>y</p></div>',
    )
    assert 'class="fc neu"' in findings
    assert 'class="fc cau"' in findings
    assert "fc-neu" not in findings

    quote = sanitize_slot_output(
        "sec05_agents_html",
        '<div class=ag-quote>Hej</div>',
    )
    assert 'class="ag-quote"' in quote

    lbl = sanitize_slot_output(
        "cover_box3_lbl",
        "Vi testade vilken kommentarsstil som engagerar mest i en lokal politisk "
        "diskussion om trygghet och belysning över hela Sverige med många detaljer.",
    )
    assert len(lbl) <= 48


def test_classify_topics_longest_keyword_wins():
    packs = [
        TopicPack(label="Trygghet", keywords=["trygghet", "belysning"]),
        TopicPack(label="Väder", keywords=["väder"]),
    ]
    shares = classify_topics(
        ["Belysning och trygghet i byn", "Regnväder idag", "Något annat"],
        packs,
    )
    assert shares["Trygghet"] == pytest.approx(1 / 3)
    assert shares["Väder"] == pytest.approx(1 / 3)
    assert shares["Övrigt"] == pytest.approx(1 / 3)


def test_tools_describe_runs():
    b = _bundle()
    tools = ReportToolBundle([b], compute_report_metrics([b], [_clf_for(b)]))
    data = tools.describe_runs()
    assert data["n_runs"] == 1
    assert "notes" in data
    raw = call_tool(tools, "compare_engagement", {})
    assert "gini" in raw


def test_is_ab_comparison_detects_variant_ids():
    a = _bundle(label="Run — Version A")
    a.variant_id = "a"
    b = _bundle(label="Run — Version B", agents=4)
    b.variant_id = "b"
    from app.services.report.bundles import is_ab_comparison

    assert is_ab_comparison([a, b])
    assert not is_ab_comparison([a])


def test_group_questions_into_section_batches():
    questions = _load_questions()
    batches = group_questions_into_batches(questions)
    names = [n for n, _ in batches]
    assert "cover" in names
    assert "infographic" in names
    assert "topics" in names
    # Far fewer LLM calls than one-per-slot
    assert len(batches) <= 8
    total_slots = sum(len(items) for _, items in batches)
    assert total_slots >= 25


@pytest.mark.asyncio
async def test_fill_slot_batch_structured():
    async def fake_structured(messages, response_model):
        assert response_model is SlotBatchResponse
        return SlotBatchResponse(
            slots={
                "sec04_h2": "Belysningen tog över",
                "sec04_intro": "Debatten handlade om trygghet.",
            }
        )

    set_structured_completer(fake_structured)
    try:
        out = await fill_slot_batch(
            digest="fakta",
            multi=False,
            batch_name="topics",
            items=[
                {"slot": "sec04_h2", "question": "Kort rubrik"},
                {"slot": "sec04_intro", "question": "Intro"},
                {"slot": "sec04_explainer_html", "question": "Explainer"},
            ],
        )
        assert out["sec04_h2"] == "Belysningen tog över"
        assert "sec04_explainer_html" not in out  # missing from model → skipped
    finally:
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_fill_narrative_slots_batches_in_parallel(monkeypatch: pytest.MonkeyPatch):
    async def fake_structured(messages, response_model):
        content = messages[-1]["content"] if messages else ""
        slots: dict[str, str] = {}
        for line in content.splitlines():
            if line.startswith("- **") and "**:" in line:
                slot = line.split("**")[1]
                slots[slot] = f"text för {slot}"
        return SlotBatchResponse(slots=slots)

    monkeypatch.setattr(
        "app.services.report.generate.settings.deepseek_api_key",
        "test-key",
    )
    set_structured_completer(fake_structured)
    try:
        b = _bundle()
        tools = ReportToolBundle([b], compute_report_metrics([b], [_clf_for(b)]))
        out = await fill_narrative_slots(
            tools=tools,
            questions=_load_questions(),
            dry_run=False,
        )
        assert len(out) >= 20
        assert "cover_h1" in out or "page_title" in out
    finally:
        set_structured_completer(None)


@pytest.mark.asyncio
async def test_generate_report_dry_run(tmp_path: Path):
    html_path, slots_path, slots = await generate_report_html(
        [_bundle()],
        out_dir=tmp_path / "rpt",
        dry_run=True,
        title="Test",
    )
    assert html_path.is_file()
    assert slots_path.is_file()
    html = html_path.read_text(encoding="utf-8")
    assert "Opinionssimulator" in html or "Simuleringsrapport" in html
    assert "donut" in html or "pyramid" in html or "info-kpi" in html
    assert slots["page_title"]
    assert "infographic_grid_html" in slots
    assert "Äldreomsorg" not in slots.get("meta_topics", "")
    assert "Budskap" in slots.get("meta_topics", "") or "Övrigt" in slots.get(
        "meta_topics", ""
    )


@pytest.mark.asyncio
async def test_generate_report_escapes_hostile_title(tmp_path: Path):
    hostile = '</title><script>alert("xss")</script><title>'
    html_path, _slots_path, slots = await generate_report_html(
        [_bundle(label="Run <img src=x onerror=alert(1)>")],
        out_dir=tmp_path / "rpt_xss",
        dry_run=True,
        title=hostile,
    )
    html = html_path.read_text(encoding="utf-8")
    assert slots["page_title"] == hostile
    assert "<script>" not in html
    assert "<img " not in html
    assert "&lt;/title&gt;&lt;script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
