"""Unit tests for lexical convergence detection."""

import json
from pathlib import Path

import pytest

from app.services.lexical_convergence import (
    CONVERGENCE_AGENT_SHARE_THRESHOLD,
    analyze_lexical_convergence,
)


def _agents(n: int) -> list[dict]:
    return [
        {"index": i, "username": f"u{i}", "member_name": f"Agent {i}", "role": "population"}
        for i in range(n)
    ]


def test_no_warnings_when_agents_diverge():
    agents = _agents(5)
    comments = [
        {"comment_id": 0, "post_id": 1, "user_id": 0, "content": "Skolan behöver mer pengar nu"},
        {"comment_id": 1, "post_id": 1, "user_id": 1, "content": "Vårdens köer är för långa"},
        {"comment_id": 2, "post_id": 1, "user_id": 2, "content": "Bussarna går sällan på kvällen"},
        {"comment_id": 3, "post_id": 1, "user_id": 3, "content": "Hyresrätt kostar för mycket"},
        {"comment_id": 4, "post_id": 1, "user_id": 4, "content": "Elpriset oroar mig verkligen"},
    ]
    result = analyze_lexical_convergence(agents=agents, comments=comments)
    assert result["population_agents"] == 5
    assert result["threshold"] == CONVERGENCE_AGENT_SHARE_THRESHOLD
    assert result["warnings"] == []


def test_cross_agent_convergence_flags_shared_phrase():
    shared = "samma exakt fras här"
    agents = _agents(5)
    comments = [
        {
            "comment_id": i,
            "post_id": 1,
            "user_id": i,
            "content": shared if i < 3 else f"Helt annat {i}",
        }
        for i in range(5)
    ]
    result = analyze_lexical_convergence(
        agents=agents,
        comments=comments,
        threshold=0.40,
    )
    kinds = {w["kind"] for w in result["warnings"]}
    assert "cross_agent_convergence" in kinds
    hit = next(
        w
        for w in result["warnings"]
        if w["phrase"].casefold() in shared.casefold()
    )
    assert hit["agent_count"] == 3
    assert hit["agent_share"] == 0.6


def test_source_phrase_echo_from_injection():
    agents = _agents(4)
    injection = "Regeringen föreslår tolvmiljarders satsning på skolan"
    echo = "tolvmiljarders satsning på"
    comments = [
        {
            "comment_id": i,
            "post_id": 1,
            "user_id": i,
            "content": f"Jag tycker {echo} är rimligt" if i < 3 else "Nej tack",
        }
        for i in range(4)
    ]
    result = analyze_lexical_convergence(
        agents=agents,
        comments=comments,
        injection_texts=[("tick_day1", injection)],
        threshold=0.40,
    )
    echo_warnings = [w for w in result["warnings"] if w["kind"] == "source_phrase_echo"]
    assert echo_warnings
    assert any(w["source"] == "tick_day1" for w in echo_warnings)
    assert any("tolvmiljarders satsning" in w["phrase"] for w in echo_warnings)


def test_excludes_injector_posts():
    agents = [
        {"index": 0, "username": "news", "member_name": "Nyheter", "role": "injector"},
        {"index": 1, "username": "a1", "member_name": "Anna", "role": "population"},
        {"index": 2, "username": "a2", "member_name": "Bo", "role": "population"},
    ]
    posts = [
        {"post_id": 1, "user_id": 0, "content": "identisk nyhetsfras i artikeln"},
        {"post_id": 2, "user_id": 1, "content": "kort reaktion"},
        {"post_id": 3, "user_id": 2, "content": "annan reaktion"},
    ]
    result = analyze_lexical_convergence(agents=agents, posts=posts, threshold=0.40)
    assert result["population_agents"] == 2
    assert result["warnings"] == []


def test_anchor_bigram_catches_shared_opening_with_varied_tail():
    """Two-word anchor when continuations differ (kollektivt döma + …)."""
    agents = _agents(15)
    tails = [
        "nätverk för vad andra gjort",
        "hela nätverk",
        "folk",
        "för vad andra gjort",
        "nätverket",
        "hela folket",
        "andra",
        "grannar",
        "kompisar",
        "bekanta",
        "släkten",
        "kollegor",
        "gruppen",
    ]
    comments = [
        {
            "comment_id": i,
            "post_id": 1,
            "user_id": i,
            "content": f"Kollektivt döma {tails[i]}" if i < 13 else f"Helt annat {i}",
        }
        for i in range(15)
    ]
    result = analyze_lexical_convergence(
        agents=agents,
        comments=comments,
        threshold=0.40,
    )
    anchor_hits = [
        w
        for w in result["warnings"]
        if w["kind"] == "cross_agent_convergence"
        and w["phrase"].casefold() == "kollektivt döma"
    ]
    assert anchor_hits
    assert anchor_hits[0]["agent_count"] == 13
    assert anchor_hits[0]["agent_share"] == round(13 / 15, 3)


def test_kollektiv_bestraffning_merges_case_and_inflection_variants():
    """Regression: run 6 control — 5/12 agents, split by case without normalization."""
    agents = _agents(12)
    variants = [
        "Kollektiv bestraffning låter inte som rättssäkerhet.",
        "Kollektiv bestraffning skrämmer mig.",
        "Kollektiv bestraffning låter farligt i mina öron.",
        "Låter bra på pappret, men kollektiv bestraffning känns otäckt.",
        "Kollektiv bestraffningen betyder att oskyldiga åker dit.",
        "Kollektivt straffa hela nätverk låter fel.",
        "Helt annat resonemang här.",
        "Också något helt annat.",
        "Ingen koppling alls.",
        "Bara hyra och mat.",
        "Skolan behöver mer stöd.",
        "Vårdens köer är för långa.",
    ]
    comments = [
        {
            "comment_id": i,
            "post_id": 1,
            "user_id": i,
            "content": variants[i],
        }
        for i in range(12)
    ]
    result = analyze_lexical_convergence(
        agents=agents,
        comments=comments,
        threshold=0.40,
    )
    kollektiv_hits = [
        w
        for w in result["warnings"]
        if w["kind"] == "cross_agent_convergence"
        and "kollektiv" in w["phrase"].casefold()
        and "bestraff" in w["phrase"].casefold()
    ]
    assert kollektiv_hits, "expected kollektiv bestraffning-family convergence"
    top = max(kollektiv_hits, key=lambda w: w["agent_count"])
    assert top["agent_count"] == 5
    assert top["agent_share"] == round(5 / 12, 3)


def test_run6_control_transcript_triggers_warning():
    """Verify stored run 6 control variant after normalization fix."""
    run_path = Path("/tmp/run6.json")
    if not run_path.exists():
        pytest.skip("run 6 export not present locally")
    data = json.loads(run_path.read_text())
    att = data["results"]["attempts"][0]
    variant = next(v for v in att["variants"] if v["id"] == "b")
    result = analyze_lexical_convergence(
        posts=variant.get("posts"),
        comments=variant.get("comments"),
        agents=variant.get("agents"),
    )
    kollektiv = [
        w
        for w in result["warnings"]
        if "kollektiv" in w["phrase"].casefold()
        and "bestraff" in w["phrase"].casefold()
    ]
    assert kollektiv
    assert kollektiv[0]["agent_count"] == 5
    assert kollektiv[0]["agent_share"] >= 0.40
