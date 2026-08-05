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
    """Raised when no active configuration exists for a language."""


async def get_active_configuration(
    session: AsyncSession,
    language: ConfigurationLanguage,
) -> Configuration | None:
    stmt = (
        select(Configuration)
        .where(Configuration.language == language, Configuration.is_active.is_(True))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def require_active_prompts(
    session: AsyncSession,
    language: ConfigurationLanguage = "sv",
) -> dict[str, str]:
    row = await get_active_configuration(session, language)
    if row is None:
        raise MissingActiveConfigurationError(
            f"No active prompt configuration for language '{language}'. "
            "Activate one under Konfigurationer."
        )
    prompts = normalize_prompts(dict(row.prompts or {}), language=language, fill_missing=False)
    missing = [k for k in PROMPT_KEYS if not str(prompts.get(k, "")).strip()]
    if missing:
        raise MissingActiveConfigurationError(
            f"Active configuration '{row.name}' (id={row.id}) is missing prompts: "
            + ", ".join(missing[:8])
            + ("…" if len(missing) > 8 else "")
        )
    return prompts


async def ensure_default_configurations(session: AsyncSession) -> int:
    """Seed Standard configs for sv/en and backfill incomplete prompt maps."""
    changed = 0
    for language, name in (("sv", "Standard (svenska)"), ("en", "Standard (English)")):
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
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed += 1
            continue
        defaults = default_prompts(language)  # type: ignore[arg-type]
        for row in rows:
            merged = normalize_prompts(dict(row.prompts or {}), language=language, fill_missing=True)
            if merged != dict(row.prompts or {}):
                row.prompts = merged
                row.updated_at = utcnow()
                changed += 1
        if not any(r.is_active for r in rows):
            rows[0].is_active = True
            rows[0].updated_at = utcnow()
            if not rows[0].prompts:
                rows[0].prompts = defaults
            changed += 1
    if changed:
        await session.commit()
    return changed


async def set_active_configuration(
    session: AsyncSession,
    configuration_id: int,
) -> Configuration:
    row = await session.get(Configuration, configuration_id)
    if row is None:
        raise LookupError("Configuration not found")
    others = await session.execute(
        select(Configuration).where(
            Configuration.language == row.language,
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
