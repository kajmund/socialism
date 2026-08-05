"""Batched narrative slot filling for HTML reports (structured LLM, no per-slot agent)."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from app.llm import complete_structured
from app.services.report.bundles import is_ab_comparison
from app.services.report.locale import ReportLocale, narrative_system_prompt
from app.services.report.tools import ReportToolBundle

logger = logging.getLogger(__name__)

# Kept for tests / callers that import historical names.
SYSTEM_META = narrative_system_prompt(multi=True, locale="sv")
SYSTEM_SINGLE = narrative_system_prompt(multi=False, locale="sv")

# Section batches: ~6 LLM calls instead of one agent loop per slot.
NARRATIVE_BATCHES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "cover",
        (
            "page_title",
            "cover_eyebrow",
            "cover_h1",
            "cover_sub",
            "cover_box1_lbl",
            "cover_box1_html",
            "cover_box2_lbl",
            "cover_box2_html",
            "cover_box3_lbl",
            "cover_box3_html",
            "meta_scenario",
        ),
    ),
    (
        "infographic",
        (
            "infographic_eyebrow",
            "infographic_h2",
            "infographic_lead",
            "info_conc_1_html",
            "info_conc_2_html",
            "info_conc_3_html",
        ),
    ),
    (
        "method",
        (
            "sec01_intro",
            "method_steps_html",
            "method_explainer_html",
        ),
    ),
    (
        "reception_style",
        (
            "sec02_intro",
            "sec02_findings_html",
            "sec03_intro",
            "sec03_findings_html",
        ),
    ),
    (
        "topics",
        (
            "sec04_h2",
            "sec04_intro",
            "sec04_explainer_html",
        ),
    ),
    (
        "leaders_compare",
        (
            "sec05_intro",
            "sec06_intro",
            "sec06_findings_html",
        ),
    ),
)


class SlotBatchResponse(BaseModel):
    """Map slot name -> raw content for one narrative batch."""

    slots: dict[str, str] = Field(default_factory=dict)


def metrics_digest(tools: ReportToolBundle, *, locale: ReportLocale = "sv") -> str:
    data = tools.describe_runs()
    extras = {
        "opinion_leaders": tools.opinion_leaders(limit=4),
        "sample_comments": tools.sample_comments(limit=12),
        "topics": tools.compare_topics(),
        "tone": tools.compare_tone(),
        "engagement": tools.compare_engagement(),
    }
    ab = is_ab_comparison(tools.bundles)
    if locale == "en":
        ab_block = ""
        if ab:
            ab_block = (
                "\n\n### A/B TEST\n"
                "This is Version A vs Version B from the same run. "
                "Compare the arms side by side. Do not invent a single merged debate.\n"
            )
        return (
            "### REQUIRED FACTS (do not change these numbers):\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
            + "\n\n### SUPPORTING DATA (quotes and distributions):\n"
            + json.dumps(extras, ensure_ascii=False, indent=2, default=str)
            + ab_block
            + "\n\n### Response format\n"
            "- Return JSON with key slots: {slot_name: content}.\n"
            "- Fill ALL requested slots. Empty string only if impossible.\n"
            "- No preamble or reasoning outside slot values.\n"
            "- No markdown code fences.\n"
            "- Never markdown ** — use <strong> only in HTML slots.\n"
            "- Heading/title slots: short headline text without analysis.\n"
            "- Do not invent percentages that contradict the facts above.\n"
        )
    ab_block = ""
    if ab:
        ab_block = (
            "\n\n### A/B-TEST\n"
            "Detta är Version A vs Version B från samma körning. "
            "Jämför armarna sida vid sida. Hitta inte på att det bara fanns en sammanslagen debatt.\n"
        )
    return (
        "### OBLIGATORISKA FAKTA (ändra inte dessa siffror):\n"
        + json.dumps(data, ensure_ascii=False, indent=2)
        + "\n\n### STÖDDATA (citat och fördelningar):\n"
        + json.dumps(extras, ensure_ascii=False, indent=2, default=str)
        + ab_block
        + "\n\n### Svarformat\n"
        "- Returnera JSON med nyckeln slots: {slot_namn: innehåll}.\n"
        "- Fyll ALLA begärda slots. Tom sträng endast om omöjligt.\n"
        "- Ingen inledning eller resonemang utanför slotvärdena.\n"
        "- Ingen markdown-kodstängsel.\n"
        "- Aldrig markdown ** — använd <strong> endast i HTML-slots.\n"
        "- Rubrik-/titel-slots: kort rubriktext utan analys.\n"
        "- Hitta inte på procenttal som strider mot faktan ovan.\n"
    )


def group_questions_into_batches(
    questions: list[dict[str, Any]],
) -> list[tuple[str, list[dict[str, str]]]]:
    """Partition questions.json entries into named section batches.

    Unknown slots are appended to a final 'other' batch.
    """
    by_slot: dict[str, dict[str, str]] = {}
    for q in questions:
        slot = str(q.get("slot") or "").strip()
        question = str(q.get("question") or "").strip()
        if slot and question:
            by_slot[slot] = {"slot": slot, "question": question}

    batches: list[tuple[str, list[dict[str, str]]]] = []
    used: set[str] = set()
    for name, slot_names in NARRATIVE_BATCHES:
        items = []
        for slot in slot_names:
            if slot in by_slot:
                items.append(by_slot[slot])
                used.add(slot)
        if items:
            batches.append((name, items))

    leftover = [by_slot[s] for s in by_slot if s not in used]
    if leftover:
        batches.append(("other", leftover))
    return batches


async def fill_slot_batch(
    *,
    digest: str,
    multi: bool,
    batch_name: str,
    items: list[dict[str, str]],
    locale: ReportLocale = "sv",
) -> dict[str, str]:
    if not items:
        return {}
    system = narrative_system_prompt(multi=multi, locale=locale)
    task_lines = [
        f"- **{it['slot']}**: {it['question']}" for it in items
    ]
    expected = [it["slot"] for it in items]
    fill_intro = (
        "Fill the following slots. Keys in slots must be exactly these names:\n"
        if locale == "en"
        else "Fyll följande slots. Nycklar i slots måste vara exakt dessa namn:\n"
    )
    try:
        result = await complete_structured(
            [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": (
                        f"{digest}\n\n"
                        f"### Batch: {batch_name}\n"
                        f"{fill_intro}"
                        f"{', '.join(expected)}\n\n"
                        + "\n".join(task_lines)
                    ),
                },
            ],
            SlotBatchResponse,
        )
    except Exception:
        logger.exception("Narrative batch %s failed", batch_name)
        return {}

    out: dict[str, str] = {}
    for slot in expected:
        raw = result.slots.get(slot)
        if raw is None:
            # tolerate accidental key variants
            for k, v in result.slots.items():
                if k.strip() == slot:
                    raw = v
                    break
        if isinstance(raw, str) and raw.strip():
            out[slot] = raw
    return out
