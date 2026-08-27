"""Benchmark OASIS simulations across prompt configuration variants.

Compares engagement balance and SSR tone/style for the same körning while varying
``oasis.agents.action_rules`` on dedicated benchmark Configuration rows.

Usage (from backend/):
  uv sync --extra oasis
  uv run python scripts/benchmark_prompt_configurations.py --run-id 8 \\
      --repetitions 5 --boost-rounds 3

Requires real ``DEEPSEEK_API_KEY`` for simulation and ``OPENAI_API_KEY`` for SSR
tone/style classification (same paths as snabbrapport). Use ``--mechanics-only`` to
verify config creation/activation without calling external APIs.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database.models import Configuration, Population, Run
from app.database.session import SessionLocal
from app.serializers import utcnow
from app.services.kund_store import default_os_customer_id
from app.services.catalog_store import ensure_catalog_defaults
from app.services.oasis_run import OasisUnavailable, attempt_all_failed, simulate_run
from app.services.prompt_catalog import default_prompts, normalize_prompts
from app.services.prompt_store import (
    ensure_default_configurations,
    get_active_configuration,
    require_active_ssr_temperature,
    set_active_configuration,
)
from app.services.report.bundles import (
    RunBundle,
    _bundle_from_variant,
    _load_personas,
    _usable_variants,
)
from app.services.report.classify import BundleClassification, classify_bundles
from app.services.report.metrics import compute_report_metrics
from app.services.report.segment_ssr import _critical_share, _positive_share
from app.services.ssr import STYLE_LABELS

VariantKey = Literal["baseline", "symmetric_like", "symmetric_list", "list_only"]

ACTION_RULES_KEY = "oasis.agents.action_rules"

BENCHMARK_CONFIG_NAMES: dict[VariantKey, str] = {
    "baseline": "Benchmark: Baseline (action_rules)",
    "symmetric_like": "Benchmark: Symmetrisk gilla-regel",
    "symmetric_list": "Benchmark: Symmetrisk + omstrukturerad lista",
    "list_only": "Benchmark: Omstrukturerad lista (utan gilla-regel)",
}

DEFAULT_VARIANT_ORDER: tuple[VariantKey, ...] = (
    "baseline",
    "symmetric_like",
    "symmetric_list",
    "list_only",
)

DEFAULT_REPETITIONS = 5
DEFAULT_BOOST_ROUNDS = 1
DEFAULT_CRITICAL_RETENTION = 0.70
DEFAULT_MIN_REACTIONS = 15

_SYMMETRIC_LIKE_RULE = (
    "- Om du håller med eller uppskattar inlägget: gilla det och säg gärna varför "
    "— instämmande är lika naturligt som kritik."
)

_OLD_STRUCTURE_LINE = (
    "- Välj EN struktur per kommentar: invändning, ny vinkel, konkret exempel, kort anekdot,\n"
    "  retorisk fråga, eller kort instämmande/avståndstagande med namngiven person."
)

_NEW_STRUCTURE_LINE = (
    "- Välj EN struktur per kommentar: kort instämmande med namngiven person, invändning, "
    "ny vinkel,\n"
    "  konkret exempel, kort anekdot, retorisk fråga, eller avståndstagande med "
    "namngiven person."
)

_CRITICAL_AFTER_LINE = (
    "- Om du kommenterar kritiskt, sarkastiskt eller ifrågasättande: gilla INTE samma inlägg."
)


@dataclass
class PromptBenchmarkResult:
    variant: str
    configuration_id: int
    configuration_name: str
    repetition: int
    wall_seconds: float
    status: str
    error: str | None
    variants: int
    ticks_run: int
    agent_count: int
    trace_events: int
    posts: int
    comments: int
    action_histogram: list[dict[str, Any]]
    like_count: int
    dislike_count: int
    reaction_count: int
    like_ratio: float | None
    zero_engagement_agents: int
    zero_engagement_share: float | None
    gini: float | None
    tone_shares: dict[str, float] = field(default_factory=dict)
    positive_tone_share: float | None = None
    critical_tone_share: float | None = None
    neutral_tone_share: float | None = None
    style_shares: list[tuple[str, float]] = field(default_factory=list)
    sarcasm_style_share: float | None = None
    warnings: list[str] = field(default_factory=list)
    ssr_skipped: bool = False


def baseline_action_rules(language: str = "sv") -> str:
    prompts = default_prompts(language)  # type: ignore[arg-type]
    return str(prompts[ACTION_RULES_KEY])


def _insert_after(text: str, needle: str, insertion: str) -> str:
    if insertion in text:
        return text
    idx = text.find(needle)
    if idx < 0:
        raise ValueError(f"Expected anchor line not found: {needle!r}")
    end = idx + len(needle)
    return text[:end] + "\n" + insertion + text[end:]


def _replace_structure_list(text: str) -> str:
    if _NEW_STRUCTURE_LINE in text:
        return text
    if _OLD_STRUCTURE_LINE not in text:
        raise ValueError("Expected comment structure list line not found in action_rules")
    return text.replace(_OLD_STRUCTURE_LINE, _NEW_STRUCTURE_LINE)


def build_action_rules_variant(variant: VariantKey, *, language: str = "sv") -> str:
    """Return modified ``oasis.agents.action_rules`` text for a benchmark variant."""
    text = baseline_action_rules(language)
    if variant == "baseline":
        return text
    if variant == "symmetric_like":
        return _insert_after(text, _CRITICAL_AFTER_LINE, _SYMMETRIC_LIKE_RULE)
    if variant == "symmetric_list":
        text = _insert_after(text, _CRITICAL_AFTER_LINE, _SYMMETRIC_LIKE_RULE)
        return _replace_structure_list(text)
    if variant == "list_only":
        return _replace_structure_list(text)
    raise ValueError(f"Unknown variant: {variant}")


def _hist_count(histogram: list[dict[str, Any]], action: str) -> int:
    total = 0
    for row in histogram:
        if str(row.get("action") or "") == action:
            total += int(row.get("count") or 0)
    return total


def engagement_from_histogram(
    histogram: list[dict[str, Any]],
    *,
    agent_count: int,
    gini: float | None,
    zero_like_agents: int | None = None,
    comments: int = 0,
) -> dict[str, Any]:
    likes = _hist_count(histogram, "like_post") + _hist_count(histogram, "like_comment")
    dislikes = _hist_count(histogram, "dislike_post") + _hist_count(
        histogram, "dislike_comment"
    )
    reactions = likes + dislikes
    like_ratio = (likes / reactions) if reactions > 0 else None
    zero = zero_like_agents if zero_like_agents is not None else 0
    zero_share = (zero / agent_count) if agent_count > 0 else None
    return {
        "like_count": likes,
        "dislike_count": dislikes,
        "reaction_count": reactions + comments,
        "like_ratio": like_ratio,
        "zero_engagement_agents": zero,
        "zero_engagement_share": zero_share,
        "gini": gini,
    }


def tone_from_classification(
    classification: BundleClassification | None,
    *,
    locale: str = "sv",
) -> dict[str, Any]:
    if classification is None:
        return {
            "tone_shares": {},
            "positive_tone_share": None,
            "critical_tone_share": None,
            "neutral_tone_share": None,
            "style_shares": [],
            "sarcasm_style_share": None,
        }
    tone = dict(classification.tone_shares or {})
    loc = "en" if locale == "en" else "sv"
    style_shares = list(classification.style_shares or [])
    sarcasm = next(
        (share for label, share in style_shares if label == STYLE_LABELS[0]),
        None,
    )
    return {
        "tone_shares": tone,
        "positive_tone_share": _positive_share(tone, locale=loc),
        "critical_tone_share": _critical_share(tone, locale=loc),
        "neutral_tone_share": float(tone.get("Neutral") or 0.0),
        "style_shares": style_shares,
        "sarcasm_style_share": sarcasm,
    }


def aggregate_numeric(values: list[float | None]) -> dict[str, Any]:
    nums = [v for v in values if v is not None]
    if not nums:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None}
    if len(nums) == 1:
        return {
            "n": 1,
            "mean": nums[0],
            "std": 0.0,
            "min": nums[0],
            "max": nums[0],
        }
    return {
        "n": len(nums),
        "mean": statistics.mean(nums),
        "std": statistics.pstdev(nums),
        "min": min(nums),
        "max": max(nums),
    }


def aggregate_variant_results(
    runs: list[PromptBenchmarkResult],
) -> dict[str, Any]:
    ok_runs = [r for r in runs if r.status == "ok"]
    return {
        "variant": runs[0].variant if runs else "",
        "configuration_id": runs[0].configuration_id if runs else None,
        "configuration_name": runs[0].configuration_name if runs else "",
        "repetitions_requested": len(runs),
        "repetitions_ok": len(ok_runs),
        "like_ratio": aggregate_numeric([r.like_ratio for r in ok_runs]),
        "critical_tone_share": aggregate_numeric([r.critical_tone_share for r in ok_runs]),
        "sarcasm_style_share": aggregate_numeric([r.sarcasm_style_share for r in ok_runs]),
        "reaction_count": aggregate_numeric([float(r.reaction_count) for r in ok_runs]),
        "like_count": aggregate_numeric([float(r.like_count) for r in ok_runs]),
        "gini": aggregate_numeric([r.gini for r in ok_runs if r.gini is not None]),
        "runs": [asdict(r) for r in runs],
    }


def critical_retention_ok(
    *,
    candidate_mean: float | None,
    baseline_mean: float | None,
    retention: float,
) -> bool:
    """True when candidate keeps at least ``retention`` of baseline critical tone."""
    if candidate_mean is None or baseline_mean is None:
        return False
    if baseline_mean <= 0:
        return candidate_mean >= 0
    return candidate_mean >= baseline_mean * retention


def determine_conclusion(
    aggregates: list[dict[str, Any]],
    *,
    critical_retention: float,
) -> dict[str, Any]:
    baseline = next((a for a in aggregates if a["variant"] == "baseline"), None)
    if baseline is None or baseline["repetitions_ok"] == 0:
        return {
            "conclusion": "no_clear_result",
            "reason": "baseline_missing_or_failed",
            "winners": [],
            "candidates": [],
        }

    base_like = baseline["like_ratio"]["mean"]
    base_crit = baseline["critical_tone_share"]["mean"]
    if base_like is None:
        return {
            "conclusion": "no_clear_result",
            "reason": "baseline_like_ratio_unavailable",
            "winners": [],
            "candidates": [],
        }
    if base_crit is None:
        return {
            "conclusion": "no_clear_result",
            "reason": "baseline_critical_tone_unavailable_ssr_required",
            "winners": [],
            "candidates": [],
        }

    candidates: list[dict[str, Any]] = []
    for agg in aggregates:
        if agg["variant"] == "baseline":
            continue
        if agg["repetitions_ok"] == 0:
            continue
        cand_like = agg["like_ratio"]["mean"]
        cand_crit = agg["critical_tone_share"]["mean"]
        if cand_like is None or cand_crit is None:
            continue
        passes_like = cand_like > base_like
        passes_crit = critical_retention_ok(
            candidate_mean=cand_crit,
            baseline_mean=base_crit,
            retention=critical_retention,
        )
        candidates.append(
            {
                "variant": agg["variant"],
                "like_ratio_mean": cand_like,
                "like_ratio_delta": cand_like - base_like,
                "critical_tone_share_mean": cand_crit,
                "critical_retention_ratio": (
                    cand_crit / base_crit if base_crit > 0 else None
                ),
                "passes_like_improvement": passes_like,
                "passes_critical_retention": passes_crit,
                "passes_all": passes_like and passes_crit,
            }
        )

    winners = [c for c in candidates if c["passes_all"]]
    if not winners:
        return {
            "conclusion": "no_clear_result",
            "reason": "no_variant_passed_winner_criteria",
            "winners": [],
            "candidates": candidates,
            "baseline": {
                "like_ratio_mean": base_like,
                "critical_tone_share_mean": base_crit,
            },
            "criteria": {
                "like_ratio_must_exceed_baseline": True,
                "critical_tone_retention_min": critical_retention,
            },
        }

    winners.sort(key=lambda c: (c["like_ratio_delta"], c["like_ratio_mean"]), reverse=True)
    return {
        "conclusion": "winner",
        "reason": "passed_like_and_critical_retention",
        "winners": winners,
        "winner": winners[0]["variant"],
        "candidates": candidates,
        "baseline": {
            "like_ratio_mean": base_like,
            "critical_tone_share_mean": base_crit,
        },
        "criteria": {
            "like_ratio_must_exceed_baseline": True,
            "critical_tone_retention_min": critical_retention,
        },
    }


def detect_overcorrection_warnings(
    result: PromptBenchmarkResult,
    *,
    baseline: PromptBenchmarkResult | None,
) -> list[str]:
    warnings: list[str] = []
    if result.critical_tone_share is not None and result.critical_tone_share < 0.05:
        warnings.append(
            "critical_tone_share below 5% — kritik/sarkasm kan ha pressats bort"
        )
    if result.sarcasm_style_share is not None and result.sarcasm_style_share < 0.02:
        warnings.append(
            "sarcasm_style_share below 2% — sarkastisk stil nästan borta"
        )
    if result.gini is not None and result.gini < 0.15 and result.like_ratio is not None:
        if result.like_ratio > 0.4:
            warnings.append(
                "gini unusually low with high like_ratio — engagement may be artificially even"
            )
    if baseline is not None and baseline.status == "ok" and result.status == "ok":
        base_crit = baseline.critical_tone_share
        if (
            base_crit is not None
            and result.critical_tone_share is not None
            and base_crit >= 0.10
            and result.critical_tone_share < base_crit * 0.35
        ):
            warnings.append(
                "critical_tone_share dropped sharply vs baseline — possible overcorrection"
            )
    if result.reaction_count < DEFAULT_MIN_REACTIONS:
        warnings.append(
            f"reaction_count={result.reaction_count} below recommended "
            f"{DEFAULT_MIN_REACTIONS} — high sampling noise expected"
        )
    return warnings


def _multiply_tick_rounds(ticks: list[dict[str, Any]], multiplier: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tick in ticks:
        row = copy.deepcopy(tick)
        base_rounds = max(1, int(row.get("rounds") or 1))
        row["rounds"] = base_rounds * multiplier
        out.append(row)
    return out


def apply_boost_rounds(run: Run, multiplier: int) -> None:
    """Scale reaction rounds on ticks in-memory (does not persist to DB)."""
    if multiplier <= 1:
        return
    run.main_ticks = _multiply_tick_rounds(list(run.main_ticks or []), multiplier)
    branch = run.branch
    if isinstance(branch, dict):
        branch_copy = copy.deepcopy(branch)
        for key in ("a", "b"):
            ticks = branch_copy.get(key)
            if isinstance(ticks, list):
                branch_copy[key] = _multiply_tick_rounds(ticks, multiplier)
        run.branch = branch_copy


def inspect_run(run: Run, population: Population) -> dict[str, Any]:
    members = list(population.members or [])
    main_ticks = list(run.main_ticks or [])
    main_rounds = sum(max(1, int(t.get("rounds") or 1)) for t in main_ticks)
    branch_rounds = 0
    branch = run.branch if isinstance(run.branch, dict) else None
    if branch:
        for key in ("a", "b"):
            for tick in branch.get(key) or []:
                branch_rounds += max(1, int(tick.get("rounds") or 1))
    return {
        "run_id": run.id,
        "run_name": run.name,
        "population_name": population.name,
        "population_members": len(members),
        "main_ticks": len(main_ticks),
        "main_reaction_rounds": main_rounds,
        "branch_reaction_rounds": branch_rounds,
        "has_ab_branch": bool(branch),
        "recommended_min_reactions": DEFAULT_MIN_REACTIONS,
    }


def _summarize_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
    variants = attempt.get("variants") or []
    trace_events = 0
    posts = 0
    comments = 0
    ticks_run = 0
    agent_count = 0
    action_histogram: dict[str, int] = {}

    for variant in variants:
        ticks_run += int(variant.get("ticks_run") or 0)
        agent_count = max(agent_count, int(variant.get("agent_count") or 0))
        posts += len(variant.get("posts") or [])
        comments += len(variant.get("comments") or [])
        trace_events += len(variant.get("trace") or [])
        for row in variant.get("action_histogram") or []:
            action = str(row.get("action") or "unknown")
            action_histogram[action] = action_histogram.get(action, 0) + int(
                row.get("count") or 0
            )

    histogram_out = [
        {"action": action, "count": count}
        for action, count in sorted(action_histogram.items(), key=lambda x: (-x[1], x[0]))
    ]
    return {
        "variants": len(variants),
        "ticks_run": ticks_run,
        "agent_count": agent_count,
        "trace_events": trace_events,
        "posts": posts,
        "comments": comments,
        "action_histogram": histogram_out,
    }


async def _build_bundles_from_attempt(
    session,
    *,
    run: Run,
    attempt: dict[str, Any],
) -> list[RunBundle]:
    variants = _usable_variants(attempt)
    if not variants:
        raise ValueError("Attempt has no simulation data")
    personas = await _load_personas(session, run)
    base = (run.name or "").strip() or f"Run {run.id}"
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


async def ensure_benchmark_configuration(
    session,
    *,
    variant: VariantKey,
    template: Configuration,
) -> Configuration:
    name = BENCHMARK_CONFIG_NAMES[variant]
    result = await session.execute(
        select(Configuration).where(Configuration.name == name).limit(1)
    )
    row = result.scalar_one_or_none()
    prompts = dict(template.prompts or {})
    prompts[ACTION_RULES_KEY] = build_action_rules_variant(variant, language=template.language)
    normalized = normalize_prompts(
        prompts,
        language=template.language,  # type: ignore[arg-type]
        fill_missing=True,
    )
    now = utcnow()
    if row is None:
        customer_id = await default_os_customer_id(session)
        row = Configuration(
            customer_id=customer_id,
            name=name,
            language=template.language,
            prompts=normalized,
            ssr_temperature=float(template.ssr_temperature),
            report_thresholds=dict(template.report_thresholds or {}),
            anchor_sets=dict(template.anchor_sets or {}),
            is_active=False,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        await ensure_catalog_defaults(session, row.id)
        return row

    if dict(row.prompts or {}) != normalized:
        row.prompts = normalized
        row.updated_at = now
        await session.commit()
        await session.refresh(row)
    return row


async def benchmark_variant(
    *,
    run_id: int,
    variant: VariantKey,
    configuration_id: int,
    configuration_name: str,
    repetition: int,
    boost_rounds: int,
    skip_ssr: bool,
) -> PromptBenchmarkResult:
    settings.apply_oasis_env()

    async with SessionLocal() as session:
        result = await session.execute(
            select(Run)
            .options(selectinload(Run.population).selectinload(Population.members))
            .where(Run.id == run_id)
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise SystemExit(f"Run {run_id} not found")

        apply_boost_rounds(run, boost_rounds)

        await set_active_configuration(session, configuration_id)

        started = time.perf_counter()
        error: str | None = None
        attempt: dict[str, Any] = {}
        try:
            results = await simulate_run(session, run)
            attempts = results.get("attempts") or []
            attempt = attempts[0] if attempts else {}
            if attempt.get("error"):
                error = str(attempt["error"])
            elif attempt_all_failed(attempt):
                error = "All variants failed"
        except (OasisUnavailable, RuntimeError, OSError) as exc:
            error = str(exc)
        elapsed = time.perf_counter() - started

        summary = _summarize_attempt(attempt)
        status = "failed" if error else "ok"

        tone_payload: dict[str, Any] = {}
        gini: float | None = None
        zero_like: int | None = None
        ssr_skipped = skip_ssr

        if status == "ok" and attempt:
            try:
                bundles = await _build_bundles_from_attempt(session, run=run, attempt=attempt)
                classifications: list[BundleClassification] = []
                if not skip_ssr:
                    resolved = await require_anchor_sets_for_language(session, "sv")
                    temperature = await require_active_ssr_temperature(session)
                    classifications = await classify_bundles(
                        bundles,
                        locale="sv",
                        ssr_temperature=temperature,
                        tone_anchor_set=resolved["tone"],
                        style_anchor_set=resolved["style"],
                        tone_anchor_vectors=resolved["tone_vectors"],
                        style_anchor_vectors=resolved["style_vectors"],
                    )
                else:
                    ssr_skipped = True
                metrics = compute_report_metrics(bundles, classifications or None)
                agg = metrics.aggregate
                gini = agg.gini
                zero_like = agg.zero_like_agents
                if classifications:
                    merged_tone: dict[str, float] = {}
                    for clf in classifications:
                        for lab, share in (clf.tone_shares or {}).items():
                            merged_tone[lab] = merged_tone.get(lab, 0.0) + share
                    n = len(classifications) or 1
                    merged_tone = {lab: val / n for lab, val in merged_tone.items()}
                    merged_style: dict[str, float] = {}
                    for clf in classifications:
                        for lab, share in clf.style_shares or []:
                            merged_style[lab] = merged_style.get(lab, 0.0) + share
                    merged_style_list = [
                        (lab, merged_style.get(lab, 0.0) / n) for lab in STYLE_LABELS
                    ]
                    tone_payload = tone_from_classification(
                        BundleClassification(
                            tone_shares=merged_tone,
                            style_shares=merged_style_list,
                        ),
                        locale="sv",
                    )
            except Exception as exc:  # noqa: BLE001 — benchmark collects per-variant errors
                if error is None:
                    error = f"Metrics/classification failed: {exc}"
                status = "failed"

        engagement = engagement_from_histogram(
            summary["action_histogram"],
            agent_count=summary["agent_count"],
            gini=gini,
            zero_like_agents=zero_like,
            comments=summary["comments"],
        )

        row = PromptBenchmarkResult(
            variant=variant,
            configuration_id=configuration_id,
            configuration_name=configuration_name,
            repetition=repetition,
            wall_seconds=round(elapsed, 2),
            status=status,
            error=error,
            variants=summary["variants"],
            ticks_run=summary["ticks_run"],
            agent_count=summary["agent_count"],
            trace_events=summary["trace_events"],
            posts=summary["posts"],
            comments=summary["comments"],
            action_histogram=summary["action_histogram"],
            like_count=engagement["like_count"],
            dislike_count=engagement["dislike_count"],
            reaction_count=int(engagement["reaction_count"]),
            like_ratio=engagement["like_ratio"],
            zero_engagement_agents=engagement["zero_engagement_agents"],
            zero_engagement_share=engagement["zero_engagement_share"],
            gini=engagement["gini"],
            tone_shares=tone_payload.get("tone_shares", {}),
            positive_tone_share=tone_payload.get("positive_tone_share"),
            critical_tone_share=tone_payload.get("critical_tone_share"),
            neutral_tone_share=tone_payload.get("neutral_tone_share"),
            style_shares=tone_payload.get("style_shares", []),
            sarcasm_style_share=tone_payload.get("sarcasm_style_share"),
            ssr_skipped=ssr_skipped,
        )
        return row


def _format_aggregate_summary(
    aggregates: list[dict[str, Any]],
    conclusion: dict[str, Any],
) -> str:
    lines = ["", "=== Aggregerat resultat (medel ± std) ==="]
    for agg in aggregates:
        like = agg["like_ratio"]
        crit = agg["critical_tone_share"]
        sarc = agg["sarcasm_style_share"]
        like_s = (
            f"{like['mean'] * 100:.1f}% ± {like['std'] * 100:.1f}%"
            if like["mean"] is not None and like["std"] is not None
            else "n/a"
        )
        crit_s = (
            f"{crit['mean'] * 100:.1f}% ± {crit['std'] * 100:.1f}%"
            if crit["mean"] is not None and crit["std"] is not None
            else "n/a"
        )
        sarc_s = (
            f"{sarc['mean'] * 100:.1f}% ± {sarc['std'] * 100:.1f}%"
            if sarc["mean"] is not None and sarc["std"] is not None
            else "n/a"
        )
        lines.append(
            f"{agg['variant']}: ok={agg['repetitions_ok']}/{agg['repetitions_requested']} "
            f"like_ratio={like_s} kritisk={crit_s} sarkasm={sarc_s}"
        )

    lines.append("")
    if conclusion["conclusion"] == "winner":
        lines.append(f"Slutsats: vinnare = {conclusion['winner']}")
        lines.append(
            f"  (högre like_ratio än baseline, kritisk ton ≥ "
            f"{conclusion['criteria']['critical_tone_retention_min'] * 100:.0f}% av baseline)"
        )
    else:
        lines.append("Slutsats: inget tydligt resultat")
        lines.append(f"  Orsak: {conclusion['reason']}")
    return "\n".join(lines)


def _keys_available() -> tuple[bool, bool, list[str]]:
    notes: list[str] = []
    deepseek_ok = bool(
        settings.deepseek_api_key
        and not str(settings.deepseek_api_key).startswith("placeholder")
        and settings.deepseek_api_key != "test-key-not-real"
    )
    openai_ok = bool(
        settings.openai_api_key
        and not str(settings.openai_api_key).startswith("placeholder")
        and settings.openai_api_key != "test-openai-key-not-real"
    )
    if not deepseek_ok:
        notes.append("DEEPSEEK_API_KEY missing or placeholder — simulation will not run")
    if not openai_ok:
        notes.append("OPENAI_API_KEY missing or placeholder — SSR tone/style is required")
    return deepseek_ok, openai_ok, notes


async def main_async(args: argparse.Namespace) -> None:
    deepseek_ok, openai_ok, key_notes = _keys_available()
    if args.mechanics_only:
        deepseek_ok = False

    if not deepseek_ok and not args.mechanics_only:
        raise SystemExit(
            "DEEPSEEK_API_KEY is required for simulation. "
            "Set it in backend/.env or use --mechanics-only to verify config setup only."
        )

    if not openai_ok and not args.mechanics_only and not args.skip_ssr:
        raise SystemExit(
            "OPENAI_API_KEY is required for SSR tone/style classification. "
            "This benchmark needs critical_tone_share and sarcasm_style_share. "
            "Use --mechanics-only to verify config rows without simulating."
        )

    variants: list[VariantKey] = list(args.variants)
    skip_ssr = bool(args.skip_ssr)
    if skip_ssr and not args.mechanics_only:
        key_notes.append(
            "WARNING: --skip-ssr set — critical_tone_share/sarcasm_style_share will be missing"
        )

    async with SessionLocal() as session:
        await ensure_default_configurations(session)
        original_active = await get_active_configuration(session)
        template = original_active
        if template is None:
            raise SystemExit("No configuration in database — run seed first.")
        if template.language != "sv":
            result = await session.execute(
                select(Configuration)
                .where(Configuration.language == "sv")
                .order_by(Configuration.id.asc())
            )
            template = result.scalars().first()
        if template is None:
            raise SystemExit("No Swedish configuration template found.")

        config_rows: dict[VariantKey, Configuration] = {}
        for variant in variants:
            config_rows[variant] = await ensure_benchmark_configuration(
                session,
                variant=variant,
                template=template,
            )

        run_result = await session.execute(
            select(Run)
            .options(selectinload(Run.population).selectinload(Population.members))
            .where(Run.id == args.run_id)
        )
        run = run_result.scalar_one_or_none()
        if run is None:
            raise SystemExit(f"Run {args.run_id} not found")
        population = run.population
        if population is None:
            raise SystemExit(f"Run {args.run_id} has no population")
        run_inspection = inspect_run(run, population)

    total_runs = len(variants) * args.repetitions
    print(
        f"Benchmark plan: {len(variants)} variants × {args.repetitions} repetitions "
        f"= {total_runs} simulations"
    )
    print(
        f"Run {args.run_id}: {run_inspection['population_members']} population members, "
        f"{run_inspection['main_ticks']} main ticks, "
        f"{run_inspection['main_reaction_rounds']} main reaction rounds"
        + (f" (×{args.boost_rounds} boost → "
           f"{run_inspection['main_reaction_rounds'] * args.boost_rounds} effective)"
           if args.boost_rounds > 1
           else "")
    )
    if run_inspection["population_members"] < 10:
        key_notes.append(
            "Population has fewer than 10 members — consider seed run "
            "'Prompt benchmark — volym' (id after re-seed) or a larger production population"
        )
    if run_inspection["has_ab_branch"]:
        key_notes.append(
            "Run has A/B branch — benchmark compares variants on full run shape; "
            "prefer single-arm runs for cleaner prompt A/B tests"
        )

    cost_note = (
        f"Estimated LLM calls: ~{total_runs} DeepSeek simulation batches + "
        f"SSR classify per ok repetition"
    )
    if total_runs > 12:
        print(cost_note)
        print(
            "Tip: reduce cost with --repetitions 3 or --variants baseline symmetric_like "
            "if a variant is clearly worse in early reps"
        )

    out: dict[str, Any] = {
        "run_id": args.run_id,
        "variants": variants,
        "repetitions": args.repetitions,
        "boost_rounds": args.boost_rounds,
        "critical_retention_min": args.critical_retention,
        "skip_ssr": skip_ssr,
        "mechanics_only": args.mechanics_only,
        "key_notes": key_notes,
        "run_inspection": run_inspection,
        "aggregates": [],
        "conclusion": {},
    }

    if args.mechanics_only:
        for variant in variants:
            row = config_rows[variant]
            out["aggregates"].append(
                {
                    "variant": variant,
                    "configuration_id": row.id,
                    "configuration_name": row.name,
                    "status": "mechanics_only",
                    "action_rules_preview": build_action_rules_variant(variant)[:240]
                    + "…",
                }
            )
        if args.output:
            from pathlib import Path

            Path(args.output).write_text(
                json.dumps(out, indent=2, ensure_ascii=False) + "\n"
            )
            print(f"\nSparat till {args.output}")
        print("Mechanics-only: benchmark configurations ensured (no simulation run).")
        return

    aggregates: list[dict[str, Any]] = []
    baseline_by_rep: dict[int, PromptBenchmarkResult] = {}
    try:
        for variant in variants:
            cfg = config_rows[variant]
            rep_results: list[PromptBenchmarkResult] = []
            print(f"\n=== Variant {variant} (config id={cfg.id}) ===")
            for rep in range(1, args.repetitions + 1):
                print(f"--- Repetition {rep}/{args.repetitions} ---")
                result = await benchmark_variant(
                    run_id=args.run_id,
                    variant=variant,
                    configuration_id=cfg.id,
                    configuration_name=cfg.name,
                    repetition=rep,
                    boost_rounds=args.boost_rounds,
                    skip_ssr=skip_ssr,
                )
                baseline_rep: PromptBenchmarkResult | None = None
                if variant == "baseline":
                    baseline_by_rep[rep] = result
                else:
                    baseline_rep = baseline_by_rep.get(rep)
                result.warnings = detect_overcorrection_warnings(
                    result, baseline=baseline_rep
                )
                rep_results.append(result)
                like_s = (
                    f"{result.like_ratio * 100:.0f}%"
                    if result.like_ratio is not None
                    else "n/a"
                )
                crit_s = (
                    f"{result.critical_tone_share * 100:.0f}%"
                    if result.critical_tone_share is not None
                    else "n/a"
                )
                print(
                    f"{variant} rep{rep}: {result.wall_seconds}s ({result.status}) "
                    f"reactions={result.reaction_count} like_ratio={like_s} "
                    f"kritisk={crit_s} gini={result.gini}"
                )
                if result.error:
                    print(f"  error: {result.error}")
                for w in result.warnings:
                    print(f"  warning: {w}")

            agg = aggregate_variant_results(rep_results)
            aggregates.append(agg)
    finally:
        if original_active is not None:
            async with SessionLocal() as session:
                await set_active_configuration(session, original_active.id)

    conclusion = determine_conclusion(
        aggregates,
        critical_retention=args.critical_retention,
    )
    summary = _format_aggregate_summary(aggregates, conclusion)
    print(summary)

    out["aggregates"] = aggregates
    out["conclusion"] = conclusion
    out["summary_note"] = summary.strip()

    if args.output:
        from pathlib import Path

        Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
        print(f"\nSparat till {args.output}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark OASIS prompt configuration variants (action_rules)"
    )
    parser.add_argument(
        "--run-id",
        type=int,
        default=7,
        help="Körning id (default: 7 = seed 'Prompt benchmark — volym')",
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        choices=list(DEFAULT_VARIANT_ORDER),
        default=list(DEFAULT_VARIANT_ORDER),
        help="Prompt variants to compare",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=DEFAULT_REPETITIONS,
        help=f"Simulation repetitions per variant (default: {DEFAULT_REPETITIONS})",
    )
    parser.add_argument(
        "--boost-rounds",
        type=int,
        default=DEFAULT_BOOST_ROUNDS,
        help=(
            "Multiply each tick's reaction rounds in-memory before simulating "
            f"(default: {DEFAULT_BOOST_ROUNDS}; use 2–3 for more engagement events)"
        ),
    )
    parser.add_argument(
        "--critical-retention",
        type=float,
        default=DEFAULT_CRITICAL_RETENTION,
        help=(
            "Winner must keep at least this fraction of baseline critical_tone_share "
            f"(default: {DEFAULT_CRITICAL_RETENTION} = max 30%% relative drop)"
        ),
    )
    parser.add_argument(
        "--output",
        default="data/benchmark_prompt_configurations.json",
        help="JSON output path (default: data/benchmark_prompt_configurations.json)",
    )
    parser.add_argument(
        "--skip-ssr",
        action="store_true",
        help="Skip OpenAI SSR (not recommended — breaks winner criteria)",
    )
    parser.add_argument(
        "--mechanics-only",
        action="store_true",
        help="Only create/update benchmark Configuration rows; do not simulate",
    )
    args = parser.parse_args()
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be at least 1")
    if args.boost_rounds < 1:
        raise SystemExit("--boost-rounds must be at least 1")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
