"""HTML chart / finding fragments from ReportMetrics (no LLM)."""

from __future__ import annotations

from html import escape

from app.services.report.bundles import RunBundle
from app.services.report.locale import (
    ReportLocale,
    display_style_label,
    other_topic_label,
    runs_label,
)
from app.services.report.metrics import ReportMetrics, confidence_badge, fmt_num, pct
from app.services.report.recommendation import QuickRecommendation
from app.services.report.segment_analysis import (
    AudienceSegmentSummary,
    build_audience_summaries,
    interview_quote_label,
    interview_section_caption,
)
from app.services.report.classify import BundleClassification
from app.services.report.tick_report import (
    InterviewQA,
    TickStatsRow,
    build_tick_stats,
    extract_interview_qa,
)

# Report chart palette (warm paper-adjacent tones for HTML reports)
C_PRIMARY = "#1E3A55"
C_PRIMARY_2 = "#2D5378"
C_SOFT = "#DDE5EE"
C_ORANGE = "#C96B3A"
C_GREEN = "#5F7A4C"
C_ROSE = "#B0563F"
C_AMBER = "#D8A14A"
C_MUTED = "#6B6253"
C_INK = "#1A1814"

_TOPIC_PALETTE = (C_PRIMARY, C_ORANGE, C_PRIMARY_2, C_GREEN, C_AMBER, C_MUTED, C_ROSE)


def _topic_color(label: str, index: int, *, locale: ReportLocale = "sv") -> str:
    if label == other_topic_label(locale):
        return C_MUTED
    return _TOPIC_PALETTE[index % len(_TOPIC_PALETTE)]


def _badge_html(kind: str, n: int, locale: ReportLocale) -> str:
    if locale == "en":
        if kind == "confirmed":
            return f'<span class="badge confirmed">Confirmed in all {n} tests</span>'
        if kind == "indicated":
            return f'<span class="badge indicated">Tendency in {n} tests</span>'
        return '<span class="badge single">Observation</span>'
    if kind == "confirmed":
        return f'<span class="badge confirmed">Bekräftat i alla {n} tester</span>'
    if kind == "indicated":
        return f'<span class="badge indicated">Tendens i {n} tester</span>'
    return '<span class="badge single">Observation</span>'


def _donut(shares: list[tuple[str, float, str]], center: str) -> str:
    """CSS conic-gradient donut + legend."""
    if not shares:
        return "<p>—</p>"
    stops: list[str] = []
    acc = 0.0
    for _, share, color in shares:
        nxt = acc + max(0.0, share) * 100
        stops.append(f"{color} {acc:.1f}% {nxt:.1f}%")
        acc = nxt
    gradient = ", ".join(stops) if stops else f"{C_SOFT} 0% 100%"
    legend_items = []
    for label, share, color in shares:
        legend_items.append(
            f'<div class="leg-item"><span class="leg-dot" style="background:{color}"></span>'
            f"{escape(label)} ({pct(share)})</div>"
        )
    return (
        f'<div class="donut-wrap">'
        f'<div class="donut" style="background:conic-gradient({gradient})">'
        f'<div class="donut-hole"><span>{escape(center)}</span></div></div>'
        f'<div class="legend">{"".join(legend_items)}</div></div>'
    )


def render_engagement_donut(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    m = metrics.aggregate
    total = max(1, m.top_agents + m.mid_agents + m.zero_like_agents)
    if locale == "en":
        shares = [
            ("Top engaged", m.top_agents / total, C_PRIMARY),
            ("Some activity", m.mid_agents / total, C_PRIMARY_2),
            ("No likes at all", m.zero_like_agents / total, C_SOFT),
        ]
        title = "Engagement in the debate"
        sub = f"Of {m.agent_count} simulated citizens"
    else:
        shares = [
            ("Toppengagerade", m.top_agents / total, C_PRIMARY),
            ("Viss aktivitet", m.mid_agents / total, C_PRIMARY_2),
            ("Inga likes alls", m.zero_like_agents / total, C_SOFT),
        ]
        title = "Engagemang i debatten"
        sub = f"Av {m.agent_count} simulerade medborgare"
    return (
        '<div class="chart-card">'
        f"<h4>{title}</h4>"
        f'<div class="chart-sub">{sub}</div>'
        f"{_donut(shares, str(m.zero_like_agents))}"
        "</div>"
    )


def render_topic_donut(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    m = metrics.aggregate
    ordered = sorted(m.topic_shares.items(), key=lambda x: x[1], reverse=True)
    shares = [(k, v, _topic_color(k, i, locale=locale)) for i, (k, v) in enumerate(ordered)]
    top = ordered[0][0] if ordered else "—"
    if locale == "en":
        title = "What was discussed?"
        sub = "Topic distribution in text (keywords from injections)"
    else:
        title = "Vad diskuterades?"
        sub = "Ämnesfördelning i text (nyckelord från injektioner)"
    return (
        '<div class="chart-card">'
        f"<h4>{title}</h4>"
        f'<div class="chart-sub">{sub}</div>'
        f"{_donut(shares, top[:12])}"
        "</div>"
    )


def render_tone_donut(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    m = metrics.aggregate
    if locale == "en":
        colors = {
            "Strongly negative": C_ROSE,
            "Somewhat negative": "#C47A5A",
            "Neutral": C_MUTED,
            "Somewhat positive": C_GREEN,
            "Strongly positive": C_AMBER,
        }
        title = "Debate tone"
        sub = "SSR distribution (5-level) — embeddings vs tone anchors"
        center = "tone"
    else:
        colors = {
            "Starkt negativ": C_ROSE,
            "Något negativ": "#C47A5A",
            "Neutral": C_MUTED,
            "Något positiv": C_GREEN,
            "Starkt positiv": C_AMBER,
        }
        title = "Debattens ton"
        sub = "SSR-fördelning (5 nivåer) — embeddings mot tonankare"
        center = "ton"
    # Stable Likert order left→right on legend when present
    order = list(colors.keys())
    ordered_items = [(k, m.tone_shares[k]) for k in order if k in m.tone_shares]
    ordered_items.extend(
        (k, v) for k, v in m.tone_shares.items() if k not in colors
    )
    shares = [(k, v, colors.get(k, C_MUTED)) for k, v in ordered_items]
    return (
        '<div class="chart-card">'
        f"<h4>{title}</h4>"
        f'<div class="chart-sub">{sub}</div>'
        f"{_donut(shares, center)}"
        "</div>"
    )


def render_sec02_charts(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    return (
        render_engagement_donut(metrics, locale=locale)
        + render_topic_donut(metrics, locale=locale)
        + render_tone_donut(metrics, locale=locale)
    )


def render_style_hbars(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    styles = metrics.aggregate.style_avg_likes
    max_v = max((v for _, v in styles), default=1.0) or 1.0
    palette = [C_PRIMARY, C_PRIMARY_2, C_GREEN, C_ORANGE, C_MUTED, C_ROSE]
    rows = []
    for i, (label, avg) in enumerate(styles):
        width = max(2, round((avg / max_v) * 100)) if avg > 0 else 2
        color = palette[i % len(palette)]
        zero_cls = " hb-zero" if avg <= 0 else ""
        shown = display_style_label(label, locale)
        rows.append(
            f'<div class="hbar-row">'
            f'<div class="hbar-lbl">{escape(shown)}</div>'
            f'<div class="hbar-track"><div class="hbar-fill{zero_cls}" '
            f'style="width:{width}%;background:{color}">{fmt_num(avg)}</div></div>'
            f'<div class="hbar-val">{fmt_num(avg)}</div></div>'
        )
    if locale == "en":
        title = "Average likes per message style"
        sub = "SSR style rating — soft-weighted likes per style"
    else:
        title = "Genomsnittliga likes per budskapsstil"
        sub = "SSR-stilranking — mjuka vikter × likes per stil"
    return (
        '<div class="chart-card">'
        f"<h4>{title}</h4>"
        f'<div class="chart-sub">{sub}</div>'
        f'<div class="hbar-chart">{"".join(rows)}</div></div>'
    )


def render_topic_race(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    shares = metrics.aggregate.topic_shares
    rows = []
    ordered = sorted(shares.items(), key=lambda x: x[1], reverse=True)
    share_note = "share of matched text" if locale == "en" else "andel av matchad text"
    for i, (topic, share) in enumerate(ordered):
        w = max(2, round(share * 100))
        color = _topic_color(topic, i, locale=locale)
        rows.append(
            f'<div class="topic-row">'
            f'<div class="t-name">{escape(topic)}'
            f"<small>{share_note}</small></div>"
            f'<div class="t-track"><div class="t-fill" style="width:{w}%;background:{color}">'
            f"</div></div>"
            f'<div class="t-pct">{pct(share)}</div></div>'
        )
    return f'<div class="topic-race">{"".join(rows)}</div>'


def render_infographic_grid(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    m = metrics.aggregate
    n = metrics.n_runs
    top_style = m.style_avg_likes[0] if m.style_avg_likes else ("—", 0.0)
    top_topic = max(m.topic_shares, key=m.topic_shares.get) if m.topic_shares else "—"
    top_share = m.topic_shares.get(top_topic, 0.0)
    top_style_label = display_style_label(top_style[0], locale)
    style_rows = [
        (display_style_label(s, locale), a) for s, a in m.style_avg_likes[:5]
    ]

    if locale == "en":
        pyramid = (
            f'<div class="info-card tall">'
            f'<div class="info-card-label">Who engaged?</div>'
            f'<div class="info-card-title">Engagement gathered around a few</div>'
            f'<div class="pyramid">'
            f'<div class="pyr-top">{m.top_agents}<span>Led</span></div>'
            f'<div class="pyr-mid">{m.mid_agents}<span>Participated</span></div>'
            f'<div class="pyr-base">{m.zero_like_agents}<span>Scrolled past</span></div>'
            f"</div>"
            f'<p class="chart-sub">of {m.agent_count} simulated citizens · Gini {fmt_num(m.gini)}</p>'
            f"</div>"
        )
        avg_note = f"avg across {n} tests" if n > 1 else "in this run"
        kpis = (
            f'<div class="info-col"><div class="info-kpi-row">'
            f'<div class="info-kpi red"><div class="info-kpi-num">{m.zero_like_agents}</div>'
            f'<div class="info-kpi-label">agents with no likes'
            f"<span>{avg_note}</span>"
            f"</div></div>"
            f'<div class="info-kpi blue"><div class="info-kpi-num">{fmt_num(top_style[1])}</div>'
            f'<div class="info-kpi-label">likes/post · {escape(top_style_label)}</div></div>'
            f'<div class="info-kpi orange"><div class="info-kpi-num">{pct(top_share)}</div>'
            f'<div class="info-kpi-label">of the debate about {escape(top_topic)}</div></div>'
            f"</div>"
            f'<div class="info-card"><div class="info-card-label">Message style</div>'
            f'<div class="info-card-title">Impact (SSR)</div>'
            f"{_mini_style_bars(style_rows)}</div></div>"
        )
        tone_rows = "".join(
            f"<div class=\"tone-row\"><span>{escape(k)}</span><strong>{pct(v)}</strong></div>"
            for k, v in m.tone_shares.items()
        )
        tone_card = (
            f'<div class="info-col">'
            f'<div class="info-card"><div class="info-card-label">Mood</div>'
            f'<div class="info-card-title">What was the tone?</div>{tone_rows}</div>'
            f'<div class="info-card"><div class="info-card-label">Volume</div>'
            f'<div class="info-card-title">{m.post_count} posts · {m.comment_count} comments</div>'
            f'<p class="chart-sub">{runs_label(n, locale)} · up to {m.ticks_run} ticks</p>'
            f"</div></div>"
        )
    else:
        pyramid = (
            f'<div class="info-card tall">'
            f'<div class="info-card-label">Vem engagerade sig?</div>'
            f'<div class="info-card-title">Engagemanget samlades hos ett fåtal</div>'
            f'<div class="pyramid">'
            f'<div class="pyr-top">{m.top_agents}<span>Ledde</span></div>'
            f'<div class="pyr-mid">{m.mid_agents}<span>Deltog</span></div>'
            f'<div class="pyr-base">{m.zero_like_agents}<span>Scrollade förbi</span></div>'
            f"</div>"
            f'<p class="chart-sub">av {m.agent_count} simulerade medborgare · Gini {fmt_num(m.gini)}</p>'
            f"</div>"
        )
        kpis = (
            f'<div class="info-col"><div class="info-kpi-row">'
            f'<div class="info-kpi red"><div class="info-kpi-num">{m.zero_like_agents}</div>'
            f'<div class="info-kpi-label">agenter utan likes'
            f"<span>{'snitt över ' + str(n) + ' tester' if n > 1 else 'i denna körning'}</span>"
            f"</div></div>"
            f'<div class="info-kpi blue"><div class="info-kpi-num">{fmt_num(top_style[1])}</div>'
            f'<div class="info-kpi-label">likes/inlägg · {escape(top_style_label)}</div></div>'
            f'<div class="info-kpi orange"><div class="info-kpi-num">{pct(top_share)}</div>'
            f'<div class="info-kpi-label">av debatten om {escape(top_topic)}</div></div>'
            f"</div>"
            f'<div class="info-card"><div class="info-card-label">Budskapsstil</div>'
            f'<div class="info-card-title">Genomslag (SSR)</div>'
            f"{_mini_style_bars(style_rows)}</div></div>"
        )
        tone_rows = "".join(
            f"<div class=\"tone-row\"><span>{escape(k)}</span><strong>{pct(v)}</strong></div>"
            for k, v in m.tone_shares.items()
        )
        tone_card = (
            f'<div class="info-col">'
            f'<div class="info-card"><div class="info-card-label">Stämning</div>'
            f'<div class="info-card-title">Hur var tonen?</div>{tone_rows}</div>'
            f'<div class="info-card"><div class="info-card-label">Volym</div>'
            f'<div class="info-card-title">{m.post_count} inlägg · {m.comment_count} kommentarer</div>'
            f'<p class="chart-sub">{runs_label(n, locale)} · upp till {m.ticks_run} ticks</p>'
            f"</div></div>"
        )
    return pyramid + kpis + tone_card


def _mini_style_bars(styles: list[tuple[str, float]]) -> str:
    max_v = max((v for _, v in styles), default=1.0) or 1.0
    parts = []
    for label, avg in styles:
        w = max(2, round((avg / max_v) * 100)) if avg > 0 else 2
        parts.append(
            f'<div class="mini-bar"><span>{escape(label)}</span>'
            f'<i style="width:{w}%"></i><b>{fmt_num(avg)}</b></div>'
        )
    return '<div class="mini-bars">' + "".join(parts) + "</div>"


def render_agents_html(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    cards = []
    for i, actor in enumerate(metrics.aggregate.top_actors):
        warn = " ag-warn" if i == len(metrics.aggregate.top_actors) - 1 else ""
        quote = escape(str(actor.get("sample") or "")[:160])
        if locale == "en":
            role = "Opinion voice"
            likes_l = "likes/post"
            total_l = "total"
            items_l = "posts"
            empty = '<p class="sec-intro">No clear opinion leaders in the data.</p>'
        else:
            role = "Opinionsröst"
            likes_l = "likes/inlägg"
            total_l = "totalt"
            items_l = "poster"
            empty = '<p class="sec-intro">Inga tydliga opinionsledare i datan.</p>'
        cards.append(
            f'<div class="agent-card{warn}">'
            f'<div class="ag-name">{escape(str(actor["name"]))}</div>'
            f'<div class="ag-title">{role}</div>'
            f'<div class="ag-scores">'
            f'<div class="ag-score"><div class="ag-score-v">{fmt_num(actor["likes_per_item"])}</div>'
            f'<div class="ag-score-l">{likes_l}</div></div>'
            f'<div class="ag-score"><div class="ag-score-v">{actor["likes_total"]}</div>'
            f'<div class="ag-score-l">{total_l}</div></div>'
            f'<div class="ag-score"><div class="ag-score-v">{actor["items"]}</div>'
            f'<div class="ag-score-l">{items_l}</div></div></div>'
            f'{f"<div class=\"ag-quote\">“{quote}”</div>" if quote else ""}'
            f"</div>"
        )
    if not cards:
        return empty
    return '<div class="agents-grid">' + "".join(cards) + "</div>"


def render_pop_compare(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    cards = []
    for m in metrics.bundles:
        top_topic = max(m.topic_shares, key=m.topic_shares.get) if m.topic_shares else "—"
        if locale == "en":
            agents_l = f"{m.agent_count} agents"
            topic_l = "Dominant topic"
            comments_l = "Comments"
            likes_l = "Total likes"
            shares_l = "Shares"
            inj_l = "Injection likes"
        else:
            agents_l = f"{m.agent_count} agenter"
            topic_l = "Dominerande ämne"
            comments_l = "Kommentarer"
            likes_l = "Likes totalt"
            shares_l = "Delningar"
            inj_l = "Likes injicerat"
        cards.append(
            f'<div class="pop-card">'
            f'<div class="pop-head">{escape(m.label)}'
            f"<small>{agents_l}</small></div>"
            f'<div class="pop-body">'
            f'<div class="pop-row"><span class="pop-row-l">{likes_l}</span>'
            f'<span class="pop-row-v">{m.likes_total}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">{inj_l}</span>'
            f'<span class="pop-row-v">{m.injection_likes}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">Gini</span>'
            f'<span class="pop-row-v">{fmt_num(m.gini)}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">0 likes</span>'
            f'<span class="pop-row-v">{m.zero_like_agents}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">{shares_l}</span>'
            f'<span class="pop-row-v">{m.shares}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">{topic_l}</span>'
            f'<span class="pop-row-v">{escape(top_topic)}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">{comments_l}</span>'
            f'<span class="pop-row-v">{m.comment_count}</span></div>'
            f"</div></div>"
        )
    return f'<div class="pop-compare">{"".join(cards)}</div>'


def _positive_tone_share(tone: dict[str, float], *, locale: ReportLocale) -> float:
    if locale == "en":
        return tone.get("Somewhat positive", 0.0) + tone.get("Strongly positive", 0.0)
    return tone.get("Något positiv", 0.0) + tone.get("Starkt positiv", 0.0)


def _ab_bar_row(
    label: str,
    values: list[tuple[str, float | int]],
    *,
    locale: ReportLocale,
) -> str:
    nums = [float(v) for _, v in values]
    max_v = max(nums) if nums else 1.0
    if max_v <= 0:
        max_v = 1.0
    colors = (C_PRIMARY, C_ORANGE, C_GREEN, C_ROSE)
    bars = []
    for i, (arm, val) in enumerate(values):
        width = max(2, round((float(val) / max_v) * 100))
        color = colors[i % len(colors)]
        bars.append(
            f'<div class="ab-bar-line">'
            f'<span class="ab-arm">{escape(arm)}</span>'
            f'<div class="ab-track"><div class="ab-fill" style="width:{width}%;background:{color}"></div></div>'
            f'<span class="ab-val">{fmt_num(float(val)) if isinstance(val, float) else val}</span>'
            f"</div>"
        )
    return (
        f'<div class="ab-metric">'
        f'<div class="ab-metric-label">{escape(label)}</div>'
        f'<div class="ab-bars">{"".join(bars)}</div></div>'
    )


def render_quick_stats_table(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    if locale == "en":
        headers = (
            "<th>Run</th><th>Posts</th><th>Comments</th><th>Likes</th>"
            "<th>Post likes</th><th>Comment likes</th><th>Shares</th><th>Dislikes</th>"
            "<th>Inj. likes</th><th>Follows</th><th>Eng. score</th><th>Gini</th><th>0 likes</th>"
        )
    else:
        headers = (
            "<th>Körning</th><th>Inlägg</th><th>Kommentarer</th><th>Likes</th>"
            "<th>Inläggslikes</th><th>Kommentarslikes</th><th>Delningar</th><th>Dislikes</th>"
            "<th>Inj.likes</th><th>Följningar</th><th>Eng.poäng</th><th>Gini</th><th>0 likes</th>"
        )
    rows = []
    for m in metrics.bundles:
        rows.append(
            f"<tr><td>{escape(m.label)}</td>"
            f"<td>{m.post_count}</td><td>{m.comment_count}</td>"
            f"<td>{m.likes_total}</td><td>{m.post_likes}</td><td>{m.comment_likes}</td>"
            f"<td>{m.shares}</td><td>{m.dislikes}</td><td>{m.injection_likes}</td>"
            f"<td>{m.follow_edges}</td><td>{m.engagement_score}</td>"
            f"<td>{fmt_num(m.gini)}</td><td>{m.zero_like_agents}</td></tr>"
        )
    return (
        '<div class="chart-card wide">'
        f'<table class="data-table stats-table"><thead><tr>{headers}</tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def render_quick_ab_bars(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    if len(metrics.bundles) < 2:
        return ""
    arms = [(m.label, m) for m in metrics.bundles]
    if locale == "en":
        metrics_spec: list[tuple[str, str]] = [
            ("Total likes", "likes_total"),
            ("Injection likes", "injection_likes"),
            ("Posts", "post_count"),
            ("Comments", "comment_count"),
            ("Shares", "shares"),
            ("Dislikes", "dislikes"),
            ("Follow edges", "follow_edges"),
            ("Engagement score", "engagement_score"),
            ("Positive SSR tone", "_pos_tone"),
            ("Gini (inequality)", "gini"),
            ("Agents with 0 likes", "zero_like_agents"),
        ]
        title = "A/B — key metrics compared"
        sub = "Bar length is relative within each metric (longest arm = 100%)"
    else:
        metrics_spec = [
            ("Likes totalt", "likes_total"),
            ("Likes på injicerat budskap", "injection_likes"),
            ("Inlägg", "post_count"),
            ("Kommentarer", "comment_count"),
            ("Delningar", "shares"),
            ("Dislikes", "dislikes"),
            ("Följkanter", "follow_edges"),
            ("Engagemangspoäng", "engagement_score"),
            ("Positiv SSR-ton", "_pos_tone"),
            ("Gini (ojämlikhet)", "gini"),
            ("Agenter utan likes", "zero_like_agents"),
        ]
        title = "A/B — nyckeltal jämförda"
        sub = "Stapelns längd är relativ inom varje mått (längsta arm = 100 %)"
    rows = []
    for label, key in metrics_spec:
        vals: list[tuple[str, float | int]] = []
        for arm_label, m in arms:
            if key == "_pos_tone":
                vals.append((arm_label, round(_positive_tone_share(m.tone_shares, locale=locale), 3)))
            elif key == "gini":
                vals.append((arm_label, m.gini))
            else:
                vals.append((arm_label, int(getattr(m, key))))
        rows.append(_ab_bar_row(label, vals, locale=locale))
    return (
        '<div class="chart-card wide">'
        f"<h4>{title}</h4>"
        f'<div class="chart-sub">{sub}</div>'
        f'<div class="ab-compare">{"".join(rows)}</div></div>'
    )


def render_ab_tone_donuts(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    if len(metrics.bundles) < 2:
        return ""
    cards = []
    for m in metrics.bundles:
        mini = ReportMetrics(
            n_runs=1,
            bundles=[m],
            aggregate=m,
            cross_table=[],
            tone_mode=metrics.tone_mode,
        )
        cards.append(
            f'<div class="ab-tone-card"><div class="ab-tone-head">{escape(m.label)}</div>'
            f"{render_tone_donut(mini, locale=locale)}</div>"
        )
    if locale == "en":
        title = "SSR tone distribution per arm"
    else:
        title = "SSR-tonfördelning per arm"
    return (
        '<div class="chart-card wide">'
        f"<h4>{title}</h4>"
        f'<div class="ab-tone-grid">{"".join(cards)}</div></div>'
    )


def render_quick_charts(
    metrics: ReportMetrics,
    *,
    locale: ReportLocale = "sv",
    ab: bool = False,
) -> str:
    parts = [
        render_engagement_donut(metrics, locale=locale),
        render_tone_donut(metrics, locale=locale),
        render_topic_donut(metrics, locale=locale),
        render_style_hbars(metrics, locale=locale),
    ]
    if ab:
        parts.extend(
            [
                render_quick_ab_bars(metrics, locale=locale),
                render_ab_tone_donuts(metrics, locale=locale),
                render_pop_compare(metrics, locale=locale),
            ]
        )
    else:
        parts.append(render_agents_html(metrics, locale=locale))
    return f'<div class="chart-grid">{"".join(parts)}</div>'


def _tick_chart_bars(rows: list[TickStatsRow], *, locale: ReportLocale) -> str:
    if not rows:
        return ""
    max_score = max(r.cumulative_engagement_score for r in rows) or 1
    bars = []
    for row in rows:
        h = max(4, round((row.cumulative_engagement_score / max_score) * 100))
        silent = " tick-silent" if row.silent else ""
        label = f"D{row.day}" if locale == "en" else f"D{row.day}"
        bars.append(
            f'<div class="tick-bar-col{silent}" title="{escape(row.key)}">'
            f'<div class="tick-bar" style="height:{h}%"></div>'
            f'<span class="tick-bar-lbl">{label}</span></div>'
        )
    title = "Cumulative engagement score by tick" if locale == "en" else "Kumulativ engagemangspoäng per tick"
    return f'<div class="tick-spark"><div class="tick-spark-title">{title}</div><div class="tick-bars">{"".join(bars)}</div></div>'


def _tick_table_rows(rows: list[TickStatsRow], *, locale: ReportLocale) -> str:
    html_rows = []
    for row in rows:
        meas_bits = []
        for pt in row.measurement_points:
            meas_bits.append(f"{escape(str(pt.get('label') or pt.get('id') or ''))}: {escape(str(pt.get('summary') or ''))}")
        meas_cell = "<br/>".join(meas_bits) if meas_bits else "—"
        silent = " · tyst" if row.silent and locale == "sv" else (" · silent" if row.silent else "")
        tick_lbl = (
            f"Tick {row.tick_index + 1} · day {row.day}{silent}"
            if locale == "en"
            else f"Tick {row.tick_index + 1} · dag {row.day}{silent}"
        )
        html_rows.append(
            f"<tr><td>{escape(tick_lbl)}</td>"
            f"<td>{row.window_posts}</td><td>{row.window_comments}</td>"
            f"<td>{row.window_likes}</td><td>{row.window_shares}</td><td>{row.window_dislikes}</td>"
            f"<td>{row.window_engagement_score}</td>"
            f"<td>{row.cumulative_likes}</td><td>{row.cumulative_engagement_score}</td>"
            f"<td>{meas_cell}</td></tr>"
        )
    return "".join(html_rows)


def render_tick_timeline(
    bundles: list[RunBundle],
    *,
    locale: ReportLocale = "sv",
) -> str:
    if not bundles:
        return "<p>—</p>"
    sections = []
    for bundle in bundles:
        rows = build_tick_stats(bundle)
        if not rows:
            continue
        if locale == "en":
            headers = (
                "<th>Tick</th><th>Posts</th><th>Comments</th><th>Likes</th>"
                "<th>Shares</th><th>Dislikes</th><th>Tick score</th>"
                "<th>Cum. likes</th><th>Cum. score</th><th>Measurements</th>"
            )
            head = escape(bundle.label)
        else:
            headers = (
                "<th>Tick</th><th>Inlägg</th><th>Kommentarer</th><th>Likes</th>"
                "<th>Delningar</th><th>Dislikes</th><th>Tick-poäng</th>"
                "<th>Kum. likes</th><th>Kum. poäng</th><th>Mätpunkter</th>"
            )
            head = escape(bundle.label)
        sections.append(
            f'<div class="tick-bundle">'
            f'<h4>{head}</h4>'
            f"{_tick_chart_bars(rows, locale=locale)}"
            f'<table class="data-table tick-table"><thead><tr>{headers}</tr></thead>'
            f"<tbody>{_tick_table_rows(rows, locale=locale)}</tbody></table></div>"
        )
    if not sections:
        empty = "No tick data in this run." if locale == "en" else "Ingen tick-data i körningen."
        return f"<p>{empty}</p>"
    return f'<div class="tick-timeline">{"".join(sections)}</div>'


def render_interview_qa_section(
    bundles: list[RunBundle],
    *,
    locale: ReportLocale = "sv",
) -> str:
    all_qa: list[tuple[str, list[InterviewQA]]] = []
    for bundle in bundles:
        qa = extract_interview_qa(bundle)
        if qa:
            all_qa.append((bundle.label, qa))
    if not all_qa:
        empty = (
            "No planned tick interviews in this run."
            if locale == "en"
            else "Inga planerade tick-intervjuer i körningen."
        )
        return f"<p class=\"muted\">{empty}</p>"

    blocks = []
    for label, qa_list in all_qa:
        by_tick: dict[int, list[InterviewQA]] = {}
        for item in qa_list:
            by_tick.setdefault(item.tick_index, []).append(item)
        tick_sections = []
        for tick_index in sorted(by_tick):
            items = by_tick[tick_index]
            day = items[0].day
            tick_title = (
                f"After tick {tick_index + 1} · day {day}"
                if locale == "en"
                else f"Efter tick {tick_index + 1} · dag {day}"
            )
            cards = []
            for item in items:
                cards.append(
                    f'<div class="qa-card">'
                    f'<div class="qa-agent">{escape(item.agent_name)}</div>'
                    f'<div class="qa-q"><strong>{"Q" if locale == "en" else "F"}:</strong> {escape(item.question)}</div>'
                    f'<div class="qa-a"><strong>{"A" if locale == "en" else "S"}:</strong> {escape(item.answer)}</div>'
                    f"</div>"
                )
            tick_sections.append(
                f'<div class="qa-tick"><h5>{escape(tick_title)}</h5>{"".join(cards)}</div>'
            )
        blocks.append(
            f'<div class="qa-bundle"><h4>{escape(label)}</h4>{"".join(tick_sections)}</div>'
        )
    intro = (
        "Questions configured on the run timeline and answered via OASIS INTERVIEW after each tick's reaction rounds."
        if locale == "en"
        else "Frågor konfigurerade på körningens tidslinje — besvarade via OASIS INTERVIEW efter tickens reaktionsronder."
    )
    return f'<p class="chart-sub">{intro}</p><div class="qa-section">{"".join(blocks)}</div>'


def render_recommendation_block(
    rec: QuickRecommendation,
    *,
    locale: ReportLocale = "sv",
) -> str:
    if locale == "en":
        h_str, h_risk, h_imp, h_traj = "Strengths", "Risks", "Suggested improvements", "Trajectory"
    else:
        h_str, h_risk, h_imp, h_traj = "Styrkor", "Risker", "Rekommenderade förbättringar", "Utveckling"
    parts = [f'<p class="rec-headline"><strong>{escape(rec.headline)}</strong></p>']
    if rec.strengths:
        items = "".join(f"<li>{escape(s)}</li>" for s in rec.strengths)
        parts.append(f"<p class=\"rec-sub\"><strong>{h_str}:</strong></p><ul class=\"rec-list\">{items}</ul>")
    if rec.risks:
        items = "".join(f"<li>{escape(r)}</li>" for r in rec.risks)
        parts.append(f"<p class=\"rec-sub\"><strong>{h_risk}:</strong></p><ul class=\"rec-list\">{items}</ul>")
    if rec.improvements:
        items = "".join(f"<li>{escape(i)}</li>" for i in rec.improvements)
        parts.append(f"<p class=\"rec-sub\"><strong>{h_imp}:</strong></p><ul class=\"rec-list\">{items}</ul>")
    if rec.trajectory:
        parts.append(f"<p class=\"rec-traj\"><strong>{h_traj}:</strong> {escape(rec.trajectory)}</p>")
    return f'<div class="recommendation-block">{"".join(parts)}</div>'


def render_audience_section(
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    *,
    locale: ReportLocale = "sv",
) -> str:
    if not bundles:
        return "<p>—</p>"
    intro = (
        "SSR numbers come from posts and comments in the feed. "
        "Interview quotes below are planned tick interviews matched to each bio segment — "
        "ranked by thematic relevance (financing, clarity, injection keywords), not feed order."
        if locale == "en"
        else "SSR-siffror bygger på inlägg och kommentarer i flödet. "
        "Intervjucitat nedan kommer från planerade tick-intervjuer kopplade till varje bio-segment — "
        "rankade efter tematisk relevans (finansiering, tydlighet, injektionsord), inte flödesordning."
    )
    blocks: list[str] = []
    for bundle, clf in zip(bundles, classifications, strict=True):
        summaries = build_audience_summaries(bundle, clf, locale=locale)
        if not summaries:
            continue
        rows_html: list[str] = []
        for seg in summaries:
            tone = seg.tone
            if tone and not tone.too_few:
                pos = pct(tone.positive_share)
                crit = pct(tone.critical_share)
                stat = (
                    f"SSR (feed) +{pos} / −{crit} · {tone.text_count} texts · eng. {tone.engagement_score}"
                    if locale == "en"
                    else f"SSR (flöde) +{pos} / −{crit} · {tone.text_count} texter · eng. {tone.engagement_score}"
                )
            elif tone and tone.too_few:
                stat = "Too few reactions in segment" if locale == "en" else "För få reaktioner i segmentet"
            else:
                stat = "Interviews only" if locale == "en" else "Endast intervjuer"
            theme_lbl = ""
            if seg.themes:
                theme_lbl = (
                    f'<span class="aud-themes">{escape(", ".join(seg.themes))}</span>'
                )
            iv_html = ""
            if seg.interviews:
                shown = len(seg.interviews)
                total = seg.interview_total or shown
                caption = interview_section_caption(total, shown, locale=locale)
                iv_bits = [
                    f'<div class="aud-iv-caption">{escape(caption)}</div>',
                ]
                for iv in seg.interviews:
                    meta = interview_quote_label(iv, locale=locale)
                    iv_bits.append(
                        f'<div class="aud-iv">'
                        f'<div class="aud-iv-meta">{escape(meta)}</div>'
                        f'<div class="aud-iv-a">{escape(iv.answer[:220])}</div>'
                        f"</div>"
                    )
                iv_html = "".join(iv_bits)
            rows_html.append(
                f'<div class="aud-seg">'
                f'<div class="aud-seg-head">'
                f'<span class="aud-dim">{escape(seg.dimension_label)}</span> '
                f'<strong>{escape(seg.label)}</strong></div>'
                f'<div class="aud-stat">{escape(stat)}{theme_lbl}</div>{iv_html}</div>'
            )
        if rows_html:
            blocks.append(
                f'<div class="aud-bundle"><h4>{escape(bundle.label)}</h4>{"".join(rows_html)}</div>'
            )
    if not blocks:
        empty = (
            "No segment data — ensure personas have bio fields and reactions/interviews exist."
            if locale == "en"
            else "Ingen segmentdata — personas behöver bio-fält och reaktioner/intervjuer i körningen."
        )
        return f'<p class="muted">{empty}</p>'
    return f'<p class="chart-sub">{intro}</p><div class="audience-section">{"".join(blocks)}</div>'


def prefill_quick_chart_slots(
    metrics: ReportMetrics,
    bundles: list[RunBundle],
    classifications: list[BundleClassification] | None = None,
    *,
    locale: ReportLocale = "sv",
    ab: bool = False,
    recommendation: QuickRecommendation | None = None,
) -> dict[str, str]:
    clfs = classifications or []
    aud_html = (
        render_audience_section(bundles, clfs, locale=locale)
        if clfs and len(clfs) == len(bundles)
        else ""
    )
    rec_html = render_recommendation_block(recommendation, locale=locale) if recommendation else ""
    return {
        "stats_html": render_quick_stats_table(metrics, locale=locale),
        "charts_html": render_quick_charts(metrics, locale=locale, ab=ab),
        "tick_html": render_tick_timeline(bundles, locale=locale),
        "qa_html": render_interview_qa_section(bundles, locale=locale),
        "audience_html": aud_html,
        "recommendation_html": rec_html,
    }


def render_appendix_tables(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    rows = "".join(
        f"<tr><td>{escape(r['label'])}</td><td>{fmt_num(r['gini'])}</td>"
        f"<td>{r['zero_likes']}</td><td>{r['agents']}</td>"
        f"<td>{escape(str(r['top_topic']))}</td></tr>"
        for r in metrics.cross_table
    )
    if locale == "en":
        glossary = (
            '<div class="app-card"><h4>Glossary</h4>'
            '<div class="tech-def"><strong>Agent</strong> — '
            "<span>AI-simulated citizen with occupation, age, and personality.</span></div>"
            '<div class="tech-def"><strong>Gini</strong> — '
            "<span>Inequality in likes (0 = even, 1 = one person takes all).</span></div>"
            '<div class="tech-def"><strong>Message style</strong> — '
            "<span>SSR semantic similarity to style anchors, not keyword match.</span></div>"
            "</div>"
        )
        table = (
            '<div class="app-card"><h4>Comparison</h4>'
            '<table class="data-table"><thead><tr>'
            "<th>Run</th><th>Gini</th><th>0 likes</th><th>Agents</th><th>Topic</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )
        limits = (
            '<div class="app-card"><h4>Limitations</h4>'
            f'<div class="tech-def"><strong>{runs_label(metrics.n_runs, locale)}</strong> — '
            "<span>Too few for formal statistics; speak of tendencies.</span></div>"
            '<div class="tech-def"><strong>Simulated ≠ real</strong> — '
            "<span>AI agents model behavior; they are not voters.</span></div>"
            "</div>"
        )
    else:
        glossary = (
            '<div class="app-card"><h4>Ordlista</h4>'
            '<div class="tech-def"><strong>Agent</strong> — '
            "<span>AI-simulerad medborgare med yrke, ålder och personlighet.</span></div>"
            '<div class="tech-def"><strong>Gini</strong> — '
            "<span>Ojämlikhet i likes (0 = jämnt, 1 = en person tar allt).</span></div>"
            '<div class="tech-def"><strong>Budskapsstil</strong> — '
            "<span>SSR semantisk likhet mot stilankare, inte nyckelordsmatch.</span></div>"
            "</div>"
        )
        table = (
            '<div class="app-card"><h4>Jämförelse</h4>'
            '<table class="data-table"><thead><tr>'
            "<th>Körning</th><th>Gini</th><th>0 likes</th><th>Agenter</th><th>Ämne</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div>"
        )
        limits = (
            '<div class="app-card"><h4>Begränsningar</h4>'
            f'<div class="tech-def"><strong>{runs_label(metrics.n_runs, locale)}</strong> — '
            "<span>För få för formell statistik; tala om tendenser.</span></div>"
            '<div class="tech-def"><strong>Simulerat ≠ verkligt</strong> — '
            "<span>AI-agenter modellerar beteende, de är inte väljare.</span></div>"
            "</div>"
        )
    return f'<div class="app-grid">{glossary}{table}{limits}</div>'


def prefill_chart_slots(
    metrics: ReportMetrics,
    *,
    locale: ReportLocale = "sv",
) -> dict[str, str]:
    """Slots filled without LLM."""
    n = metrics.n_runs
    m = metrics.aggregate
    badge = confidence_badge(n)
    return {
        "meta_tests": runs_label(n, locale),
        "infographic_grid_html": render_infographic_grid(metrics, locale=locale),
        "sec02_charts_html": render_sec02_charts(metrics, locale=locale),
        "sec03_bars_html": render_style_hbars(metrics, locale=locale),
        "sec04_topic_race_html": render_topic_race(metrics, locale=locale),
        "sec05_agents_html": render_agents_html(metrics, locale=locale),
        "sec06_pop_html": render_pop_compare(metrics, locale=locale),
        "appendix_grid_html": render_appendix_tables(metrics, locale=locale),
        "chart_zero_likes": str(m.zero_like_agents),
        "chart_gini": fmt_num(m.gini),
        "chart_agent_count": str(m.agent_count),
        "badge_kind": badge,
        "badge_html": _badge_html(badge, n, locale),
    }
