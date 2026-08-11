"""SSR anchor pool: append-only items on published sets + centroid vectors."""

from __future__ import annotations

import json
import threading
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    PersonaMessage,
    SsrAnchorCalibrationItem,
    SsrAnchorPoolItem,
    SsrAnchorSet,
)
from app.services.anchor_store import (
    AnchorResolutionError,
    require_anchor_set_row,
)
from app.services.prompt_store import get_active_configuration
from app.services.report.bundles import build_bundles_for_attempt
from app.services.report.locale import ReportLocale, normalize_locale
from app.services.run_results import find_attempt, find_variant
from app.services.ssr.embeddings import embed_texts_cached
from app.serializers import utcnow

AnchorPoolSourceType = Literal["comment", "tick_interview", "posthoc_interview"]

_centroid_cache: dict[tuple[int, int], list[list[float]]] = {}
_centroid_lock = threading.Lock()


class AnchorPoolError(RuntimeError):
    """Raised when pool operations fail validation."""


def drop_centroid_cache() -> None:
    """Clear in-process centroid cache (tests)."""
    with _centroid_lock:
        _centroid_cache.clear()


def compute_centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        raise ValueError("compute_centroid requires at least one vector")
    dims = len(vectors[0])
    acc = [0.0] * dims
    for vec in vectors:
        if len(vec) != dims:
            raise ValueError("centroid input vectors must share dimension")
        for i, x in enumerate(vec):
            acc[i] += x
    n = len(vectors)
    return [x / n for x in acc]


def _source_ref_key(source_ref: dict[str, Any]) -> str:
    return json.dumps(source_ref, sort_keys=True, ensure_ascii=False)


async def pool_items_for_set(
    session: AsyncSession, anchor_set_id: int
) -> list[SsrAnchorPoolItem]:
    stmt = (
        select(SsrAnchorPoolItem)
        .where(SsrAnchorPoolItem.anchor_set_id == anchor_set_id)
        .order_by(SsrAnchorPoolItem.id.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def texts_for_label(
    row: SsrAnchorSet,
    pool_items: list[SsrAnchorPoolItem],
    label: str,
) -> list[str]:
    labels = [str(x) for x in (row.labels or [])]
    statements = [str(x) for x in (row.statements or [])]
    try:
        idx = labels.index(label)
    except ValueError as exc:
        raise AnchorPoolError(f"Unknown label {label!r} for anchor set {row.id}") from exc
    seed = statements[idx].strip()
    if not seed:
        raise AnchorPoolError(f"Empty seed statement for label {label!r}")
    pool_texts = [item.text.strip() for item in pool_items if item.label == label and item.text.strip()]
    return [seed, *pool_texts]


async def centroid_vectors_for_set(
    session: AsyncSession,
    row: SsrAnchorSet,
) -> list[list[float]]:
    revision = int(row.pool_revision or 0)
    cache_key = (int(row.id), revision)
    with _centroid_lock:
        hit = _centroid_cache.get(cache_key)
        if hit is not None:
            return [list(v) for v in hit]

    pool_items = await pool_items_for_set(session, int(row.id))
    labels = [str(x) for x in (row.labels or [])]
    all_texts: list[str] = []
    spans: list[tuple[int, int]] = []
    for label in labels:
        texts = await texts_for_label(row, pool_items, label)
        start = len(all_texts)
        all_texts.extend(texts)
        spans.append((start, len(all_texts)))

    vectors = await embed_texts_cached(all_texts)
    if len(vectors) != len(all_texts):
        raise RuntimeError("embed_texts_cached returned unexpected vector count")

    centroids: list[list[float]] = []
    for start, end in spans:
        label_vecs = vectors[start:end]
        centroids.append(compute_centroid(label_vecs))

    with _centroid_lock:
        _centroid_cache[cache_key] = [list(v) for v in centroids]
    return centroids


async def bump_pool_revision(session: AsyncSession, row: SsrAnchorSet) -> int:
    row.pool_revision = int(row.pool_revision or 0) + 1
    row.updated_at = utcnow()
    await session.flush()
    return int(row.pool_revision)


def validate_label(row: SsrAnchorSet, label: str) -> None:
    allowed = {str(x) for x in (row.labels or [])}
    if label not in allowed:
        raise AnchorPoolError(
            f"label {label!r} is not in anchor set labels: {', '.join(sorted(allowed))}"
        )


async def add_pool_item(
    session: AsyncSession,
    *,
    anchor_set_id: int,
    label: str,
    text: str,
    source_type: AnchorPoolSourceType,
    source_run_id: int | None,
    source_attempt_id: str | None,
    source_variant_id: str | None,
    source_ref: dict[str, Any],
    add_to_calibration: bool = False,
) -> SsrAnchorPoolItem:
    row = await require_anchor_set_row(session, anchor_set_id)
    cleaned = " ".join(text.split())
    if not cleaned:
        raise AnchorPoolError("text must be non-empty")
    validate_label(row, label)

    item = SsrAnchorPoolItem(
        anchor_set_id=anchor_set_id,
        label=label,
        text=cleaned,
        source_type=source_type,
        source_run_id=source_run_id,
        source_attempt_id=source_attempt_id,
        source_variant_id=source_variant_id,
        source_ref=source_ref,
        created_at=utcnow(),
    )
    session.add(item)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise AnchorPoolError(
            f"Pool already contains this text for label {label!r}"
        ) from exc

    if add_to_calibration:
        session.add(
            SsrAnchorCalibrationItem(
                anchor_set_id=anchor_set_id,
                text=cleaned,
                human_label=label,
                sort_order=0,
                created_at=utcnow(),
            )
        )

    await bump_pool_revision(session, row)
    return item


async def remove_pool_item(
    session: AsyncSession,
    *,
    anchor_set_id: int,
    item_id: int,
) -> None:
    row = await require_anchor_set_row(session, anchor_set_id)
    item = await session.get(SsrAnchorPoolItem, item_id)
    if item is None or item.anchor_set_id != anchor_set_id:
        raise AnchorPoolError("Pool item not found")
    await session.delete(item)
    await bump_pool_revision(session, row)


async def resolve_active_anchor_set_ids(
    session: AsyncSession,
    locale: ReportLocale,
) -> dict[str, int]:
    """Tone/style anchor set ids from the active configuration for ``locale``."""
    loc = normalize_locale(locale)
    lang = "en" if loc == "en" else "sv"
    config = await get_active_configuration(session)
    if config is None:
        raise AnchorResolutionError(
            "No active prompt configuration. Activate one under Konfigurationer."
        )
    if config.language != lang:
        raise AnchorResolutionError(
            f"Active configuration '{config.name}' is language '{config.language}', "
            f"but {lang!r} was requested."
        )
    refs = dict(config.anchor_sets or {})
    block = refs.get(loc)
    if not isinstance(block, dict):
        raise AnchorResolutionError(f"Configuration missing anchor_sets[{loc!r}]")
    tone_id = int(block.get("tone") or 0)
    style_id = int(block.get("style") or 0)
    if tone_id <= 0 or style_id <= 0:
        raise AnchorResolutionError(f"Configuration missing tone/style refs for {loc!r}")
    return {"tone": tone_id, "style": style_id}


async def active_anchor_context(
    session: AsyncSession,
    locale: ReportLocale,
) -> dict[str, Any]:
    ids = await resolve_active_anchor_set_ids(session, locale)
    tone_row = await require_anchor_set_row(session, ids["tone"])
    style_row = await require_anchor_set_row(session, ids["style"])
    return {
        "locale": normalize_locale(locale),
        "configuration_language": tone_row.locale,
        "tone": {
            "id": int(tone_row.id),
            "name": tone_row.name,
            "kind": tone_row.kind,
            "labels": list(tone_row.labels or []),
            "pool_revision": int(tone_row.pool_revision or 0),
        },
        "style": {
            "id": int(style_row.id),
            "name": style_row.name,
            "kind": style_row.kind,
            "labels": list(style_row.labels or []),
            "pool_revision": int(style_row.pool_revision or 0),
        },
    }


def _comment_ref(comment: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "comment",
        "post_id": comment.get("post_id"),
        "comment_id": comment.get("comment_id"),
        "user_id": comment.get("user_id"),
        "created_at": comment.get("created_at"),
    }


def _tick_interview_ref(row: dict[str, Any], prompt: str, answer: str) -> dict[str, Any]:
    return {
        "type": "tick_interview",
        "user_id": row.get("user_id"),
        "created_at": row.get("created_at"),
        "prompt": prompt,
        "answer_hash": hash(answer),
    }

def _posthoc_ref(message_id: int) -> dict[str, Any]:
    return {"type": "posthoc_interview", "persona_message_id": message_id}


async def list_tagger_texts(
    session: AsyncSession,
    *,
    run_id: int,
    attempt_id: str,
    variant_id: str,
    locale: ReportLocale,
) -> dict[str, Any]:
    from app.database.models import Run

    run = await session.get(Run, run_id)
    if run is None:
        raise AnchorPoolError("Run not found")
    attempt = find_attempt(run.results, attempt_id)
    if attempt is None:
        raise AnchorPoolError("Attempt not found")
    variant = find_variant(attempt, variant_id)
    if variant is None:
        raise AnchorPoolError("Variant not found")

    bundle = None
    bundles = await build_bundles_for_attempt(
        session, run_id=run_id, attempt_id=attempt_id
    )
    for candidate in bundles:
        if str(candidate.variant_id or "") == variant_id:
            bundle = candidate
            break
    if bundle is None:
        raise AnchorPoolError(f"Variant {variant_id!r} not found in attempt")
    anchor_ctx = await active_anchor_context(session, locale)
    tone_id = anchor_ctx["tone"]["id"]
    style_id = anchor_ctx["style"]["id"]

    tone_pool = await pool_items_for_set(session, tone_id)
    style_pool = await pool_items_for_set(session, style_id)
    tone_by_ref: dict[str, list[str]] = {}
    style_by_ref: dict[str, list[str]] = {}
    for item in tone_pool:
        if item.source_run_id == run_id and item.source_attempt_id == attempt_id:
            key = _source_ref_key(dict(item.source_ref or {}))
            tone_by_ref.setdefault(key, []).append(item.label)
    for item in style_pool:
        if item.source_run_id == run_id and item.source_attempt_id == attempt_id:
            key = _source_ref_key(dict(item.source_ref or {}))
            style_by_ref.setdefault(key, []).append(item.label)

    rows: list[dict[str, Any]] = []

    for comment in variant.get("comments") or []:
        if not isinstance(comment, dict):
            continue
        text = str(comment.get("content") or comment.get("text") or "").strip()
        if not text:
            continue
        ref = _comment_ref(comment)
        key = _source_ref_key(ref)
        rows.append(
            {
                "source_type": "comment",
                "source_ref": ref,
                "text": text,
                "meta": {
                    "author": comment.get("username") or comment.get("user_name") or "",
                    "post_id": comment.get("post_id"),
                },
                "tone_labels": tone_by_ref.get(key, []),
                "style_labels": style_by_ref.get(key, []),
            }
        )

    for row in bundle.trace or []:
        if str(row.get("action") or "").strip().lower() != "interview":
            continue
        info_raw = row.get("info")
        if isinstance(info_raw, dict):
            info = info_raw
        else:
            try:
                info = json.loads(str(info_raw or "{}"))
            except json.JSONDecodeError:
                info = {}
        prompt = str(info.get("prompt") or info.get("question") or "").strip()
        answer = str(info.get("response") or info.get("answer") or "").strip()
        if not answer or answer == "—":
            continue
        ref = _tick_interview_ref(row, prompt, answer)
        key = _source_ref_key(ref)
        user_id = int(row.get("user_id") or -1)
        agent_name = next(
            (
                str(a.get("member_name") or a.get("username") or "")
                for a in bundle.agents
                if a.get("index") == user_id
            ),
            "",
        )
        rows.append(
            {
                "source_type": "tick_interview",
                "source_ref": ref,
                "text": answer,
                "meta": {
                    "author": agent_name or f"agent {user_id}",
                    "question": prompt,
                    "created_at": row.get("created_at"),
                },
                "tone_labels": tone_by_ref.get(key, []),
                "style_labels": style_by_ref.get(key, []),
            }
        )

    stmt = (
        select(PersonaMessage)
        .where(
            PersonaMessage.run_id == run_id,
            PersonaMessage.attempt_id == attempt_id,
            PersonaMessage.variant_id == variant_id,
            PersonaMessage.mode == "interview",
            PersonaMessage.role == "assistant",
        )
        .order_by(PersonaMessage.id.asc())
    )
    result = await session.execute(stmt)
    for msg in result.scalars().all():
        text = msg.content.strip()
        if not text:
            continue
        ref = _posthoc_ref(int(msg.id))
        key = _source_ref_key(ref)
        rows.append(
            {
                "source_type": "posthoc_interview",
                "source_ref": ref,
                "text": text,
                "meta": {
                    "persona_id": msg.persona_id,
                    "through_tick_index": msg.through_tick_index,
                },
                "tone_labels": tone_by_ref.get(key, []),
                "style_labels": style_by_ref.get(key, []),
            }
        )

    return {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "variant_id": variant_id,
        "anchor_context": anchor_ctx,
        "rows": rows,
    }


__all__ = [
    "AnchorPoolError",
    "AnchorPoolSourceType",
    "active_anchor_context",
    "add_pool_item",
    "bump_pool_revision",
    "centroid_vectors_for_set",
    "compute_centroid",
    "drop_centroid_cache",
    "list_tagger_texts",
    "pool_items_for_set",
    "remove_pool_item",
    "resolve_active_anchor_set_ids",
]
