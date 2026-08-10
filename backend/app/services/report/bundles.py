"""Build RunBundle from persisted run attempt JSON."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Population, PopulationMember, Run
from app.services.report.persona_bio import persona_record_from_member
from app.schemas.domain import Tick
from app.services.oasis_run import previous_attempts, variant_plans


@dataclass
class RunBundle:
    label: str
    run_id: int
    run_name: str
    attempt_id: str
    seed: str | None
    engine: str | None
    agents: list[dict[str, Any]] = field(default_factory=list)
    posts: list[dict[str, Any]] = field(default_factory=list)
    comments: list[dict[str, Any]] = field(default_factory=list)
    measurements: list[dict[str, Any]] = field(default_factory=list)
    follows: list[dict[str, Any]] = field(default_factory=list)
    action_histogram: list[dict[str, Any]] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    tick_markers: list[dict[str, Any]] = field(default_factory=list)
    ticks_run: int = 0
    personas: list[dict[str, Any]] = field(default_factory=list)
    variant_labels: list[str] = field(default_factory=list)
    injection_texts: list[str] = field(default_factory=list)
    variant_id: str | None = None


def _injection_texts_from_ticks(ticks: list[Tick]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tick in ticks:
        for inj in tick.injections:
            text = (inj.text or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
    return out


def _injection_texts_for_variant(run: Run, variant_id: str) -> list[str]:
    """Injections for one variant plan (stem+branch for A/B)."""
    for vid, _label, ticks in variant_plans(run):
        if vid == variant_id:
            return _injection_texts_from_ticks(ticks)
    # Fallback: all plans (legacy / unknown id)
    seen: set[str] = set()
    out: list[str] = []
    for _vid, _label, ticks in variant_plans(run):
        for text in _injection_texts_from_ticks(ticks):
            if text not in seen:
                seen.add(text)
                out.append(text)
    return out


def _usable_variants(attempt: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for v in attempt.get("variants") or []:
        if not isinstance(v, dict) or v.get("error"):
            continue
        if v.get("posts") or v.get("comments") or v.get("agents"):
            out.append(v)
    return out


def find_attempt(results: dict[str, Any] | None, attempt_id: str) -> dict[str, Any] | None:
    for attempt in previous_attempts(results):
        if str(attempt.get("id")) == attempt_id:
            return attempt
    return None


def attempt_has_data(attempt: dict[str, Any]) -> bool:
    return bool(_usable_variants(attempt))


def is_ab_comparison(bundles: list[RunBundle]) -> bool:
    """True when bundles look like Version A vs Version B from one attempt."""
    if len(bundles) < 2:
        return False
    ids = {b.variant_id for b in bundles if b.variant_id}
    if ids >= {"a", "b"}:
        return True
    labels = " ".join(b.label.lower() for b in bundles)
    return "version a" in labels and "version b" in labels


async def _load_personas(session: AsyncSession, run: Run) -> list[dict[str, Any]]:
    personas: list[dict[str, Any]] = []
    stmt = (
        select(Population)
        .where(Population.id == run.population_id)
        .options(
            selectinload(Population.members).selectinload(PopulationMember.persona)
        )
    )
    pop = (await session.execute(stmt)).scalar_one_or_none()
    if pop is not None:
        for m in pop.members:
            profile_data = m.persona.profile if m.persona else None
            personas.append(
                persona_record_from_member(
                    persona_id=m.persona_id,
                    name=m.name,
                    age=m.age,
                    occ=m.occ,
                    district=m.district,
                    trait=m.trait,
                    profile_data=profile_data if isinstance(profile_data, dict) else None,
                )
            )
    return personas


def _bundle_from_variant(
    *,
    run: Run,
    attempt: dict[str, Any],
    variant: dict[str, Any],
    label: str,
    personas: list[dict[str, Any]],
) -> RunBundle:
    variant_id = str(variant.get("id") or "") or None
    variant_label = str(variant.get("label") or variant_id or "variant")
    return RunBundle(
        label=label,
        run_id=run.id,
        run_name=run.name,
        attempt_id=str(attempt.get("id") or ""),
        seed=str(attempt.get("seed") or run.seed or "") or None,
        engine=str(attempt.get("engine") or "") or None,
        agents=[a for a in (variant.get("agents") or []) if isinstance(a, dict)],
        posts=[p for p in (variant.get("posts") or []) if isinstance(p, dict)],
        comments=[c for c in (variant.get("comments") or []) if isinstance(c, dict)],
        measurements=[m for m in (variant.get("measurements") or []) if isinstance(m, dict)],
        follows=[f for f in (variant.get("follows") or []) if isinstance(f, dict)],
        action_histogram=[
            h for h in (variant.get("action_histogram") or []) if isinstance(h, dict)
        ],
        trace=[t for t in (variant.get("trace") or []) if isinstance(t, dict)],
        tick_markers=[
            m for m in (variant.get("tick_markers") or []) if isinstance(m, dict)
        ],
        ticks_run=int(variant.get("ticks_run") or 0),
        personas=personas,
        variant_labels=[variant_label],
        injection_texts=_injection_texts_for_variant(run, variant_id or "main"),
        variant_id=variant_id,
    )


async def build_bundles_for_attempt(
    session: AsyncSession,
    *,
    run_id: int,
    attempt_id: str,
    label_base: str | None = None,
) -> list[RunBundle]:
    """One bundle per simulation variant (A and B stay separate for comparison)."""
    run = await session.get(Run, run_id)
    if run is None:
        raise ValueError(f"Run not found: {run_id}")
    attempt = find_attempt(run.results if isinstance(run.results, dict) else None, attempt_id)
    if attempt is None:
        raise ValueError(f"Attempt not found: {attempt_id} on run {run_id}")
    variants = _usable_variants(attempt)
    if not variants:
        raise ValueError(f"Attempt {attempt_id} has no simulation data")

    personas = await _load_personas(session, run)
    base = (label_base or run.name).strip() or run.name

    if len(variants) == 1:
        v = variants[0]
        v_label = str(v.get("label") or v.get("id") or "")
        label = base if not v_label or v_label == "Huvudtidslinje" else f"{base} — {v_label}"
        return [
            _bundle_from_variant(
                run=run,
                attempt=attempt,
                variant=v,
                label=label,
                personas=personas,
            )
        ]

    # A/B (or multi-variant): keep each arm as its own comparable bundle
    bundles: list[RunBundle] = []
    for v in variants:
        v_label = str(v.get("label") or v.get("id") or "variant")
        bundles.append(
            _bundle_from_variant(
                run=run,
                attempt=attempt,
                variant=v,
                label=f"{base} — {v_label}",
                personas=personas,
            )
        )
    return bundles


async def build_bundle(
    session: AsyncSession,
    *,
    run_id: int,
    attempt_id: str,
    label: str | None = None,
) -> RunBundle:
    """Back-compat: first bundle for the attempt (prefer build_bundles_for_attempt)."""
    bundles = await build_bundles_for_attempt(
        session,
        run_id=run_id,
        attempt_id=attempt_id,
        label_base=label,
    )
    return bundles[0]


async def build_bundles(
    session: AsyncSession,
    sources: list[dict[str, Any]],
) -> list[RunBundle]:
    bundles: list[RunBundle] = []
    for i, src in enumerate(sources):
        run_id = int(src["run_id"])
        attempt_id = str(src["attempt_id"])
        label = src.get("label")
        if not label:
            label = f"Körning {i + 1}"
        bundles.extend(
            await build_bundles_for_attempt(
                session,
                run_id=run_id,
                attempt_id=attempt_id,
                label_base=str(label),
            )
        )
    return bundles
