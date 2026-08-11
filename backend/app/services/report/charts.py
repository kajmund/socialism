"""HTML chart / finding fragments from ReportMetrics (no LLM)."""

from __future__ import annotations

from html import escape

from app.services.report.bundles import RunBundle
from app.services.report.locale import (
    ReportLocale,
    display_style_label,
    other_topic_label,
)
from app.services.report.metrics import (
    ReportMetrics,
    fmt_num,
    pct,
    tone_shares_sorted,
)
from app.services.report.quick_glossary import FootnoteContext, footnote
from app.services.report.recommendation import QuickRecommendation
from app.services.report.audience_takeaway import build_audience_takeaways, short_bundle_arm_label
from app.services.report.persona_bio import build_agent_bio_by_index, persona_profile_line
from app.services.report.segment_analysis import (
    AudienceSegmentComparison,
    AudienceSegmentSummary,
    SegmentArmSummary,
    build_audience_comparisons,
    build_audience_summaries,
    interview_quote_label,
    interview_respondent_label,
    interview_section_caption,
    theme_display_label,
)
from app.services.report.segment_ssr import SegmentSample, SegmentToneRow
from app.services.report.classify import BundleClassification
from app.services.report.tick_report import (
    InterviewQA,
    TickStatsRow,
    build_tick_stats,
    extract_interview_qa,
)

# Report chart palette (Devbrains charcoal + gold, matches admin)
C_PRIMARY = "#14161b"
C_PRIMARY_2 = "#d9a93c"
C_SOFT = "#fcf1d9"
C_ORANGE = "#c96b3a"
C_GREEN = "#3f8f5f"
C_ROSE = "#c1493f"
C_AMBER = "#f3ce73"
C_MUTED = "#565c6b"
C_INK = "#1b1e26"

_TOPIC_PALETTE = (C_PRIMARY, C_ORANGE, C_PRIMARY_2, C_GREEN, C_AMBER, C_MUTED, C_ROSE)
_LIGHT_FILLS = frozenset(c.lower() for c in (C_SOFT, C_AMBER, C_PRIMARY_2))


def _on_fill_color(bg: str) -> str:
    """Dark ink on gold/light fills; white on charcoal/saturated bars."""
    return "#1b1e2a" if bg.lower() in _LIGHT_FILLS else "#ffffff"


def _topic_color(label: str, index: int, *, locale: ReportLocale = "sv") -> str:
    if label == other_topic_label(locale):
        return C_MUTED
    return _TOPIC_PALETTE[index % len(_TOPIC_PALETTE)]


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
    engaged_share = (m.top_agents + m.mid_agents) / total
    if locale == "en":
        shares = [
            ("Top engaged", m.top_agents / total, C_PRIMARY),
            ("Some activity", m.mid_agents / total, C_PRIMARY_2),
            ("No likes at all", m.zero_like_agents / total, C_SOFT),
        ]
        title = "Engagement in the debate"
        sub = (
            f"Of {m.agent_count} simulated citizens · "
            f"{m.zero_like_agents} with no likes."
        )
    else:
        shares = [
            ("Toppengagerade", m.top_agents / total, C_PRIMARY),
            ("Viss aktivitet", m.mid_agents / total, C_PRIMARY_2),
            ("Inga likes alls", m.zero_like_agents / total, C_SOFT),
        ]
        title = "Engagemang i debatten"
        sub = (
            f"Av {m.agent_count} simulerade medborgare · "
            f"{m.zero_like_agents} utan likes."
        )
    # Center = share with any likes (not zero-like count — that read as “broken” when 0).
    return (
        '<div class="chart-card">'
        f"<h4>{title}</h4>"
        f'<div class="chart-sub">{sub}</div>'
        f"{_donut(shares, pct(engaged_share))}"
        "</div>"
    )


def render_topic_donut(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    m = metrics.aggregate
    ordered = sorted(m.topic_shares.items(), key=lambda x: x[1], reverse=True)
    shares = [(k, v, _topic_color(k, i, locale=locale)) for i, (k, v) in enumerate(ordered)]
    top = ordered[0][0] if ordered else "—"
    if locale == "en":
        title = "What was discussed?"
        sub = "Keyword shares from the test messages."
    else:
        title = "Vad diskuterades?"
        sub = "Ämnesandelar utifrån testbudskapet."
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
        sub = "Tone in the most liked posts and comments."
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
        sub = "Ton i de mest gillade inläggen och kommentarerna."
        center = "ton"
    ordered_items = tone_shares_sorted(m.tone_shares)
    shares = [(k, v, colors.get(k, C_MUTED)) for k, v in ordered_items]
    return (
        '<div class="chart-card">'
        f"<h4>{title}</h4>"
        f'<div class="chart-sub">{sub}</div>'
        f"{_donut(shares, center)}"
        "</div>"
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
            f'style="width:{width}%;background:{color};color:{_on_fill_color(color)}">'
            f"{fmt_num(avg)}</div></div>"
            f'<div class="hbar-val">{fmt_num(avg)}</div></div>'
        )
    if locale == "en":
        title = "Average likes per message style"
        sub = "Which styles drew the most likes."
    else:
        title = "Genomsnittliga likes per budskapsstil"
        sub = "Vilka stilar som drog flest likes."
    return (
        '<div class="chart-card">'
        f"<h4>{title}</h4>"
        f'<div class="chart-sub">{sub}</div>'
        f'<div class="hbar-chart">{"".join(rows)}</div></div>'
    )


def render_agents_html(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    if locale == "en":
        role = "Opinion voice"
        likes_l = "likes/post"
        total_l = "total"
        items_l = "posts + comments"
        empty = '<p class="sec-intro">No clear opinion leaders in the data.</p>'
    else:
        role = "Opinionsröst"
        likes_l = "likes/inlägg"
        total_l = "totalt"
        items_l = "inlägg + komm."
        empty = '<p class="sec-intro">Inga tydliga opinionsledare i datan.</p>'
    cards = []
    for i, actor in enumerate(metrics.aggregate.top_actors):
        warn = " ag-warn" if i == len(metrics.aggregate.top_actors) - 1 else ""
        quote = escape(str(actor.get("sample") or ""))
        bio = actor.get("bio") if isinstance(actor.get("bio"), dict) else {}
        profile = persona_profile_line(bio, locale=locale) if bio else ""
        label = profile or str(actor.get("name") or "")
        cards.append(
            f'<div class="agent-card{warn}">'
            f'<div class="ag-name">{escape(label)}</div>'
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
            agents_l = f"{m.agent_count} participants"
            topic_l = "Dominant topic"
            comments_l = "Comments"
            likes_l = "Total likes"
            shares_l = "Shares"
            inj_l = "Likes on test message"
        else:
            agents_l = f"{m.agent_count} deltagare"
            topic_l = "Dominerande ämne"
            comments_l = "Kommentarer"
            likes_l = "Likes totalt"
            shares_l = "Delningar"
            inj_l = "Likes på testbudskap"
        gini_l = "Inequality" if locale == "en" else "Ojämlikhet"
        zero_l = "0 likes"
        cards.append(
            f'<div class="pop-card">'
            f'<div class="pop-head">{escape(m.label)}'
            f"<small>{agents_l}</small></div>"
            f'<div class="pop-body">'
            f'<div class="pop-row"><span class="pop-row-l">{likes_l}</span>'
            f'<span class="pop-row-v">{m.likes_total}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">{inj_l}</span>'
            f'<span class="pop-row-v">{m.injection_likes}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">'
            f'{gini_l}</span>'
            f'<span class="pop-row-v">{fmt_num(m.gini)}</span></div>'
            f'<div class="pop-row"><span class="pop-row-l">{zero_l}</span>'
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
        f'<div class="ab-metric-label">{label}</div>'
        f'<div class="ab-bars">{"".join(bars)}</div></div>'
    )


def render_quick_stats_table(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    fn_inj = footnote("likes-injection")
    fn_eng = footnote("engagement-score")
    if locale == "en":
        volume_title = "Volume"
        reach_title = "Reach & distribution"
        volume_headers = (
            "<th>Run</th><th>Posts</th><th>Comments</th>"
            "<th>Likes</th><th>Post likes</th><th>Comment likes</th>"
            "<th>Shares</th><th>Dislikes</th>"
        )
        reach_headers = (
            f"<th>Run</th><th>Test msg. likes{fn_inj}</th><th>Follows</th>"
            f"<th>Eng. score{fn_eng}</th><th>Inequality</th>"
            "<th>0 likes</th>"
        )
    else:
        volume_title = "Volym"
        reach_title = "Räckvidd & fördelning"
        volume_headers = (
            "<th>Körning</th><th>Inlägg</th><th>Kommentarer</th>"
            "<th>Likes</th><th>Inläggslikes</th><th>Kommentarslikes</th>"
            "<th>Delningar</th><th>Dislikes</th>"
        )
        reach_headers = (
            f"<th>Körning</th><th>Likes testbudskap{fn_inj}</th><th>Följningar</th>"
            f"<th>Eng.poäng{fn_eng}</th><th>Ojämlikhet</th>"
            "<th>0 likes</th>"
        )
    volume_rows: list[str] = []
    reach_rows: list[str] = []
    for m in metrics.bundles:
        label = escape(m.label)
        volume_rows.append(
            f"<tr><td>{label}</td>"
            f"<td>{m.post_count}</td><td>{m.comment_count}</td>"
            f"<td>{m.likes_total}</td><td>{m.post_likes}</td><td>{m.comment_likes}</td>"
            f"<td>{m.shares}</td><td>{m.dislikes}</td></tr>"
        )
        reach_rows.append(
            f"<tr><td>{label}</td>"
            f"<td>{m.injection_likes}</td><td>{m.follow_edges}</td>"
            f"<td>{m.engagement_score}</td>"
            f"<td>{fmt_num(m.gini)}</td><td>{m.zero_like_agents}</td></tr>"
        )
    return (
        '<div class="stats-tables">'
        '<div class="chart-card">'
        f'<div class="chart-sub">{volume_title}</div>'
        f'<table class="data-table stats-table"><thead><tr>{volume_headers}</tr></thead>'
        f"<tbody>{''.join(volume_rows)}</tbody></table></div>"
        '<div class="chart-card">'
        f'<div class="chart-sub">{reach_title}</div>'
        f'<table class="data-table stats-table"><thead><tr>{reach_headers}</tr></thead>'
        f"<tbody>{''.join(reach_rows)}</tbody></table></div>"
        "</div>"
    )


def render_quick_ab_bars(metrics: ReportMetrics, *, locale: ReportLocale = "sv") -> str:
    if len(metrics.bundles) < 2:
        return ""
    arms = [(m.label, m) for m in metrics.bundles]
    if locale == "en":
        metrics_spec: list[tuple[str, str]] = [
            ("Total likes", "likes_total"),
            ("Test message likes", "injection_likes"),
            ("Posts", "post_count"),
            ("Comments", "comment_count"),
            ("Shares", "shares"),
            ("Dislikes", "dislikes"),
            ("Follow edges", "follow_edges"),
            ("Engagement score", "engagement_score"),
            ("Positive tone", "_pos_tone"),
            ("Inequality in likes", "gini"),
            ("Participants with 0 likes", "zero_like_agents"),
        ]
        title = "A/B — key metrics compared"
        sub = (
            "Bar length is relative within each metric (longest arm = 100%)"
            f"{footnote('ab-relative')}"
        )
    else:
        metrics_spec = [
            ("Likes totalt", "likes_total"),
            ("Likes på testbudskap", "injection_likes"),
            ("Inlägg", "post_count"),
            ("Kommentarer", "comment_count"),
            ("Delningar", "shares"),
            ("Dislikes", "dislikes"),
            ("Följkanter", "follow_edges"),
            ("Engagemangspoäng", "engagement_score"),
            ("Positiv ton", "_pos_tone"),
            ("Ojämlikhet i likes", "gini"),
            ("Deltagare utan likes", "zero_like_agents"),
        ]
        title = "A/B — nyckeltal jämförda"
        sub = (
            "Stapelns längd är relativ inom varje mått (längsta arm = 100 %)"
            f"{footnote('ab-relative')}"
        )
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
        title = "Tone distribution per version"
    else:
        title = "Tonfördelning per version"
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
        label = f"Day {row.day}" if locale == "en" else f"Dag {row.day}"
        bars.append(
            f'<div class="tick-bar-col{silent}" title="{escape(row.key)}">'
            f'<div class="tick-bar" style="height:{h}%"></div>'
            f'<span class="tick-bar-lbl">{label}</span></div>'
        )
    title = "Cumulative engagement by day" if locale == "en" else "Kumulativt engagemang per dag"
    return f'<div class="tick-spark"><div class="tick-spark-title">{title}</div><div class="tick-bars">{"".join(bars)}</div></div>'


def _tick_table_rows(rows: list[TickStatsRow], *, locale: ReportLocale) -> str:
    html_rows = []
    for row in rows:
        meas_bits = []
        for pt in row.measurement_points:
            meas_bits.append(f"{escape(str(pt.get('label') or pt.get('id') or ''))}: {escape(str(pt.get('summary') or ''))}")
        meas_cell = "<br/>".join(meas_bits) if meas_bits else "—"
        silent = " · tyst dag" if row.silent and locale == "sv" else (" · silent day" if row.silent else "")
        day_lbl = (
            f"Day {row.day}{silent}"
            if locale == "en"
            else f"Dag {row.day}{silent}"
        )
        html_rows.append(
            f"<tr><td>{escape(day_lbl)}</td>"
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
                "<th>Day</th><th>Posts</th><th>Comments</th>"
                "<th>Likes</th><th>Shares</th><th>Dislikes</th>"
                "<th>Day score</th><th>Cum. likes</th>"
                "<th>Cum. score</th><th>Measurements</th>"
            )
            head = escape(bundle.label)
        else:
            headers = (
                "<th>Dag</th><th>Inlägg</th><th>Kommentarer</th>"
                "<th>Likes</th><th>Delningar</th><th>Dislikes</th>"
                "<th>Dagspoäng</th><th>Kum. likes</th>"
                "<th>Kum. poäng</th><th>Mätpunkter</th>"
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
        empty = "No day-by-day data in this run." if locale == "en" else "Ingen dag-för-dag-data i körningen."
        return f"<p>{empty}</p>"
    return f'<div class="tick-timeline">{"".join(sections)}</div>'


def _qa_card_html(
    item: InterviewQA,
    bundle: RunBundle,
    *,
    locale: ReportLocale,
    exclude_dimension: str | None = None,
) -> str:
    bio = build_agent_bio_by_index(bundle).get(item.user_id)
    profile = (
        persona_profile_line(bio, locale=locale, exclude_dimension=exclude_dimension)
        if bio
        else ""
    )
    q_lbl = "Q" if locale == "en" else "F"
    a_lbl = "A" if locale == "en" else "S"
    label = profile or item.agent_name
    return (
        f'<div class="qa-card">'
        f'<div class="qa-agent">{escape(label)}</div>'
        f'<div class="qa-q"><strong>{q_lbl}:</strong> {escape(item.question)}</div>'
        f'<div class="qa-a"><strong>{a_lbl}:</strong> {escape(item.answer)}</div>'
        f"</div>"
    )


def render_interview_qa_section(
    bundles: list[RunBundle],
    *,
    locale: ReportLocale = "sv",
) -> str:
    all_qa: list[tuple[str, RunBundle, list[InterviewQA]]] = []
    for bundle in bundles:
        qa = extract_interview_qa(bundle)
        if qa:
            all_qa.append((bundle.label, bundle, qa))
    if not all_qa:
        empty = (
            "No planned survey questions in this run."
            if locale == "en"
            else "Inga planerade enkätfrågor i körningen."
        )
        return f"<p class=\"muted\">{empty}</p>"

    blocks = []
    for label, bundle, qa_list in all_qa:
        by_tick: dict[int, list[InterviewQA]] = {}
        for item in qa_list:
            by_tick.setdefault(item.tick_index, []).append(item)
        tick_sections = []
        for tick_index in sorted(by_tick):
            items = by_tick[tick_index]
            day = items[0].day
            day_title = (
                f"After day {day}"
                if locale == "en"
                else f"Efter dag {day}"
            )
            cards = [
                _qa_card_html(item, bundle, locale=locale) for item in items
            ]
            tick_sections.append(
                f'<div class="qa-tick"><h5>{escape(day_title)}</h5>{"".join(cards)}</div>'
            )
        blocks.append(
            f'<div class="qa-bundle"><h4>{escape(label)}</h4>{"".join(tick_sections)}</div>'
        )
    intro = (
        "Planned questions after each simulation day, answered by selected participants."
        if locale == "en"
        else "Planerade frågor efter varje simuleringsdag — besvarade av utvalda deltagare."
    )
    return f'<p class="chart-sub">{intro}</p><div class="qa-section">{"".join(blocks)}</div>'


def render_recommendation_block(
    rec: QuickRecommendation,
    *,
    locale: ReportLocale = "sv",
) -> str:
    if locale == "en":
        h_rec = "Recommendation"
        h_str, h_risk = "Strengths", "Watch out"
        h_next = "Next step"
        score_lbl = "Simulated score"
        score_note = "not voter support"
        pos_lbl, likes_lbl = "Positive tone", "Likes on test message"
    else:
        h_rec = "Rekommendation"
        h_str, h_risk = "Det som fungerar", "Det som biter tillbaka"
        h_next = "Nästa steg"
        score_lbl = "Simulerat betyg"
        score_note = "inte väljarstöd"
        pos_lbl, likes_lbl = "Positiv ton", "Likes på testbudskap"

    parts = [
        '<section class="conclusion">',
        f'<p class="rec-eyebrow">{escape(h_rec)}</p>',
    ]
    if rec.recommended_arm:
        parts.append(f'<h2 class="rec-arm">{escape(rec.recommended_arm)}</h2>')
    parts.append(f'<p class="rec-action">{escape(rec.action)}</p>')
    parts.append(
        f'<p class="rec-score">{escape(score_lbl)} <strong>{rec.score}/100</strong> '
        f'<span class="rec-note">({escape(score_note)})</span></p>'
    )
    if rec.summary:
        parts.append(f'<p class="rec-summary">{escape(rec.summary)}</p>')

    if rec.ab_rows:
        head_pos = escape(pos_lbl)
        head_likes = escape(likes_lbl)
        rows = []
        for row in rec.ab_rows:
            win = ' class="rec-ab-win"' if row.is_winner else ""
            rows.append(
                f"<tr{win}><td>{escape(row.arm)}</td>"
                f"<td>{escape(row.positive)}</td>"
                f"<td>{escape(row.likes)}</td></tr>"
            )
        parts.append(
            '<table class="rec-ab-table">'
            f"<thead><tr><th></th><th>{head_pos}</th><th>{head_likes}</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    if rec.strengths or rec.risks:
        parts.append('<div class="rec-columns">')
        if rec.strengths:
            items = "".join(f"<li>{escape(s)}</li>" for s in rec.strengths)
            parts.append(
                f'<div class="rec-col"><p class="rec-sub"><strong>{h_str}</strong></p>'
                f'<ul class="rec-list">{items}</ul></div>'
            )
        if rec.risks:
            items = "".join(f"<li>{escape(r)}</li>" for r in rec.risks)
            parts.append(
                f'<div class="rec-col"><p class="rec-sub"><strong>{h_risk}</strong></p>'
                f'<ul class="rec-list">{items}</ul></div>'
            )
        parts.append("</div>")

    if rec.improvements:
        parts.append(
            f'<p class="rec-next"><strong>{h_next}:</strong> '
            f"{escape(rec.improvements[0])}</p>"
        )
    parts.append("</section>")
    return "".join(parts)


def render_audience_takeaway_section(
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    *,
    locale: ReportLocale = "sv",
) -> str:
    if not bundles or not classifications:
        return ""
    lines = build_audience_takeaways(bundles, classifications, locale=locale)
    if not lines:
        empty = (
            "Not enough segment data for a summary — add bio fields and reactions."
            if locale == "en"
            else "För lite segmentdata för en sammanfattning — personas behöver bio-fält och reaktioner."
        )
        return f'<p class="muted">{empty}</p>'
    intro = (
        "Rule-based summary from tone in posts and comments per segment (no narrative AI)."
        if locale == "en"
        else "Regelbaserad sammanfattning utifrån ton i inlägg och kommentarer per segment (ingen narrativ AI)."
    )
    body = "".join(f"<p>{escape(line)}</p>" for line in lines)
    return f'<p class="chart-sub">{intro}</p><div class="audience-takeaway">{body}</div>'


def _segment_tone_donut(tone_shares: dict[str, float], *, locale: ReportLocale) -> str:
    if not tone_shares:
        return "<p>—</p>"
    if locale == "en":
        colors = {
            "Strongly negative": C_ROSE,
            "Somewhat negative": "#C47A5A",
            "Neutral": C_MUTED,
            "Somewhat positive": C_GREEN,
            "Strongly positive": C_AMBER,
        }
        center = "tone"
        title = "Tone in this group"
    else:
        colors = {
            "Starkt negativ": C_ROSE,
            "Något negativ": "#C47A5A",
            "Neutral": C_MUTED,
            "Något positiv": C_GREEN,
            "Starkt positiv": C_AMBER,
        }
        center = "ton"
        title = "Ton i gruppen"
    ordered = tone_shares_sorted(tone_shares)
    shares = [(k, v, colors.get(k, C_MUTED)) for k, v in ordered if v > 0]
    if not shares:
        return "<p>—</p>"
    return (
        f'<div class="aud-chart-card">'
        f'<div class="aud-chart-title">{title}</div>'
        f"{_donut(shares, center)}"
        f"</div>"
    )


def _segment_engagement_bars(tone: SegmentToneRow, *, locale: ReportLocale) -> str:
    if locale == "en":
        specs = [
            ("Posts", tone.post_count),
            ("Comments", tone.comment_count),
            ("Likes", tone.likes_total),
            ("Shares", tone.shares_total),
            (f"Segment score{footnote('segment-score')}", tone.engagement_score),
        ]
        title = "Activity in this group"
    else:
        specs = [
            ("Inlägg", tone.post_count),
            ("Kommentarer", tone.comment_count),
            ("Likes", tone.likes_total),
            ("Delningar", tone.shares_total),
            (f"Segmentpoäng{footnote('segment-score')}", tone.engagement_score),
        ]
        title = "Aktivitet i gruppen"
    max_v = max((v for _, v in specs), default=1) or 1
    rows = []
    palette = (C_PRIMARY, C_PRIMARY_2, C_GREEN, C_ORANGE, C_AMBER)
    for i, (label, val) in enumerate(specs):
        width = max(2, round((val / max_v) * 100)) if val > 0 else 2
        color = palette[i % len(palette)]
        rows.append(
            f'<div class="aud-eng-row">'
            f'<span class="aud-eng-lbl">{label}</span>'
            f'<div class="aud-eng-track"><div class="aud-eng-fill" '
            f'style="width:{width}%;background:{color}"></div></div>'
            f'<span class="aud-eng-val">{val}</span></div>'
        )
    return (
        f'<div class="aud-chart-card">'
        f'<div class="aud-chart-title">{title}</div>'
        f'<div class="aud-eng-chart">{"".join(rows)}</div></div>'
    )


def _segment_theme_bars(theme_counts: dict[str, int], *, locale: ReportLocale) -> str:
    if not theme_counts:
        return ""
    title = "Themes in text" if locale == "en" else "Teman i text"
    ordered = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
    max_v = max(v for _, v in ordered) or 1
    rows = []
    for i, (key, count) in enumerate(ordered):
        label = theme_display_label(key, locale=locale)
        width = max(2, round((count / max_v) * 100))
        color = _TOPIC_PALETTE[i % len(_TOPIC_PALETTE)]
        rows.append(
            f'<div class="aud-eng-row">'
            f'<span class="aud-eng-lbl">{escape(label)}</span>'
            f'<div class="aud-eng-track"><div class="aud-eng-fill" '
            f'style="width:{width}%;background:{color}"></div></div>'
            f'<span class="aud-eng-val">{count}</span></div>'
        )
    return (
        f'<div class="aud-chart-card">'
        f'<div class="aud-chart-title">{title}</div>'
        f'<div class="aud-eng-chart">{"".join(rows)}</div></div>'
    )


_MAX_QUOTES_PER_TONE = 2
_TOP_TONE_GROUPS = 3


def _top_tone_labels(
    by_tone: dict[str, list[SegmentSample]],
    tone_shares: dict[str, float] | None,
    *,
    limit: int = _TOP_TONE_GROUPS,
) -> set[str]:
    """Pick the largest tone groups (by share, else by sample count)."""
    if not by_tone:
        return set()
    if tone_shares:
        ranked = sorted(
            by_tone.keys(),
            key=lambda lab: (float(tone_shares.get(lab) or 0.0), len(by_tone[lab])),
            reverse=True,
        )
    else:
        ranked = sorted(by_tone.keys(), key=lambda lab: len(by_tone[lab]), reverse=True)
    return set(ranked[:limit])


def _segment_sample_quotes(
    samples: list[SegmentSample],
    *,
    locale: ReportLocale,
    tone_shares: dict[str, float] | None = None,
) -> str:
    if not samples:
        return ""
    title = "Sample reactions" if locale == "en" else "Exempel från flödet"
    by_tone: dict[str, list[SegmentSample]] = {}
    for sample in samples:
        label = sample.tone_label or ("Unclassified" if locale == "en" else "Oklassad")
        by_tone.setdefault(label, []).append(sample)

    keep = _top_tone_labels(by_tone, tone_shares)
    by_tone = {lab: items for lab, items in by_tone.items() if lab in keep}

    if tone_shares:
        ordered = [
            lab
            for lab, _share in tone_shares_sorted(
                {lab: float(tone_shares.get(lab) or 0.0) for lab in by_tone}
            )
        ]
    else:
        ordered = sorted(by_tone.keys(), key=lambda lab: (-len(by_tone[lab]), lab))

    groups: list[str] = []
    for tone_lab in ordered:
        items = by_tone[tone_lab][:_MAX_QUOTES_PER_TONE]
        share = float((tone_shares or {}).get(tone_lab) or 0.0)
        heading = f"{tone_lab} ({pct(share)})" if tone_shares else tone_lab
        quotes: list[str] = []
        for item in items:
            body = escape(str(item.text))
            meta = item.profile_line or item.agent_name
            meta_html = (
                f'<div class="aud-quote-meta">{escape(meta)}</div>' if meta else ""
            )
            quotes.append(
                f'<blockquote class="aud-quote">{meta_html}'
                f'<div class="aud-quote-text">{body}</div></blockquote>'
            )
        groups.append(
            f'<div class="aud-tone-group">'
            f'<div class="aud-tone-label">{escape(heading)}</div>'
            f'{"".join(quotes)}</div>'
        )
    return (
        f'<div class="aud-samples">'
        f'<div class="aud-chart-title">{title}</div>{"".join(groups)}</div>'
    )


def _segment_kpi_html(tone: SegmentToneRow | None, *, locale: ReportLocale) -> str:
    if not tone:
        return ""
    if locale == "en":
        return (
            f'<div class="aud-kpi-row">'
            f'<div class="aud-kpi"><strong>{tone.agent_count}</strong>'
            f"<span>participants</span></div>"
            f'<div class="aud-kpi"><strong>{tone.text_count}</strong>'
            f"<span>rated texts</span></div>"
            f'<div class="aud-kpi"><strong>{pct(tone.positive_share)}</strong>'
            f"<span>positive</span></div>"
            f'<div class="aud-kpi"><strong>{pct(tone.critical_share)}</strong>'
            f"<span>critical</span></div>"
            f"</div>"
        )
    return (
        f'<div class="aud-kpi-row">'
        f'<div class="aud-kpi"><strong>{tone.agent_count}</strong>'
        f"<span>deltagare</span></div>"
        f'<div class="aud-kpi"><strong>{tone.text_count}</strong>'
        f"<span>analyserade texter</span></div>"
        f'<div class="aud-kpi"><strong>{pct(tone.positive_share)}</strong>'
        f"<span>positiv ton</span></div>"
        f'<div class="aud-kpi"><strong>{pct(tone.critical_share)}</strong>'
        f"<span>kritisk ton</span></div>"
        f"</div>"
    )


def _segment_charts_html(seg: AudienceSegmentSummary, *, locale: ReportLocale) -> str:
    tone = seg.tone
    charts: list[str] = []
    if tone and tone.tone_shares and not tone.too_few:
        charts.append(_segment_tone_donut(tone.tone_shares, locale=locale))
    if tone:
        charts.append(_segment_engagement_bars(tone, locale=locale))
    theme_chart = _segment_theme_bars(seg.theme_counts, locale=locale)
    if theme_chart:
        charts.append(theme_chart)
    if not charts:
        return ""
    return f'<div class="aud-chart-grid">{"".join(charts)}</div>'


def _segment_interviews_html(seg: AudienceSegmentSummary, *, locale: ReportLocale) -> str:
    if not seg.interviews and not seg.interview_total:
        return ""
    shown = len(seg.interviews)
    total = seg.interview_total or shown
    caption = interview_section_caption(total, shown, locale=locale)
    cards = []
    for iv in seg.interviews:
        meta = interview_respondent_label(iv, locale=locale)
        q_lbl = "Q" if locale == "en" else "F"
        a_lbl = "A" if locale == "en" else "S"
        cards.append(
            f'<div class="aud-qa-card">'
            f'<div class="aud-qa-meta">{escape(meta)}</div>'
            f'<div class="aud-qa-q"><strong>{q_lbl}:</strong> {escape(iv.question)}</div>'
            f'<div class="aud-qa-a"><strong>{a_lbl}:</strong> {escape(iv.answer)}</div>'
            f"</div>"
        )
    return (
        f'<div class="aud-qa-block">'
        f'<div class="aud-chart-title">{escape(caption)}</div>'
        f'{"".join(cards)}</div>'
    )


def _render_segment_body(seg: AudienceSegmentSummary, *, locale: ReportLocale) -> str:
    tone = seg.tone
    samples = _segment_sample_quotes(
        tone.sample_items if tone else [],
        locale=locale,
        tone_shares=tone.tone_shares if tone else None,
    )
    return (
        f'<p class="aud-narrative">{escape(seg.narrative)}</p>'
        f"{_segment_kpi_html(tone, locale=locale)}"
        f"{_segment_charts_html(seg, locale=locale)}"
        f"{samples}"
        f"{_segment_interviews_html(seg, locale=locale)}"
    )


def _render_segment_arm_panel(arm: SegmentArmSummary, *, locale: ReportLocale) -> str:
    seg = arm.summary
    if not seg or not (
        seg.interviews
        or seg.interview_total
        or (seg.tone and (not seg.tone.too_few or seg.tone.agent_count))
    ):
        empty = (
            "No data for this version in the segment."
            if locale == "en"
            else "Ingen data för denna version i segmentet."
        )
        return (
            f'<div class="aud-arm-panel aud-arm-empty">'
            f'<div class="aud-arm-head">{escape(arm.arm_label)}</div>'
            f'<p class="muted">{empty}</p></div>'
        )
    return (
        f'<div class="aud-arm-panel">'
        f'<div class="aud-arm-head">{escape(arm.arm_label)}</div>'
        f"{_render_segment_body(seg, locale=locale)}"
        f"</div>"
    )


def _render_segment_comparison(comp: AudienceSegmentComparison, *, locale: ReportLocale) -> str:
    panels = "".join(_render_segment_arm_panel(arm, locale=locale) for arm in comp.arms)
    return (
        f'<article class="aud-report aud-compare">'
        f'<header class="aud-report-head">'
        f'<span class="aud-dim">{escape(comp.dimension_label)}</span> '
        f'<h4>{escape(comp.label)}</h4>'
        f"</header>"
        f'<p class="aud-ab-diff">{escape(comp.diff_summary)}</p>'
        f'<div class="aud-arm-grid">{panels}</div>'
        f"</article>"
    )


def _render_ab_legend(bundles: list[RunBundle], *, locale: ReportLocale) -> str:
    chips = []
    for bundle in bundles:
        arm = short_bundle_arm_label(bundle)
        hint = ""
        if bundle.injection_texts:
            snippet = str(bundle.injection_texts[0]).strip()
            if len(snippet) > 120:
                snippet = snippet[:117] + "…"
            hint = f' title="{escape(snippet)}"'
        chips.append(f'<span class="aud-ab-chip"{hint}>{escape(arm)}</span>')
    if locale == "en":
        label = "Compared versions"
    else:
        label = "Jämförda versioner"
    return f'<div class="aud-ab-legend"><span class="aud-ab-legend-lbl">{label}:</span>{"".join(chips)}</div>'


def _render_audience_single_version(
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    *,
    locale: ReportLocale,
) -> str:
    blocks: list[str] = []
    for bundle, clf in zip(bundles, classifications, strict=True):
        summaries = build_audience_summaries(bundle, clf, locale=locale)
        if not summaries:
            continue
        reports = "".join(_render_segment_report(seg, locale=locale) for seg in summaries)
        blocks.append(
            f'<div class="aud-bundle">'
            f'<h3 class="aud-bundle-title">{escape(bundle.label)}</h3>'
            f'<div class="aud-reports">{reports}</div></div>'
        )
    return "".join(blocks)


def _render_audience_ab_comparison(
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    *,
    locale: ReportLocale,
) -> str:
    comparisons = build_audience_comparisons(bundles, classifications, locale=locale)
    if not comparisons:
        return ""
    reports = "".join(_render_segment_comparison(comp, locale=locale) for comp in comparisons)
    return f'{_render_ab_legend(bundles, locale=locale)}<div class="aud-reports">{reports}</div>'


def _render_segment_report(seg: AudienceSegmentSummary, *, locale: ReportLocale) -> str:
    return (
        f'<article class="aud-report">'
        f'<header class="aud-report-head">'
        f'<span class="aud-dim">{escape(seg.dimension_label)}</span> '
        f'<h4>{escape(seg.label)}</h4>'
        f"</header>"
        f"{_render_segment_body(seg, locale=locale)}"
        f"</article>"
    )


def render_audience_section(
    bundles: list[RunBundle],
    classifications: list[BundleClassification],
    *,
    locale: ReportLocale = "sv",
) -> str:
    if not bundles:
        return "<p>—</p>"
    ab = len(bundles) > 1
    if ab:
        intro = (
            "Each card compares the same target group across versions — tone, activity, "
            "themes, and survey Q&A side by side (rule-based, no narrative AI)."
            if locale == "en"
            else "Varje kort jämför samma målgrupp mellan versionerna — ton, aktivitet, "
            "teman och enkätfrågor med svar sida vid sida (regelbaserat, ingen narrativ AI)."
        )
        body = _render_audience_ab_comparison(bundles, classifications, locale=locale)
    else:
        intro = (
            "Each card is a mini-report for one target group: tone, activity, themes, "
            "sample reactions from the feed, and survey Q&A (rule-based, no narrative AI)."
            if locale == "en"
            else "Varje kort är en egen mini-rapport per målgrupp: ton, aktivitet, teman, "
            "exempel från flödet och enkätfrågor med svar (regelbaserat, ingen narrativ AI)."
        )
        body = _render_audience_single_version(bundles, classifications, locale=locale)
    if not body:
        empty = (
            "No segment data — ensure personas have bio fields and reactions/interviews exist."
            if locale == "en"
            else "Ingen segmentdata — personas behöver bio-fält och reaktioner/intervjuer i körningen."
        )
        return f'<p class="muted">{empty}</p>'
    return f'<p class="chart-sub">{intro}</p><div class="audience-section">{body}</div>'


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
    rec_html = render_recommendation_block(recommendation, locale=locale) if recommendation else ""

    with FootnoteContext(locale) as stats_tracker:
        stats_html = render_quick_stats_table(metrics, locale=locale)
        stats_html += stats_tracker.render_block()

    if ab:
        with FootnoteContext(locale) as charts_tracker:
            charts_html = render_quick_charts(metrics, locale=locale, ab=ab)
            charts_html += charts_tracker.render_block()
    else:
        charts_html = render_quick_charts(metrics, locale=locale, ab=ab)

    tick_html = render_tick_timeline(bundles, locale=locale)

    qa_html = render_interview_qa_section(bundles, locale=locale)
    takeaway_html = (
        render_audience_takeaway_section(bundles, clfs, locale=locale)
        if clfs and len(clfs) == len(bundles)
        else ""
    )
    if clfs and len(clfs) == len(bundles):
        with FootnoteContext(locale) as aud_tracker:
            aud_html = render_audience_section(bundles, clfs, locale=locale)
            aud_html += aud_tracker.render_block()
    else:
        aud_html = ""

    return {
        "stats_html": stats_html,
        "charts_html": charts_html,
        "tick_html": tick_html,
        "qa_html": qa_html,
        "audience_html": aud_html,
        "takeaway_html": takeaway_html,
        "recommendation_html": rec_html,
    }
