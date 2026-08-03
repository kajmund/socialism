"""HTML chart / finding fragments from ReportMetrics (no LLM)."""

from __future__ import annotations

from html import escape

from app.services.report.metrics import ReportMetrics, confidence_badge, fmt_num, pct

# Paper-theme colors matching simulator tokens
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


def _topic_color(label: str, index: int) -> str:
    if label == "Övrigt":
        return C_MUTED
    return _TOPIC_PALETTE[index % len(_TOPIC_PALETTE)]


def _tone_subtitle(metrics: ReportMetrics) -> str:
    if metrics.tone_mode == "llm":
        return "Klassad per kommentar (LLM)"
    return "Heuristisk fallback (Neutral om ingen träff)"


def _badge_html(kind: str, n: int) -> str:
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


def render_engagement_donut(metrics: ReportMetrics) -> str:
    m = metrics.aggregate
    total = max(1, m.top_agents + m.mid_agents + m.zero_like_agents)
    shares = [
        ("Toppengagerade", m.top_agents / total, C_PRIMARY),
        ("Viss aktivitet", m.mid_agents / total, C_PRIMARY_2),
        ("Inga likes alls", m.zero_like_agents / total, C_SOFT),
    ]
    return (
        '<div class="chart-card">'
        "<h4>Engagemang i debatten</h4>"
        f'<div class="chart-sub">Av {m.agent_count} simulerade medborgare</div>'
        f"{_donut(shares, str(m.zero_like_agents))}"
        "</div>"
    )


def render_topic_donut(metrics: ReportMetrics) -> str:
    m = metrics.aggregate
    ordered = sorted(m.topic_shares.items(), key=lambda x: x[1], reverse=True)
    shares = [(k, v, _topic_color(k, i)) for i, (k, v) in enumerate(ordered)]
    top = ordered[0][0] if ordered else "—"
    return (
        '<div class="chart-card">'
        "<h4>Vad diskuterades?</h4>"
        '<div class="chart-sub">Ämnesfördelning i text (nyckelord från injektioner)</div>'
        f"{_donut(shares, top[:12])}"
        "</div>"
    )


def render_tone_donut(metrics: ReportMetrics) -> str:
    m = metrics.aggregate
    colors = {
        "Kritisk / uppgiven": C_ROSE,
        "Konstruktiv": C_GREEN,
        "Positiv / hoppfull": C_AMBER,
        "Neutral / oklassad": C_MUTED,
    }
    shares = [(k, v, colors.get(k, C_MUTED)) for k, v in m.tone_shares.items()]
    return (
        '<div class="chart-card">'
        "<h4>Debattens ton</h4>"
        f'<div class="chart-sub">{_tone_subtitle(metrics)}</div>'
        f"{_donut(shares, 'ton')}"
        "</div>"
    )


def render_sec02_charts(metrics: ReportMetrics) -> str:
    return (
        render_engagement_donut(metrics)
        + render_topic_donut(metrics)
        + render_tone_donut(metrics)
    )


def render_style_hbars(metrics: ReportMetrics) -> str:
    styles = metrics.aggregate.style_avg_likes
    max_v = max((v for _, v in styles), default=1.0) or 1.0
    palette = [C_PRIMARY, C_PRIMARY_2, C_GREEN, C_ORANGE, C_MUTED, C_ROSE]
    rows = []
    for i, (label, avg) in enumerate(styles):
        width = max(2, round((avg / max_v) * 100)) if avg > 0 else 2
        color = palette[i % len(palette)]
        zero_cls = " hb-zero" if avg <= 0 else ""
        rows.append(
            f'<div class="hbar-row">'
            f'<div class="hbar-lbl">{escape(label)}</div>'
            f'<div class="hbar-track"><div class="hbar-fill{zero_cls}" '
            f'style="width:{width}%;background:{color}">{fmt_num(avg)}</div></div>'
            f'<div class="hbar-val">{fmt_num(avg)}</div></div>'
        )
    return (
        '<div class="chart-card">'
        "<h4>Genomsnittliga likes per budskapsstil</h4>"
        '<div class="chart-sub">Nyckelordsmatch — omatchad text = Oklassad (ingen Personlig-default)</div>'
        f'<div class="hbar-chart">{"".join(rows)}</div></div>'
    )


def render_topic_race(metrics: ReportMetrics) -> str:
    shares = metrics.aggregate.topic_shares
    rows = []
    ordered = sorted(shares.items(), key=lambda x: x[1], reverse=True)
    for i, (topic, share) in enumerate(ordered):
        w = max(2, round(share * 100))
        color = _topic_color(topic, i)
        rows.append(
            f'<div class="topic-row">'
            f'<div class="t-name">{escape(topic)}'
            f'<small>andel av matchad text</small></div>'
            f'<div class="t-track"><div class="t-fill" style="width:{w}%;background:{color}">'
            f"</div></div>"
            f'<div class="t-pct">{pct(share)}</div></div>'
        )
    return f'<div class="topic-race">{"".join(rows)}</div>'


def render_infographic_grid(metrics: ReportMetrics) -> str:
    m = metrics.aggregate
    n = metrics.n_runs
    top_style = m.style_avg_likes[0] if m.style_avg_likes else ("—", 0.0)
    top_topic = max(m.topic_shares, key=m.topic_shares.get) if m.topic_shares else "—"
    top_share = m.topic_shares.get(top_topic, 0.0)

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
        f'<div class="info-kpi-label">likes/inlägg · {escape(top_style[0])}</div></div>'
        f'<div class="info-kpi orange"><div class="info-kpi-num">{pct(top_share)}</div>'
        f'<div class="info-kpi-label">av debatten om {escape(top_topic)}</div></div>'
        f"</div>"
        f'<div class="info-card"><div class="info-card-label">Budskapsstil</div>'
        f'<div class="info-card-title">Genomslag (heuristik)</div>'
        f"{_mini_style_bars(m.style_avg_likes[:5])}</div></div>"
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
        f'<p class="chart-sub">{n} körning{"ar" if n != 1 else ""} · upp till {m.ticks_run} ticks</p>'
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


def render_agents_html(metrics: ReportMetrics) -> str:
    cards = []
    for i, actor in enumerate(metrics.aggregate.top_actors):
        warn = " ag-warn" if i == len(metrics.aggregate.top_actors) - 1 else ""
        quote = escape(str(actor.get("sample") or "")[:160])
        cards.append(
            f'<div class="agent-card{warn}">'
            f'<div class="ag-name">{escape(str(actor["name"]))}</div>'
            f'<div class="ag-title">Opinionsröst</div>'
            f'<div class="ag-scores">'
            f'<div class="ag-score"><div class="ag-score-v">{fmt_num(actor["likes_per_item"])}</div>'
            f'<div class="ag-score-l">likes/inlägg</div></div>'
            f'<div class="ag-score"><div class="ag-score-v">{actor["likes_total"]}</div>'
            f'<div class="ag-score-l">totalt</div></div>'
            f'<div class="ag-score"><div class="ag-score-v">{actor["items"]}</div>'
            f'<div class="ag-score-l">poster</div></div></div>'
            f'{f"<div class=\"ag-quote\">“{quote}”</div>" if quote else ""}'
            f"</div>"
        )
    if not cards:
        return '<p class="sec-intro">Inga tydliga opinionsledare i datan.</p>'
    return '<div class="agents-grid">' + "".join(cards) + "</div>"


def render_pop_compare(metrics: ReportMetrics) -> str:
    cards = []
    for m in metrics.bundles:
        top_topic = max(m.topic_shares, key=m.topic_shares.get) if m.topic_shares else "—"
        cards.append(
            f'<div class="pop-card">'
            f'<div class="pop-head">{escape(m.label)}'
            f"<small>{m.agent_count} agenter</small></div>"
            f'<div class="pop-body">'
            f'<div class="pop-row"><span class="pop-row-l">Gini</span>'
            f'<span class="pop-row-v">{fmt_num(m.gini)}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">0 likes</span>'
            f'<span class="pop-row-v">{m.zero_like_agents}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">Dominerande ämne</span>'
            f'<span class="pop-row-v">{escape(top_topic)}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">Kommentarer</span>'
            f'<span class="pop-row-v">{m.comment_count}</span></div>'
            f"</div></div>"
        )
    return f'<div class="pop-compare">{"".join(cards)}</div>'


def render_appendix_tables(metrics: ReportMetrics) -> str:
    rows = "".join(
        f"<tr><td>{escape(r['label'])}</td><td>{fmt_num(r['gini'])}</td>"
        f"<td>{r['zero_likes']}</td><td>{r['agents']}</td>"
        f"<td>{escape(str(r['top_topic']))}</td></tr>"
        for r in metrics.cross_table
    )
    glossary = (
        '<div class="app-card"><h4>Ordlista</h4>'
        '<div class="tech-def"><strong>Agent</strong> — '
        "<span>AI-simulerad medborgare med yrke, ålder och personlighet.</span></div>"
        '<div class="tech-def"><strong>Gini</strong> — '
        "<span>Ojämlikhet i likes (0 = jämnt, 1 = en person tar allt).</span></div>"
        '<div class="tech-def"><strong>Budskapsstil</strong> — '
        "<span>Heuristik via nyckelord, inte manuell annotering.</span></div>"
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
        f'<div class="tech-def"><strong>{metrics.n_runs} körning'
        f'{"ar" if metrics.n_runs != 1 else ""}</strong> — '
        "<span>För få för formell statistik; tala om tendenser.</span></div>"
        '<div class="tech-def"><strong>Simulerat ≠ verkligt</strong> — '
        "<span>AI-agenter modellerar beteende, de är inte väljare.</span></div>"
        "</div>"
    )
    return f'<div class="app-grid">{glossary}{table}{limits}</div>'


def prefill_chart_slots(metrics: ReportMetrics) -> dict[str, str]:
    """Slots filled without LLM."""
    n = metrics.n_runs
    m = metrics.aggregate
    badge = confidence_badge(n)
    return {
        "meta_tests": f"{n} körning{'ar' if n != 1 else ''}",
        "infographic_grid_html": render_infographic_grid(metrics),
        "sec02_charts_html": render_sec02_charts(metrics),
        "sec03_bars_html": render_style_hbars(metrics),
        "sec04_topic_race_html": render_topic_race(metrics),
        "sec05_agents_html": render_agents_html(metrics),
        "sec06_pop_html": render_pop_compare(metrics),
        "appendix_grid_html": render_appendix_tables(metrics),
        "chart_zero_likes": str(m.zero_like_agents),
        "chart_gini": fmt_num(m.gini),
        "chart_agent_count": str(m.agent_count),
        "badge_kind": badge,
        "badge_html": _badge_html(badge, n),
    }
