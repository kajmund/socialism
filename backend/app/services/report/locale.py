"""Report locale: asset selection + Swedish/English copy for generation."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from app.services.report.bundles import RunBundle, is_ab_comparison
from app.services.report.render import ASSETS_DIR
from app.services.ssr.anchors import TONE_LABELS_EN, TONE_LABELS_SV

ReportLocale = Literal["sv", "en"]

DEFAULT_LOCALE: ReportLocale = "sv"


def normalize_locale(value: str | None) -> ReportLocale:
    if value == "en":
        return "en"
    return "sv"


def template_path(locale: ReportLocale) -> Path:
    if locale == "en":
        return ASSETS_DIR / "report_template.en.html"
    return ASSETS_DIR / "report_template.html"


def questions_path(locale: ReportLocale) -> Path:
    if locale == "en":
        return ASSETS_DIR / "questions.en.json"
    return ASSETS_DIR / "questions.json"


def download_filename(locale: ReportLocale) -> str:
    return "report.html" if locale == "en" else "rapport.html"


def default_report_title(
    *,
    locale: ReportLocale,
    ab_source: bool,
    source_label: str,
    n_sources: int,
) -> str:
    if locale == "en":
        if ab_source:
            return f"A/B report — {source_label}"
        unit = "run" if n_sources == 1 else "runs"
        return f"Report ({n_sources} {unit})"
    if ab_source:
        return f"A/B-rapport — {source_label}"
    return f"Rapport ({n_sources} körning{'ar' if n_sources != 1 else ''})"


def runs_label(n: int, locale: ReportLocale) -> str:
    if locale == "en":
        return f"{n} run" if n == 1 else f"{n} runs"
    return f"{n} körning" if n == 1 else f"{n} körningar"


def ab_meta_tests(locale: ReportLocale) -> str:
    return "A/B · 2 arms" if locale == "en" else "A/B · 2 armar"


def other_topic_label(locale: ReportLocale) -> str:
    return "Other" if locale == "en" else "Övrigt"


def tone_labels(locale: ReportLocale) -> tuple[str, ...]:
    """Five-level SSR tone scale (Semantic Similarity Rating)."""
    return TONE_LABELS_EN if locale == "en" else TONE_LABELS_SV


def meta_topics_fallback(locale: ReportLocale) -> str:
    if locale == "en":
        return "See topic breakdown in the report"
    return "Se ämnesfördelning i rapporten"


# Internal style keys stay Swedish (SSR anchor labels); display may be English.
_STYLE_LABEL_EN: dict[str, str] = {
    "Sarkastisk + konkret kritik": "Sarcastic + concrete criticism",
    "Uppgiven + vardagsmetafor": "Resigned + everyday metaphor",
    "Fakta + yrkesauktoritet": "Facts + professional authority",
    "Personlig + hjärtlig berättelse": "Personal + warm story",
    "Optimistisk / lösningsfokuserad": "Optimistic / solution-focused",
    "Provocerande / konfronterande": "Provocative / confrontational",
    "Oklassad": "Unclassified",
}


def display_style_label(label: str, locale: ReportLocale) -> str:
    if locale == "en":
        return _STYLE_LABEL_EN.get(label, label)
    return label


def narrative_defaults(
    metrics_slots: dict[str, str],
    bundles: list[RunBundle],
    locale: ReportLocale,
) -> dict[str, str]:
    if locale == "en":
        return _narrative_defaults_en(metrics_slots, bundles)
    return _narrative_defaults_sv(metrics_slots, bundles)


def _narrative_defaults_sv(
    metrics_slots: dict[str, str],
    bundles: list[RunBundle],
) -> dict[str, str]:
    n = len(bundles)
    labels = ", ".join(b.label for b in bundles)
    ab = is_ab_comparison(bundles)
    compare_intro = (
        "Jämförelse mellan Version A och Version B i samma A/B-test."
        if ab
        else (
            "En enda körning — ingen populationsjämförelse."
            if n == 1
            else f"Jämförelse mellan {n} körningar."
        )
    )
    compare_findings = (
        '<div class="fc neu"><h3>A vs B</h3>'
        "<p>Se jämförelsekorten för skillnader i Gini, ämne och engagemang mellan armarna.</p></div>"
        '<div class="fc cau"><h3>Osäkerhet</h3>'
        "<p>En A/B-körning — tolka skillnader som observation, inte bevis.</p></div>"
        if ab
        else (
            '<div class="fc neu"><h3>Observation</h3>'
            "<p>Se jämförelsekorten för skillnader i Gini och ämne.</p></div>"
            '<div class="fc cau"><h3>Osäkerhet</h3>'
            "<p>Få körningar — tolka skillnader försiktigt.</p></div>"
        )
    )
    return {
        "page_title": (
            f"A/B-rapport — {bundles[0].run_name}" if ab else f"Simuleringsrapport — {labels}"
        ),
        "cover_eyebrow": (
            "Pilottest — A/B meddelandeanalys" if ab else "Pilottest — Meddelandeanalys"
        ),
        "cover_h1": (
            "Vilken budskapsversion fick starkast gensvar?"
            if ab
            else "Hur tas politiska budskap emot av vanliga invånare?"
        ),
        "cover_sub": (
            f"Vi jämförde Version A och Version B i samma simulering "
            f"({metrics_slots.get('chart_agent_count', '?')} medborgare per arm)."
            if ab
            else (
                f"Vi analyserade hur budskap spreds och mottogs i "
                f"{n} simulerad{'e' if n != 1 else ''} körning{'ar' if n != 1 else ''}."
            )
        ),
        "cover_box1_lbl": "Viktigaste insikt",
        "cover_box1_html": (
            f"Engagemanget koncentrerades — "
            f"<strong>{metrics_slots.get('chart_zero_likes', '?')} agenter</strong> "
            "fick inga likes."
        ),
        "cover_box2_lbl": "Vad fungerade",
        "cover_box2_html": (
            "Jämför budskapsstil och likes mellan Version A och B i diagrammen."
            if ab
            else "Se budskapsstil-sektionen för ranking efter likes."
        ),
        "cover_box3_lbl": "Vad vi testade",
        "cover_box3_html": (
            f"<strong>A/B</strong> · {metrics_slots.get('chart_agent_count', '?')} medborgare"
            if ab
            else (
                f"<strong>{n}</strong> körning{'ar' if n != 1 else ''} · "
                f"{metrics_slots.get('chart_agent_count', '?')} medborgare"
            )
        ),
        "meta_scenario": bundles[0].run_name if bundles else "Simulering",
        "meta_topics": meta_topics_fallback("sv"),
        "infographic_eyebrow": (
            "Sammanfattning — A/B-test"
            if ab
            else f"Sammanfattning — {n} test{'er' if n != 1 else ''}"
        ),
        "infographic_h2": "Vad visade testerna?",
        "infographic_lead": (
            "Skillnader mellan Version A och Version B i engagemang och ämnesfokus."
            if ab
            else (
                "Ett tydligt mönster i engagemang och ämnesfokus."
                if n == 1
                else f"Jämförelse mellan {n} körningar."
            )
        ),
        "info_conc_1_html": "<strong>Engagemang koncentrerat</strong> — få röster bar majoriteten av likes.",
        "info_conc_2_html": "<strong>Ton och ämne</strong> — ton via SSR; ämne via LLM.",
        "info_conc_3_html": "<strong>Begränsning</strong> — för få körningar för formell statistik.",
        "sec01_intro": (
            "Vi använde ett simuleringsverktyg där AI-agenter debatterar som vanliga medborgare "
            "på sociala medier. Varje agent har yrke, ålder och personlighet."
        ),
        "method_steps_html": (
            '<div class="mstep"><div class="mstep-num">1</div><h4>Medborgare</h4>'
            "<p>Populationen speglas som AI-agenter.</p></div>"
            '<div class="mstep"><div class="mstep-num">2</div><h4>Budskap</h4>'
            "<p>Parti- och nyhetsinlägg injiceras i flödet.</p></div>"
            '<div class="mstep"><div class="mstep-num">3</div><h4>Debatt</h4>'
            "<p>Agenter gillar, kommenterar och ignorerar.</p></div>"
            '<div class="mstep"><div class="mstep-num">4</div><h4>Analys</h4>'
            "<p>Vi mäter engagemang, ton och ämnesdrift.</p></div>"
            '<div class="mstep"><div class="mstep-num">5</div><h4>Jämförelse</h4>'
            f"<p>{'A/B: Version A mot Version B' if ab else ('En körning' if n == 1 else str(n) + ' körningar')} "
            "i denna rapport.</p></div>"
        ),
        "method_explainer_html": (
            "<strong>Varför simulering?</strong> Att testa budskap på riktiga väljare är dyrt. "
            "Resultaten visar tendenser, inte garantier."
        ),
        "sec02_intro": "Engagemanget fördelades ojämnt — en liten grupp bar debatten.",
        "sec02_findings_html": (
            f'<div class="fc neu">{metrics_slots.get("badge_html", "")}'
            f"<div class=\"fc-num\">{metrics_slots.get('chart_zero_likes', '—')}</div>"
            "<h3>Agenter utan likes</h3>"
            "<p>Majoriteten fick litet eller inget engagemang.</p></div>"
            f'<div class="fc cau">{metrics_slots.get("badge_html", "")}'
            f"<div class=\"fc-num\">{metrics_slots.get('chart_gini', '—')}</div>"
            "<h3>Gini för likes</h3>"
            "<p>Högre värde betyder starkare koncentration.</p></div>"
        ),
        "sec03_intro": (
            "Vi bedömde kommunikationsstil semantiskt (SSR) och jämförde snittlikes."
        ),
        "sec03_findings_html": (
            '<div class="fc pos"><h3>Konkret kritik</h3>'
            "<p>Texter med siffror och skarp iakttagelse tenderar att få mer stöd.</p></div>"
            '<div class="fc neu"><h3>Provokation</h3>'
            "<p>Kontrollera stilranking — provocerande språk får ofta lågt engagemang.</p></div>"
        ),
        "sec04_h2": "Ämnesfokus i debatten",
        "sec04_intro": "Ämnesandelar bygger på LLM-klassning av inlägg och kommentarer.",
        "sec04_explainer_html": (
            "<strong>Vad betyder detta?</strong> Om ett sidospår dominerar kan huvudbudskapet "
            "behöva göras mer konkret och personligt."
        ),
        "sec05_intro": "Några röster samlade mer likes än övriga.",
        "sec06_intro": compare_intro,
        "sec06_findings_html": compare_findings,
    }


def _narrative_defaults_en(
    metrics_slots: dict[str, str],
    bundles: list[RunBundle],
) -> dict[str, str]:
    n = len(bundles)
    labels = ", ".join(b.label for b in bundles)
    ab = is_ab_comparison(bundles)
    compare_intro = (
        "Comparison of Version A and Version B in the same A/B test."
        if ab
        else (
            "A single run — no population comparison."
            if n == 1
            else f"Comparison across {n} runs."
        )
    )
    compare_findings = (
        '<div class="fc neu"><h3>A vs B</h3>'
        "<p>See the comparison cards for differences in Gini, topic, and engagement across arms.</p></div>"
        '<div class="fc cau"><h3>Uncertainty</h3>'
        "<p>One A/B run — treat differences as observation, not proof.</p></div>"
        if ab
        else (
            '<div class="fc neu"><h3>Observation</h3>'
            "<p>See the comparison cards for differences in Gini and topic.</p></div>"
            '<div class="fc cau"><h3>Uncertainty</h3>'
            "<p>Few runs — interpret differences cautiously.</p></div>"
        )
    )
    return {
        "page_title": (
            f"A/B report — {bundles[0].run_name}" if ab else f"Simulation report — {labels}"
        ),
        "cover_eyebrow": (
            "Pilot — A/B message analysis" if ab else "Pilot — Message analysis"
        ),
        "cover_h1": (
            "Which message version got the strongest response?"
            if ab
            else "How do ordinary residents receive political messages?"
        ),
        "cover_sub": (
            f"We compared Version A and Version B in the same simulation "
            f"({metrics_slots.get('chart_agent_count', '?')} citizens per arm)."
            if ab
            else (
                f"We analyzed how messages spread and were received across "
                f"{n} simulated run{'s' if n != 1 else ''}."
            )
        ),
        "cover_box1_lbl": "Key insight",
        "cover_box1_html": (
            f"Engagement was concentrated — "
            f"<strong>{metrics_slots.get('chart_zero_likes', '?')} agents</strong> "
            "received no likes."
        ),
        "cover_box2_lbl": "What worked",
        "cover_box2_html": (
            "Compare message style and likes between Version A and B in the charts."
            if ab
            else "See the message-style section for ranking by likes."
        ),
        "cover_box3_lbl": "What we tested",
        "cover_box3_html": (
            f"<strong>A/B</strong> · {metrics_slots.get('chart_agent_count', '?')} citizens"
            if ab
            else (
                f"<strong>{n}</strong> run{'s' if n != 1 else ''} · "
                f"{metrics_slots.get('chart_agent_count', '?')} citizens"
            )
        ),
        "meta_scenario": bundles[0].run_name if bundles else "Simulation",
        "meta_topics": meta_topics_fallback("en"),
        "infographic_eyebrow": (
            "Summary — A/B test"
            if ab
            else f"Summary — {n} test{'s' if n != 1 else ''}"
        ),
        "infographic_h2": "What did the tests show?",
        "infographic_lead": (
            "Differences between Version A and Version B in engagement and topic focus."
            if ab
            else (
                "A clear pattern in engagement and topic focus."
                if n == 1
                else f"Comparison across {n} runs."
            )
        ),
        "info_conc_1_html": "<strong>Concentrated engagement</strong> — a few voices carried most likes.",
        "info_conc_2_html": "<strong>Tone and topic</strong> — tone via SSR; topic via LLM.",
        "info_conc_3_html": "<strong>Limitation</strong> — too few runs for formal statistics.",
        "sec01_intro": (
            "We used a simulation tool where AI agents debate like ordinary citizens "
            "on social media. Each agent has an occupation, age, and personality."
        ),
        "method_steps_html": (
            '<div class="mstep"><div class="mstep-num">1</div><h4>Citizens</h4>'
            "<p>The population is mirrored as AI agents.</p></div>"
            '<div class="mstep"><div class="mstep-num">2</div><h4>Messages</h4>'
            "<p>Party and news posts are injected into the feed.</p></div>"
            '<div class="mstep"><div class="mstep-num">3</div><h4>Debate</h4>'
            "<p>Agents like, comment, and ignore.</p></div>"
            '<div class="mstep"><div class="mstep-num">4</div><h4>Analysis</h4>'
            "<p>We measure engagement, tone, and topic drift.</p></div>"
            '<div class="mstep"><div class="mstep-num">5</div><h4>Comparison</h4>'
            f"<p>{'A/B: Version A vs Version B' if ab else ('One run' if n == 1 else str(n) + ' runs')} "
            "in this report.</p></div>"
        ),
        "method_explainer_html": (
            "<strong>Why simulate?</strong> Testing messages on real voters is expensive. "
            "Results show tendencies, not guarantees."
        ),
        "sec02_intro": "Engagement was uneven — a small group carried the debate.",
        "sec02_findings_html": (
            f'<div class="fc neu">{metrics_slots.get("badge_html", "")}'
            f"<div class=\"fc-num\">{metrics_slots.get('chart_zero_likes', '—')}</div>"
            "<h3>Agents with no likes</h3>"
            "<p>Most received little or no engagement.</p></div>"
            f'<div class="fc cau">{metrics_slots.get("badge_html", "")}'
            f"<div class=\"fc-num\">{metrics_slots.get('chart_gini', '—')}</div>"
            "<h3>Gini for likes</h3>"
            "<p>Higher values mean stronger concentration.</p></div>"
        ),
        "sec03_intro": (
            "We scored communication style semantically (SSR) and compared average likes."
        ),
        "sec03_findings_html": (
            '<div class="fc pos"><h3>Concrete criticism</h3>'
            "<p>Texts with numbers and sharp observation tend to get more support.</p></div>"
            '<div class="fc neu"><h3>Provocation</h3>'
            "<p>Check the style ranking — provocative language often gets low engagement.</p></div>"
        ),
        "sec04_h2": "Topic focus in the debate",
        "sec04_intro": "Topic shares are based on LLM classification of posts and comments.",
        "sec04_explainer_html": (
            "<strong>What does this mean?</strong> If a side track dominates, the main message "
            "may need to become more concrete and personal."
        ),
        "sec05_intro": "A few voices gathered more likes than the rest.",
        "sec06_intro": compare_intro,
        "sec06_findings_html": compare_findings,
    }


def narrative_system_prompt(
    *,
    multi: bool,
    locale: ReportLocale,
    prompts: dict[str, str],
) -> str:
    from app.services.prompt_catalog import render_prompt

    key = "report.narrative.system_meta" if multi else "report.narrative.system_single"
    return render_prompt(prompts, key)
