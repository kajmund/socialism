"""Load active prompt configurations from the database."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.database.models import Configuration
from app.services.kund_store import default_os_customer_id, ensure_default_kunder
from app.schemas.domain import DEFAULT_SSR_TEMPERATURE
from app.serializers import utcnow
from app.services.prompt_catalog import (
    ConfigurationLanguage,
    default_prompts,
    normalize_prompts,
    render_prompt,
)
from app.services.report.thresholds import (
    ReportThresholds,
    default_report_thresholds,
    normalize_report_thresholds,
    report_thresholds_to_dict,
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


def _filled_prompts(row: Configuration) -> dict[str, str]:
    language: ConfigurationLanguage = row.language  # type: ignore[assignment]
    return normalize_prompts(dict(row.prompts or {}), language=language, fill_missing=True)


_SPINNDOCTOR_PROMPT_KEYS = (
    "spinndoctor.system",
    "spinndoctor.system.tools",
    "spinndoctor.system.widgets",
)

# Stock phrasing from the previous cautious catalog. Custom text without
# these markers is left alone.
_STALE_SPINNDOCTOR_MARKERS = (
    "hämtar du med verktyg när du behöver dem",
    "Svara kort om möjligt, utveckla när användaren ber om det",
    "Anropa dem när frågan kräver",
    "Anropa inte i onödan",
    "Du kan lägga saker på arbetsytan med render_chart",
    "with tools when needed",
    "Keep answers short unless the user asks for depth",
    "Call them when the question needs",
    "Do not call tools if",
    "You can place items on the workspace with render_chart",
)


def _refresh_stale_spindoctor_prompts(row: Configuration) -> bool:
    """Replace stock cautious Spinndoktor prompts with the current catalog."""
    language: ConfigurationLanguage = row.language  # type: ignore[assignment]
    defaults = default_prompts(language)
    stored = dict(row.prompts or {})
    changed = False
    for key in _SPINNDOCTOR_PROMPT_KEYS:
        current = stored.get(key) or ""
        if any(marker in current for marker in _STALE_SPINNDOCTOR_MARKERS):
            stored[key] = defaults[key]
            changed = True
    if not changed:
        return False
    row.prompts = stored
    flag_modified(row, "prompts")
    row.updated_at = utcnow()
    return True


def _sync_stored_prompts(row: Configuration) -> bool:
    """Fill missing catalog keys and refresh stale Spinndoktor stock text."""
    changed = _merge_missing_catalog_prompts(row)
    return _refresh_stale_spindoctor_prompts(row) or changed


def _merge_missing_catalog_prompts(row: Configuration) -> bool:
    """Persist new catalog keys into a stored config. Returns True if row changed."""
    before = dict(row.prompts or {})
    merged = _filled_prompts(row)
    if merged == before:
        return False
    row.prompts = merged
    flag_modified(row, "prompts")
    row.updated_at = utcnow()
    return True


async def require_active_prompts(session: AsyncSession) -> dict[str, str]:
    row = await get_active_configuration(session)
    if row is None:
        raise MissingActiveConfigurationError(
            "No active prompt configuration. Activate one under Konfigurationer."
        )
    if _sync_stored_prompts(row):
        await session.commit()
        await session.refresh(row)

    return _filled_prompts(row)


async def require_prompts_for_language(
    session: AsyncSession,
    language: ConfigurationLanguage,
) -> dict[str, str]:
    """Load prompts from the active configuration when its language matches.

    Fails loud if there is no active configuration or it uses another language —
    never falls back to an inactive config of the requested language.
    Missing catalog keys are backfilled from defaults and persisted.
    """
    row = await get_active_configuration(session)
    if row is None:
        raise MissingActiveConfigurationError(
            "No active prompt configuration. Activate one under Konfigurationer."
        )
    if row.language != language:
        raise MissingActiveConfigurationError(
            f"Active configuration '{row.name}' (id={row.id}) is language "
            f"'{row.language}', but '{language}' prompts were required. "
            f"Activate a {language} configuration under Konfigurationer."
        )
    if _sync_stored_prompts(row):
        await session.commit()
        await session.refresh(row)
    return _filled_prompts(row)

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
    """Seed Standard configs for sv/en and backfill incomplete prompt maps.

    Exactly one configuration may be active globally. New seeds activate Swedish
    by default; English is inactive until chosen.
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
                    prompts=default_prompts(language),  # type: ignore[arg-type]
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
            merged = normalize_prompts(dict(row.prompts or {}), language=language, fill_missing=True)
            if merged != dict(row.prompts or {}):
                row.prompts = merged
                flag_modified(row, "prompts")
                row.updated_at = utcnow()
                changed += 1
            if _refresh_stale_spindoctor_prompts(row):
                changed += 1
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
    "ensure_default_configurations",
    "get_active_configuration",
    "render_prompt",
    "require_active_prompts",
    "require_active_report_thresholds",
    "require_active_ssr_temperature",
    "require_prompts_for_language",
    "set_active_configuration",
]
