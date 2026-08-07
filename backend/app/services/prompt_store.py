"""Load active prompt configurations from the database."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Configuration
from app.serializers import utcnow
from app.services.prompt_catalog import (
    PROMPT_KEYS,
    ConfigurationLanguage,
    default_prompts,
    normalize_prompts,
    render_prompt,
)


class MissingActiveConfigurationError(RuntimeError):
    """Raised when no active configuration exists."""


async def get_active_configuration(session: AsyncSession) -> Configuration | None:
    stmt = (
        select(Configuration)
        .where(Configuration.is_active.is_(True))
        .order_by(Configuration.id.asc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def require_active_prompts(session: AsyncSession) -> dict[str, str]:
    from app.services.prompt_catalog import (
        default_prompts,
        refresh_ssr_classify_prompts,
    )

    row = await get_active_configuration(session)
    if row is None:
        raise MissingActiveConfigurationError(
            "No active prompt configuration. Activate one under Konfigurationer."
        )
    language: ConfigurationLanguage = row.language  # type: ignore[assignment]
    stored = dict(row.prompts or {})
    defaults = default_prompts(language)
    changed = False

    tone_key = "report.classify.tones.system"
    refreshed = refresh_ssr_classify_prompts(stored, language=language)
    if refreshed.get(tone_key) != stored.get(tone_key):
        stored[tone_key] = refreshed[tone_key]
        changed = True

    style_key = "report.classify.styles.system"
    if not str(stored.get(style_key, "")).strip():
        stored[style_key] = defaults[style_key]
        changed = True

    if changed:
        row.prompts = stored
        row.updated_at = utcnow()
        await session.commit()
        await session.refresh(row)

    prompts = normalize_prompts(stored, language=language, fill_missing=False)
    missing = [k for k in PROMPT_KEYS if not str(prompts.get(k, "")).strip()]
    if missing:
        raise MissingActiveConfigurationError(
            f"Active configuration '{row.name}' (id={row.id}) is missing prompts: "
            + ", ".join(missing[:8])
            + ("…" if len(missing) > 8 else "")
        )
    return prompts


async def ensure_default_configurations(session: AsyncSession) -> int:
    """Seed Standard configs for sv/en and backfill incomplete prompt maps.

    Exactly one configuration may be active globally. New seeds activate Swedish
    by default; English is inactive until chosen.
    """
    changed = 0
    for language, name, activate in (
        ("sv", "Standard (svenska)", True),
        ("en", "Standard (English)", False),
    ):
        result = await session.execute(
            select(Configuration).where(Configuration.language == language)
        )
        rows = list(result.scalars().all())
        if not rows:
            now = utcnow()
            session.add(
                Configuration(
                    name=name,
                    language=language,
                    prompts=default_prompts(language),  # type: ignore[arg-type]
                    is_active=activate,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed += 1
            continue
        for row in rows:
            merged = normalize_prompts(dict(row.prompts or {}), language=language, fill_missing=True)
            if merged != dict(row.prompts or {}):
                row.prompts = merged
                row.updated_at = utcnow()
                changed += 1

    # Enforce a single global active configuration.
    all_result = await session.execute(select(Configuration).order_by(Configuration.id.asc()))
    all_rows = list(all_result.scalars().all())
    if all_rows:
        active = [r for r in all_rows if r.is_active]
        if not active:
            preferred = next((r for r in all_rows if r.language == "sv"), all_rows[0])
            preferred.is_active = True
            preferred.updated_at = utcnow()
            if not preferred.prompts:
                preferred.prompts = default_prompts(preferred.language)  # type: ignore[arg-type]
            changed += 1
        elif len(active) > 1:
            keep = next((r for r in active if r.language == "sv"), active[0])
            for row in active:
                if row.id != keep.id:
                    row.is_active = False
                    row.updated_at = utcnow()
                    changed += 1

    if changed:
        await session.commit()

    # Deferred import: catalog_store must not import prompt_store at module load.
    from app.services.catalog_store import ensure_catalogs_for_all_configurations

    catalog_added = await ensure_catalogs_for_all_configurations(session)
    return changed + catalog_added


async def set_active_configuration(
    session: AsyncSession,
    configuration_id: int,
) -> Configuration:
    row = await session.get(Configuration, configuration_id)
    if row is None:
        raise LookupError("Configuration not found")
    others = await session.execute(
        select(Configuration).where(
            Configuration.id != row.id,
            Configuration.is_active.is_(True),
        )
    )
    for other in others.scalars().all():
        other.is_active = False
    row.is_active = True
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(row)
    return row


__all__ = [
    "MissingActiveConfigurationError",
    "ensure_default_configurations",
    "get_active_configuration",
    "render_prompt",
    "require_active_prompts",
    "set_active_configuration",
]
