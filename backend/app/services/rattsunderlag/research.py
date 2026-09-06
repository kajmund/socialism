"""Question → lagen.nu searches → attributed RattsunderlagResult."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import complete_structured, complete_text
from app.services.prompt_store import require_active_prompts, render_prompt
from app.services.report.rattsutredning import compute_sourcing_status
from app.services.rattsunderlag import MODULE_ID, NO_SOURCES_SUMMARY_EN, NO_SOURCES_SUMMARY_SV
from app.services.rattsunderlag.attribution import (
    apply_attribution,
    format_sources_for_prompt,
    known_source_ids,
)
from app.services.rattsunderlag.lagen_nu import LagenNuClient, build_lagen_nu_client
from app.services.rattsunderlag.schemas import (
    ForarbeteRef,
    LagtextRef,
    PraxisRef,
    RattsunderlagResult,
    SearchPlan,
)

SearchPlanner = Callable[[str, dict[str, str]], Awaitable[SearchPlan]]
Summarizer = Callable[[str, str, dict[str, str]], Awaitable[str]]


async def _default_plan(fraga: str, prompts: dict[str, str]) -> SearchPlan:
    system = render_prompt(prompts, "rattsunderlag.search_terms.system", fraga=fraga)
    user = render_prompt(prompts, "rattsunderlag.search_terms.user", fraga=fraga)
    return await complete_structured(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        SearchPlan,
    )


async def _default_summarize(
    fraga: str,
    kallor: str,
    prompts: dict[str, str],
) -> str:
    system = render_prompt(
        prompts,
        "rattsunderlag.sammanfattning.system",
        fraga=fraga,
        kallor=kallor,
    )
    user = render_prompt(
        prompts,
        "rattsunderlag.sammanfattning.user",
        fraga=fraga,
        kallor=kallor,
    )
    return await complete_text(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
    )


def _dedupe_lagtext(rows: list[LagtextRef]) -> list[LagtextRef]:
    seen: set[str] = set()
    out: list[LagtextRef] = []
    for row in rows:
        if row.sfs_id in seen:
            continue
        seen.add(row.sfs_id)
        out.append(row)
    return out


def _dedupe_praxis(rows: list[PraxisRef]) -> list[PraxisRef]:
    seen: set[str] = set()
    out: list[PraxisRef] = []
    for row in rows:
        if row.referens in seen:
            continue
        seen.add(row.referens)
        out.append(row)
    return out


def _dedupe_forarbeten(rows: list[ForarbeteRef]) -> list[ForarbeteRef]:
    seen: set[str] = set()
    out: list[ForarbeteRef] = []
    for row in rows:
        if row.referens in seen:
            continue
        seen.add(row.referens)
        out.append(row)
    return out


async def _collect_sources(
    client: LagenNuClient,
    queries: list[str],
) -> tuple[list[LagtextRef], list[PraxisRef], list[ForarbeteRef], list[str]]:
    empty_queries: list[str] = []
    law_hits: list[LagtextRef] = []
    case_hits: list[PraxisRef] = []

    async def _search(query: str) -> tuple[str, list[LagtextRef], list[PraxisRef]]:
        law, cases = await asyncio.gather(
            client.search_law(query),
            client.search_case_law(query),
        )
        return query, law, cases

    searched = await asyncio.gather(*[_search(query) for query in queries])
    for query, law, cases in searched:
        if not law and not cases:
            empty_queries.append(query)
        law_hits.extend(law)
        case_hits.extend(cases)

    unique_law = _dedupe_lagtext(law_hits)
    unique_praxis = _dedupe_praxis(case_hits)

    fetched_law = await asyncio.gather(*[client.get_sfs(item.sfs_id) for item in unique_law])
    lagtext = _dedupe_lagtext(list(fetched_law))

    refs = [item.forarbete_referens.strip() for item in lagtext if item.forarbete_referens]
    fetched_forarbeten = await asyncio.gather(
        *[client.get_forarbete(ref) for ref in refs]
    )
    return lagtext, unique_praxis, _dedupe_forarbeten(list(fetched_forarbeten)), empty_queries


async def run_rattsunderlag_research(
    *,
    fraga: str,
    customer_id: int,
    language: str,
    session: AsyncSession,
    client: LagenNuClient | None = None,
    planner: SearchPlanner | None = None,
    summarizer: Summarizer | None = None,
) -> RattsunderlagResult:
    question = fraga.strip()
    if not question:
        raise ValueError("fraga is required")
    locale: Literal["sv", "en"] = "en" if language == "en" else "sv"
    prompts = await require_active_prompts(
        session,
        customer_id=customer_id,
        module=MODULE_ID,
        language=locale,
    )
    plan = await (planner or _default_plan)(question, prompts)
    used_client = client or build_lagen_nu_client()
    lagtext, praxis, forarbeten, empty_queries = await _collect_sources(
        used_client, plan.queries
    )

    if not lagtext and not praxis and not forarbeten:
        summary = NO_SOURCES_SUMMARY_EN if locale == "en" else NO_SOURCES_SUMMARY_SV
        return RattsunderlagResult(
            fraga=question,
            lagtext=[],
            praxis=[],
            forarbeten=[],
            sammanfattning=summary,
            sourcing_status="no_sources_found",
            claims=[],
            unanswered=[],
        )

    kallor = format_sources_for_prompt(
        lagtext=lagtext, praxis=praxis, forarbeten=forarbeten
    )
    raw_summary = await (summarizer or _default_summarize)(question, kallor, prompts)
    known = known_source_ids(lagtext=lagtext, praxis=praxis, forarbeten=forarbeten)
    sammanfattning, claims, unanswered = apply_attribution(raw_summary, known)
    status = compute_sourcing_status(
        lagtext=lagtext,
        praxis=praxis,
        forarbeten=forarbeten,
        unanswered=unanswered,
        empty_queries=empty_queries,
    )
    return RattsunderlagResult(
        fraga=question,
        lagtext=lagtext,
        praxis=praxis,
        forarbeten=forarbeten,
        sammanfattning=sammanfattning,
        sourcing_status=status,
        claims=claims,
        unanswered=unanswered,
    )
