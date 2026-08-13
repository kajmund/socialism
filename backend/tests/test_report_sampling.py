"""Tests for stratified SSR reaction sampling."""

from __future__ import annotations

import json

import pytest

from app.services.report.bundles import RunBundle
from app.services.report.classify import (
    BundleClassification,
    _style_shares_from_pmfs,
    classify_bundle,
)
from app.services.report.generate import generate_report_html
from app.services.report.sampling import (
    MAX_CLASSIFY_TEXTS,
    MAX_TEXTS_PER_AGENT,
    SAMPLING_METHOD,
    sample_reactions_for_ssr,
    sampling_seed,
)
from app.services.ssr import STYLE_LABELS, set_embedder


def _bundle_with_reactions(
    *,
    reactions: list[tuple[int, str, int]],
    seed: str = "seed-1",
) -> RunBundle:
    posts: list[dict] = []
    comments: list[dict] = []
    agents: list[dict] = [{"index": 0, "member_name": "Parti", "role": "injector"}]
    for idx, (user_id, text, likes) in enumerate(reactions, start=1):
        agents.append(
            {"index": user_id, "member_name": f"Agent {user_id}", "role": "population"}
        )
        row = {
            "user_id": user_id,
            "content": text,
            "num_likes": likes,
        }
        if idx % 2 == 0:
            row["comment_id"] = idx
            row["post_id"] = 1
            comments.append(row)
        else:
            row["post_id"] = idx
            posts.append(row)
    return RunBundle(
        label="Test",
        run_id=1,
        run_name="Testkörning",
        attempt_id="att_1",
        seed=seed,
        engine="oasis",
        agents=agents,
        posts=posts,
        comments=comments,
        variant_id="main",
    )


def test_sampling_is_deterministic_for_same_seed():
    reactions = [(i, f"text {i}-{j}", j) for i in range(1, 6) for j in range(3)]
    bundle = _bundle_with_reactions(reactions=reactions)
    first = sample_reactions_for_ssr(bundle)
    second = sample_reactions_for_ssr(bundle)
    assert first.texts == second.texts
    assert first.user_ids == second.user_ids
    assert first.meta["seed"] == sampling_seed(bundle)


def test_sampling_excludes_injector():
    bundle = _bundle_with_reactions(reactions=[(0, "injector post", 99), (1, "citizen", 1)])
    result = sample_reactions_for_ssr(bundle)
    assert result.texts == ["citizen"]
    assert result.user_ids == [1]


def test_sampling_respects_max_per_agent():
    reactions = [(1, f"agent1-{i}", i) for i in range(10)]
    reactions += [(2, f"agent2-{i}", i) for i in range(10)]
    bundle = _bundle_with_reactions(reactions=reactions)
    result = sample_reactions_for_ssr(bundle, limit=16, max_per_agent=2)
    assert len(result.texts) == 4
    assert result.user_ids.count(1) <= 2
    assert result.user_ids.count(2) <= 2


def test_sampling_spreads_across_agents_not_top_likes():
    reactions: list[tuple[int, str, int]] = []
    for i in range(20):
        reactions.append((1, f"loud-{i}", 100))
    for agent_id in range(2, 10):
        reactions.append((agent_id, f"quiet-{agent_id}", 0))
    bundle = _bundle_with_reactions(reactions=reactions)
    result = sample_reactions_for_ssr(bundle, limit=16, max_per_agent=2)
    unique_agents = set(result.user_ids)
    assert len(unique_agents) >= 8
    assert result.user_ids.count(1) <= 2


def test_sampling_collect_all_when_under_cap():
    reactions = [(1, "a", 0), (2, "b", 1), (3, "c", 2)]
    bundle = _bundle_with_reactions(reactions=reactions)
    result = sample_reactions_for_ssr(bundle)
    assert len(result.texts) == 3
    assert result.meta["selected_count"] == 3
    assert result.meta["eligible_count"] == 3


def test_collect_all_reactions_for_ssr():
    from app.services.report.sampling import collect_all_reactions_for_ssr

    reactions = [(1, "a", 0), (2, "b", 1)]
    bundle = _bundle_with_reactions(reactions=reactions)
    result = collect_all_reactions_for_ssr(bundle)
    assert result.texts == ["a", "b"]
    assert result.meta["method"] == "all"
    assert result.meta["selected_count"] == 2


def test_style_shares_split_across_rated_texts():
    pmf_a = {lab: 0.0 for lab in STYLE_LABELS}
    pmf_a[STYLE_LABELS[0]] = 1.0
    pmf_b = {lab: 0.0 for lab in STYLE_LABELS}
    pmf_b[STYLE_LABELS[1]] = 1.0
    by_style = dict(_style_shares_from_pmfs([pmf_a, pmf_b]))
    assert by_style[STYLE_LABELS[0]] == pytest.approx(0.5)
    assert by_style[STYLE_LABELS[1]] == pytest.approx(0.5)
    assert sum(by_style.values()) == pytest.approx(1.0)
    only_a = dict(_style_shares_from_pmfs([pmf_a, pmf_a, pmf_a]))
    assert only_a[STYLE_LABELS[0]] == pytest.approx(1.0)
    assert only_a[STYLE_LABELS[1]] == pytest.approx(0.0)


def test_style_shares_reflect_soft_mass_not_presence():
    """A style with a sliver of mass must not read the same as a dominant one."""
    pmf = {lab: 0.0 for lab in STYLE_LABELS}
    pmf[STYLE_LABELS[0]] = 0.9
    pmf[STYLE_LABELS[1]] = 0.1
    by_style = dict(_style_shares_from_pmfs([pmf]))
    assert by_style[STYLE_LABELS[0]] == pytest.approx(0.9)
    assert by_style[STYLE_LABELS[1]] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_classify_bundle_records_sampling_meta():
    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0, 0.0] for _ in texts]

    set_embedder(_fake_embed)
    try:
        bundle = _bundle_with_reactions(
            reactions=[(i, f"text-{i}", i) for i in range(1, 5)]
        )
        clf = await classify_bundle(bundle, locale="sv")
        assert clf.sampling["method"] == SAMPLING_METHOD
        assert clf.sampling["max_texts"] == MAX_CLASSIFY_TEXTS
        assert clf.sampling["max_per_agent"] == MAX_TEXTS_PER_AGENT
        assert len(clf.sample_texts) == len(clf.sample_user_ids)
    finally:
        set_embedder(None)


@pytest.mark.asyncio
async def test_generate_report_writes_sampling_block(tmp_path):
    async def _fake_embed(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0, 0.0] for _ in texts]

    set_embedder(_fake_embed)
    try:
        bundle = _bundle_with_reactions(
            reactions=[(i, f"text-{i}", i) for i in range(1, 6)]
        )
        await generate_report_html([bundle], out_dir=tmp_path / "rpt")
        doc = json.loads((tmp_path / "rpt" / "report.ssr.json").read_text(encoding="utf-8"))
        assert doc["sampling_method"] == SAMPLING_METHOD
        assert doc["bundles"][0]["sampling"]["method"] == SAMPLING_METHOD
        assert doc["recommendation"]["score"] >= 0
        assert doc["recommendation"]["action"]
        assert doc["recommendation"]["verdict_key"]
        assert doc["report_thresholds"]["verdict"]["pos_strong"] == 0.50
        assert doc["report_thresholds"]["recommendation"]["score_triggers"]["strong_pos"] == 0.45
        html = (tmp_path / "rpt" / "report.html").read_text(encoding="utf-8")
        assert "SSR-sampling" in html or "SSR sampling" in html
    finally:
        set_embedder(None)
