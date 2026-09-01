"""Load scoped prompts and the global active configuration (SSR / anchors / thresholds)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Configuration, Persona
from app.services.kund_store import default_os_customer_id, ensure_default_kunder
from app.schemas.domain import DEFAULT_SSR_TEMPERATURE
from app.serializers import utcnow
from app.services.prompt_catalog import (
    ConfigurationLanguage,
    render_prompt,
)
from app.services.prompt_fields_store import (
    MissingPromptCatalogError,
    MissingPromptCustomerError,
    filled_prompts,
)
from app.services.report.thresholds import (
    ReportThresholds,
    default_report_thresholds,
    normalize_report_thresholds,
    report_thresholds_to_dict,
)


class MissingActiveConfigurationError(RuntimeError):
    """Raised when no active configuration exists."""


def module_for_persona_kind(kind: str) -> str:
    return "dd" if kind == "expert" else "politik"


def module_for_population_kind(kind: str) -> str:
    return "dd" if kind == "expert_panel" else "politik"


async def get_active_configuration(session: AsyncSession) -> Configuration | None:
    stmt = (
        select(Configuration)
        .where(Configuration.is_active.is_(True))
        .order_by(Configuration.id.asc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def require_active_prompts(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
    language: str,
) -> dict[str, str]:
    """Load catalog defaults for ``module`` overlaid with this customer's overrides.

    Activate no longer selects prompt text. One live set per customer × language.
    Does not read or write ``Configuration.prompts``.
    """
    return await filled_prompts(
        session,
        customer_id=customer_id,
        language=language,
        module=module,
    )


async def require_prompts_for_language(
    session: AsyncSession,
    language: ConfigurationLanguage,
    *,
    customer_id: int,
    module: str,
) -> dict[str, str]:
    return await require_active_prompts(
        session,
        customer_id=customer_id,
        module=module,
        language=language,
    )


async def require_prompts_for_persona(
    session: AsyncSession,
    persona: Persona,
    *,
    language: str = "sv",
) -> dict[str, str]:
    return await require_active_prompts(
        session,
        customer_id=persona.customer_id,
        module=module_for_persona_kind(persona.kind),
        language=language,
    )


async def require_active_ssr_temperature(session: AsyncSession) -> float:
    """SSR softmax temperature from the active configuration (fail loud if missing)."""
    row = await get_active_configuration(session)
    if row is None:
        raise MissingActiveConfigurationError(
            "No active prompt configuration. Activate one under Konfigurationer."
        )
    temp = float(row.ssr_temperature)
    if temp <= 0.0:
        raise MissingActiveConfigurationError(
            f"Active configuration '{row.name}' (id={row.id}) has invalid "
            f"ssr_temperature={temp!r} (must be > 0)"
        )
    return temp


async def require_active_report_thresholds(session: AsyncSession) -> ReportThresholds:
    """Snabbrapport verdict/recommendation thresholds from active configuration."""
    row = await get_active_configuration(session)
    if row is None:
        raise MissingActiveConfigurationError(
            "No active prompt configuration. Activate one under Konfigurationer."
        )
    try:
        return normalize_report_thresholds(dict(row.report_thresholds or {}))
    except ValueError as exc:
        raise MissingActiveConfigurationError(
            f"Active configuration '{row.name}' (id={row.id}) has invalid "
            f"report_thresholds: {exc}"
        ) from exc


def _backfill_report_thresholds(row: Configuration) -> bool:
    raw = dict(row.report_thresholds or {})
    if raw:
        try:
            normalize_report_thresholds(raw)
            return False
        except ValueError:
            pass
    row.report_thresholds = report_thresholds_to_dict(default_report_thresholds())
    row.updated_at = utcnow()
    return True


async def ensure_default_configurations(session: AsyncSession) -> int:
    """Seed Standard configs for sv/en. Prompt text lives in prompt_fields / overrides.

    Exactly one configuration may be active globally. New seeds activate Swedish
    by default; English is inactive until chosen. ``Configuration.prompts`` is
    left empty — runtime no longer reads it.
    """
    changed = 0
    from app.services.anchor_store import (
        backfill_configuration_anchor_sets,
        default_anchor_refs,
        ensure_default_anchor_sets,
    )

    await ensure_default_kunder(session)
    await ensure_default_anchor_sets(session)
    default_refs = await default_anchor_refs(session)
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
            customer_id = await default_os_customer_id(session)
            session.add(
                Configuration(
                    customer_id=customer_id,
                    name=name,
                    language=language,
                    prompts={},
                    ssr_temperature=DEFAULT_SSR_TEMPERATURE,
                    report_thresholds=report_thresholds_to_dict(default_report_thresholds()),
                    anchor_sets=default_refs,
                    is_active=activate,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed += 1
            continue
        for row in rows:
            if _backfill_report_thresholds(row):
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

    backfill_changed = await backfill_configuration_anchor_sets(session)

    # Deferred import: catalog_store must not import prompt_store at module load.
    from app.services.catalog_store import ensure_catalogs_for_all_configurations

    catalog_added = await ensure_catalogs_for_all_configurations(session)
    return changed + backfill_changed + catalog_added


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
    "MissingPromptCatalogError",
    "MissingPromptCustomerError",
    "ensure_default_configurations",
    "get_active_configuration",
    "module_for_persona_kind",
    "module_for_population_kind",
    "render_prompt",
    "require_active_prompts",
    "require_active_report_thresholds",
    "require_active_ssr_temperature",
    "require_prompts_for_language",
    "require_prompts_for_persona",
    "set_active_configuration",
]
