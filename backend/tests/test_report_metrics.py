"""Unit tests for report metrics, SSR classify, and quick generate."""

from __future__ import annotations

from pathlib import Path

from app.schemas.domain import Injection, Tick

import pytest

from app.llm import set_structured_completer
from app.services.report.bundles import RunBundle, _injection_texts_from_ticks
from app.services.report.charts import (
    render_agents_html,
    render_engagement_donut,
    render_quick_charts,
)
from app.services.report.classify import (
    BundleClassification,
    TopicPack,
    classify_styles,
    classify_tones,
    classify_topics_by_keywords,
    topic_packs_from_injections,
)
from app.services.report.generate import generate_report_html
from app.services.report.metrics import STYLE_UNCLASSIFIED, compute_report_metrics
from app.services.ssr import STYLE_LABELS, set_embedder
from app.services.ssr.anchors import TONE_LABELS_EN, TONE_LABELS_SV


def _bundle(
    *,
    label: str = "A",
    agents: int = 5,
    posts: list[dict] | None = None,
    comments: list[dict] | None = None,
    injection_texts: list[str] | None = None,
    include_injector: bool = True,
) -> RunBundle:
    texts = injection_texts or [
        "Socialdemokraterna vill stoppa nedsläckningen av vägbelysning "
        "i byar. Belysningen är avgörande för tryggheten."
    ]
    agent_rows: list[dict] = []
    bundle_posts: list[dict] = []
    if include_injector:
        agent_rows.append(
            {"index": 0, "member_name": "Partikonto", "role": "injector"}
        )
        bundle_posts.append(
            {
                "post_id": 1,
                "user_id": 0,
                "content": texts[0],
                "num_likes": 4,
            }
        )
        start = 1
        citizen_post_id = 2
    else:
        start = 0
        citizen_post_id = 1
    for i in range(start, start + agents):
        agent_rows.append(
            {"index": i, "member_name": f"Person {i}", "role": "population"}
        )
    if posts is None:
        bundle_posts.extend(
            [
                {
                    "post_id": citizen_post_id,
                    "user_id": start,
                    "content": "Belysningen på landsbygden är avgörande för tryggheten.",
                    "num_likes": 4,
                },
                {
                    "post_id": citizen_post_id + 1,
                    "user_id": start + 1,
                    "content": "Enligt rapporten behövs mer data om trygghet.",
                    "num_likes": 2,
                },
            ]
        )
    else:
        bundle_posts = posts
    if comments is None:
        bundle_comments = [
            {
                "comment_id": 1,
                "post_id": 1 if include_injector else citizen_post_id,
                "user_id": start + 2,
                "content": "Bra förslag, konkret lösning behövs för belysning.",
                "num_likes": 1,
            },
            {
                "comment_id": 2,
                "post_id": citizen_post_id + 1,
                "user_id": start + 3,
                "content": "Skandal hur dåligt det skötts — rent valfläsk.",
                "num_likes": 0,
            },
        ]
    else:
        bundle_comments = comments
    return RunBundle(
        label=label,
        run_id=1,
        run_name="Testkörning",
        attempt_id="att_1",
        seed="42",
        engine="oasis",
        agents=agent_rows,
        posts=bundle_posts,
        comments=bundle_comments,
        ticks_run=3,
        injection_texts=texts,
    )


def _clf_for(bundle: RunBundle) -> BundleClassification:
    """Deterministic classification for metrics tests (no LLM)."""
    packs = [TopicPack(label="Belysning", keywords=["belysning"])]
    tone_shares = {lab: 0.2 for lab in TONE_LABELS_SV}
    style_shares = [(lab, 1.0 if i == 0 else 0.0) for i, lab in enumerate(STYLE_LABELS)]
    style_shares.append((STYLE_UNCLASSIFIED, 0.0))
    return BundleClassification(
        topic_packs=packs,
        topic_shares={"Belysning": 0.75, "Övrigt": 0.25},
        tone_shares=tone_shares,
        tone_mode="ssr",
        style_shares=style_shares,
    )


async def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic embeddings: one-hot-ish vectors by text hash."""
    out: list[list[float]] = []
    for t in texts:
        v = [0.0] * 8
        v[hash(t) % 8] = 1.0
        v[(hash(t) // 8) % 8] = 0.5
        out.append(v)
    return out


def test_topic_packs_and_keyword_classify():
    packs = topic_packs_from_injections(
        [
            "Socialdemokraterna vill stoppa nedsläckningen av vägbelysning "
            "i byar. Belysningen är avgörande för tryggheten."
        ]
    )
    assert packs
    assert any("belysning" in k for p in packs for k in p.keywords) or any(
        "belysning" in p.label.lower() for p in packs
    )
    texts = [
        "Belysningen ska vara kvar i byarna.",
        "Skandal och valfläsk.",
        "24 grader över hela Sverige.",
    ]
    topic_shares = classify_topics_by_keywords(texts, packs)
    assert "Övrigt" in topic_shares
    assert sum(topic_shares.values()) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_classify_tones_ssr():
    set_embedder(_fake_embed)
    try:
        texts = [
            "Belysningen ska vara kvar i byarna.",
            "Skandal och valfläsk.",
        ]
        tone_shares, mode, rated, _pmfs, _embed_s = await classify_tones(texts)
        assert mode == "ssr"
        assert rated == texts
        assert set(tone_shares) == set(TONE_LABELS_SV)
        assert sum(tone_shares.values()) == pytest.approx(1.0)
    finally:
        set_embedder(None)


@pytest.mark.asyncio
async def test_classify_styles_embeds_reaction_texts_directly():
    set_embedder(_fake_embed)
    try:
        texts = [
            "Ironiskt med statistik som visar att det är skandal.",
            "Skäms ni — idiotiskt lögnaktigt absolut noll!",
        ]
        style_shares, rated, pmfs, _embed_s = await classify_styles(texts)
        assert rated[0].startswith("Ironiskt")
        assert len(pmfs) == 2
        by_style = dict(style_shares)
        assert "Sarkastisk + konkret kritik" in by_style
        assert "Provocerande / konfronterande" in by_style
        assert sum(by_style.values()) == pytest.approx(1.0)
    finally:
        set_embedder(None)


def test_style_shares_come_from_classification():
    b = _bundle()
    clf = _clf_for(b)
    clf.style_shares = [
        ("Sarkastisk + konkret kritik", 0.6),
        ("Personlig + hjärtlig berättelse", 0.0),
        (STYLE_UNCLASSIFIED, 0.4),
    ]
    m = compute_report_metrics([b], [clf])
    by_style = dict(m.aggregate.style_shares)
    assert by_style["Sarkastisk + konkret kritik"] == 0.6
    assert by_style.get("Personlig + hjärtlig berättelse", 0) == 0.0


def test_population_excludes_injectors():
    b = _bundle(agents=3, include_injector=True)
    m = compute_report_metrics([b], [_clf_for(b)])
    assert m.aggregate.agent_count == 3


def test_compute_metrics_single_bundle():
    b = _bundle(include_injector=True)
    m = compute_report_metrics([b], [_clf_for(b)])
    assert m.n_runs == 1
    assert m.aggregate.agent_count >= 1
    assert m.aggregate.post_count == 3
    assert "Belysning" in m.aggregate.topic_shares or "Övrigt" in m.aggregate.topic_shares
    assert "Neutral" in m.aggregate.tone_shares
    assert m.tone_mode == "ssr"
    assert m.cross_table[0]["label"] == "A"


def test_compute_metrics_two_bundles():
    a, b = _bundle(label="A"), _bundle(label="B", agents=4)
    m = compute_report_metrics([a, b], [_clf_for(a), _clf_for(b)])
    assert m.n_runs == 2
    assert len(m.bundles) == 2
    assert len(m.cross_table) == 2


def test_aggregate_engagement_tiers_sum_to_agent_count():
    """Donut segments and the printed agent count must share one denominator."""
    bundles = [
        _bundle(label="Cynisk", agents=5),
        _bundle(label="Balanserad", agents=5),
        _bundle(label="Realistisk", agents=4),
    ]
    m = compute_report_metrics(bundles, [_clf_for(b) for b in bundles])
    agg = m.aggregate
    assert agg.top_agents + agg.mid_agents + agg.zero_like_agents == agg.agent_count


def test_engagement_donut_caption_matches_tiers():
    bundles = [_bundle(label="A", agents=5, include_injector=True)]
    metrics = compute_report_metrics(bundles, [_clf_for(b) for b in bundles])
    agg = metrics.aggregate
    html = render_engagement_donut(metrics, locale="sv")
    assert f"Av {agg.agent_count} simulerade medborgare" in html
    assert agg.injector_count == 1
    assert "exkl. 1 institutionellt konto" in html


def test_quick_charts_contain_donut_and_hbars():
    b = _bundle()
    metrics = compute_report_metrics([b], [_clf_for(b)])
    charts = render_quick_charts(metrics, locale="sv", ab=False)
    assert "donut" in charts
    assert "hbar" in charts or "hbar-chart" in charts
    assert "Engagemang" in charts
    assert "SSR" in charts or "ton" in charts.lower()


def test_opinion_leaders_use_persona_profile_line_not_name():
    b = _bundle(agents=1)
    b.agents = [
        {"index": 0, "persona_id": "p1", "member_name": "Anna", "role": "population"}
    ]
    b.personas = [
        {
            "persona_id": "p1",
            "name": "Anna",
            "bio": {
                "yrke": "Butiksbiträde",
                "age": "29",
                "ort": "Hageby",
                "lutning": "Höger",
            },
        }
    ]
    m = compute_report_metrics([b], [_clf_for(b)])
    html = render_agents_html(m, locale="sv")
    assert "Butiksbiträde · 29 år · Hageby · lutning höger" in html
    assert "Anna" not in html


def test_is_ab_comparison_detects_variant_ids():
    a = _bundle(label="Run — Version A")
    a.variant_id = "a"
    b = _bundle(label="Run — Version B", agents=4)
    b.variant_id = "b"
    from app.services.report.bundles import is_ab_comparison

    assert is_ab_comparison([a, b])
    assert not is_ab_comparison([a])


@pytest.mark.asyncio
async def test_generate_quick_report(tmp_path: Path):
    async def _no_llm(_messages, _model):
        raise AssertionError("quick report must not call DeepSeek")

    set_structured_completer(_no_llm)
    set_embedder(_fake_embed)
    try:
        html_path, slots_path, slots, timing = await generate_report_html(
            [_bundle()],
            out_dir=tmp_path / "rpt_quick",
            title="Snabb",
        )
        assert html_path.is_file()
        assert slots_path.is_file()
        assert (tmp_path / "rpt_quick" / "report.ssr.json").is_file()
        html = html_path.read_text(encoding="utf-8")
        assert 'lang="sv"' in html
        assert "Snabbrapport" in html or "Snabb" in html
        assert "Rekommendation" in html or "Publicera" in html or "publicera" in html
        assert "Statistik" in html or "Static statistics" in html
        assert "chart-grid" in html
        assert "stats-table" in html
        assert "Målgruppsanalys" in html
        assert "tech" in html
        assert slots.get("recommendation_html")
        assert slots["page_title"]
        assert timing["classify_llm_seconds"] == 0.0
        assert timing["embed_seconds"] >= 0.0
    finally:
        set_structured_completer(None)
        set_embedder(None)


@pytest.mark.asyncio
async def test_generate_english_quick_report(tmp_path: Path):
    async def _no_llm(_messages, _model):
        raise AssertionError("quick report must not call DeepSeek")

    set_structured_completer(_no_llm)
    set_embedder(_fake_embed)
    try:
        html_path, _slots_path, slots, _timing = await generate_report_html(
            [_bundle()],
            out_dir=tmp_path / "rpt_en",
            title="My report",
            locale="en",
        )
        html = html_path.read_text(encoding="utf-8")
        assert 'lang="en"' in html
        assert "Quick report" in html
        assert "My report" in html
        assert "Snabbrapport" not in html
        assert set(TONE_LABELS_EN)  # locale anchors exist
        assert slots["page_title"]
    finally:
        set_structured_completer(None)
        set_embedder(None)


@pytest.mark.asyncio
async def test_generate_report_escapes_hostile_title(tmp_path: Path):
    async def _no_llm(_messages, _model):
        raise AssertionError("quick report must not call DeepSeek")

    set_structured_completer(_no_llm)
    set_embedder(_fake_embed)
    try:
        hostile = '</title><script>alert("xss")</script><title>'
        html_path, _slots_path, slots, _timing = await generate_report_html(
            [_bundle(label="Run <img src=x onerror=alert(1)>")],
            out_dir=tmp_path / "rpt_xss",
            title=hostile,
        )
        html = html_path.read_text(encoding="utf-8")
        assert slots["page_title"] == hostile
        assert "<script>" not in html
        assert "<img " not in html
        assert "&lt;/title&gt;&lt;script&gt;" in html
        assert "&lt;img src=x onerror=alert(1)&gt;" in html
    finally:
        set_structured_completer(None)
        set_embedder(None)


def test_injection_texts_from_ticks_includes_link_url():
    ticks = [
        Tick(
            key="t1",
            day=1,
            injections=[
                Injection(
                    key="i1",
                    type="news_post",
                    sender="Lokalnyheterna",
                    text="Vårdcentralen får ny chef",
                    mode="link",
                    url="https://example.com/nyheter/vardcentral",
                    sourceDomain="example.com",
                )
            ],
        )
    ]
    texts = _injection_texts_from_ticks(ticks)
    assert texts == [
        "Vårdcentralen får ny chef\nhttps://example.com/nyheter/vardcentral"
    ]


def test_injection_texts_from_ticks_skips_silent_ticks():
    ticks = [
        Tick(
            key="silent",
            day=1,
            silent=True,
            injections=[
                Injection(
                    key="i0",
                    type="party_post",
                    sender="Partiet",
                    text="Ska inte synas",
                )
            ],
        ),
        Tick(
            key="t1",
            day=2,
            injections=[
                Injection(
                    key="i1",
                    type="party_post",
                    sender="Partiet",
                    text="Synligt budskap",
                )
            ],
        ),
    ]
    assert _injection_texts_from_ticks(ticks) == ["Synligt budskap"]
