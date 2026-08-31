"""Named configurations: prompts map + scoped grunddata catalog lists."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_admin
from app.database.models import CatalogList, Configuration
from app.database.session import get_session
from app.schemas.domain import (
    CatalogListOut,
    CatalogListUpdate,
    ConfigurationAnchorSets,
    ConfigurationCreate,
    ConfigurationLanguage,
    ConfigurationOut,
    ConfigurationUpdate,
    PromptCatalogOut,
    PromptFieldOut,
    format_date,
)
from app.serializers import utcnow
from app.services.catalog_defaults import SECTION_ORDER
from app.services.catalog_items import catalog_items_as_json, coerce_catalog_items
from app.services.catalog_store import (
    ensure_catalog_defaults,
    get_catalog_list,
    list_catalog_lists,
)
from app.services.prompt_catalog import (
    PROMPT_FIELDS,
    PROMPT_SECTIONS,
    default_prompts,
    normalize_prompts,
)
from app.services.anchor_store import (
    backfill_configuration_anchor_sets,
    configuration_anchor_sets_out,
    default_anchor_refs,
    ensure_default_anchor_sets,
    validate_configuration_anchor_refs,
)
from app.services.kund_store import default_os_customer_id
from app.services.prompt_fields_store import filled_prompts, replace_prompt_overrides
from app.services.prompt_store import ensure_default_configurations, set_active_configuration
from app.services.report.thresholds import (
    ReportThresholds,
    default_report_thresholds,
    normalize_report_thresholds,
    report_thresholds_to_dict,
)

router = APIRouter(
    prefix="/configurations",
    tags=["configurations"],
    dependencies=[Depends(require_admin)],
)


def _dt(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat()


async def _serialize(
    session: AsyncSession,
    row: Configuration,
    *,
    prompts: dict[str, str] | None = None,
) -> ConfigurationOut:
    language: ConfigurationLanguage = row.language  # type: ignore[assignment]
    if prompts is None:
        prompts = await filled_prompts(
            session,
            customer_id=row.customer_id,
            language=language,
        )
    return ConfigurationOut(
        id=row.id,
        name=row.name,
        language=language,
        prompts=prompts,
        ssr_temperature=float(row.ssr_temperature),
        report_thresholds=normalize_report_thresholds(dict(row.report_thresholds or {})),
        anchor_sets=ConfigurationAnchorSets.model_validate(
            configuration_anchor_sets_out(row.anchor_sets)
        ),
        is_active=bool(row.is_active),
        created_at=_dt(row.created_at),
        updated_at=_dt(row.updated_at),
    )


async def _get_configuration(session: AsyncSession, configuration_id: int) -> Configuration:
    row = await session.get(Configuration, configuration_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return row


async def _deactivate_others(
    session: AsyncSession,
    *,
    keep_id: int | None,
) -> None:
    """Deactivate every active configuration except keep_id (global, not per language)."""
    stmt = select(Configuration).where(Configuration.is_active.is_(True))
    if keep_id is not None:
        stmt = stmt.where(Configuration.id != keep_id)
    result = await session.execute(stmt)
    for row in result.scalars().all():
        row.is_active = False


def _serialize_catalog(row: CatalogList) -> CatalogListOut:
    return CatalogListOut(
        key=row.key,
        section=row.section,  # type: ignore[arg-type]
        title=row.title,
        items=coerce_catalog_items(row.items),
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


def _catalog_sort_key(row: CatalogList) -> tuple[int, str]:
    try:
        section_idx = SECTION_ORDER.index(row.section)
    except ValueError:
        section_idx = len(SECTION_ORDER)
    return (section_idx, row.title)


@router.get("/catalog", response_model=PromptCatalogOut)
async def prompt_catalog(
    language: ConfigurationLanguage = Query(default="sv"),
    label_locale: ConfigurationLanguage = Query(default="sv"),
) -> PromptCatalogOut:
    ui = "en" if label_locale == "en" else "sv"
    fields = [
        PromptFieldOut(
            key=field["key"],
            section=field["section"],
            label=field["label"].get(ui) or field["label"]["sv"],
            hint=field["hint"].get(ui) or field["hint"]["sv"],
            default=field["defaults"].get(language) or field["defaults"]["sv"],
        )
        for field in PROMPT_FIELDS
    ]
    sections = [
        {"id": section_id, "label": labels.get(ui) or labels["sv"]}
        for section_id, labels in PROMPT_SECTIONS
    ]
    return PromptCatalogOut(
        sections=sections,
        fields=fields,
        defaults=default_prompts(language),
    )


@router.get("", response_model=list[ConfigurationOut])
async def list_configurations(
    session: AsyncSession = Depends(get_session),
) -> list[ConfigurationOut]:
    await ensure_default_configurations(session)
    await ensure_default_anchor_sets(session)
    await backfill_configuration_anchor_sets(session)
    stmt = select(Configuration).order_by(
        Configuration.is_active.desc(),
        Configuration.updated_at.desc(),
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    cache: dict[tuple[int, str], dict[str, str]] = {}
    out: list[ConfigurationOut] = []
    for row in rows:
        key = (row.customer_id, str(row.language))
        if key not in cache:
            cache[key] = await filled_prompts(
                session,
                customer_id=row.customer_id,
                language=str(row.language),
            )
        out.append(await _serialize(session, row, prompts=cache[key]))
    return out


@router.get("/{configuration_id}", response_model=ConfigurationOut)
async def get_configuration(
    configuration_id: int,
    session: AsyncSession = Depends(get_session),
) -> ConfigurationOut:
    return await _serialize(session, await _get_configuration(session, configuration_id))


@router.post("", response_model=ConfigurationOut, status_code=201)
async def create_configuration(
    body: ConfigurationCreate,
    session: AsyncSession = Depends(get_session),
) -> ConfigurationOut:
    prompts = normalize_prompts(body.prompts, language=body.language, fill_missing=True)
    await ensure_default_anchor_sets(session)
    anchor_refs = (
        body.anchor_sets.model_dump()
        if body.anchor_sets is not None
        else await default_anchor_refs(session)
    )
    try:
        await validate_configuration_anchor_refs(session, anchor_refs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    now = utcnow()
    if body.is_active:
        await _deactivate_others(session, keep_id=None)
    customer_id = await default_os_customer_id(session)
    row = Configuration(
        customer_id=customer_id,
        name=body.name,
        language=body.language,
        prompts={},
        ssr_temperature=body.ssr_temperature,
        report_thresholds=report_thresholds_to_dict(
            body.report_thresholds
            if body.report_thresholds is not None
            else default_report_thresholds()
        ),
        anchor_sets=anchor_refs,
        is_active=body.is_active,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    await replace_prompt_overrides(
        session,
        customer_id=customer_id,
        language=body.language,
        prompts=prompts,
    )
    await session.commit()
    await session.refresh(row)
    await ensure_catalog_defaults(session, row.id)
    return await _serialize(session, row)


@router.get(
    "/{configuration_id}/catalog",
    response_model=list[CatalogListOut],
)
async def list_configuration_catalog(
    configuration_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[CatalogListOut]:
    await _get_configuration(session, configuration_id)
    await ensure_catalog_defaults(session, configuration_id)
    rows = await list_catalog_lists(session, configuration_id)
    rows.sort(key=_catalog_sort_key)
    return [_serialize_catalog(row) for row in rows]


@router.get(
    "/{configuration_id}/catalog/{key}",
    response_model=CatalogListOut,
)
async def get_configuration_catalog_list(
    configuration_id: int,
    key: str,
    session: AsyncSession = Depends(get_session),
) -> CatalogListOut:
    await _get_configuration(session, configuration_id)
    await ensure_catalog_defaults(session, configuration_id)
    row = await get_catalog_list(session, configuration_id, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Catalog list not found")
    return _serialize_catalog(row)


@router.put(
    "/{configuration_id}/catalog/{key}",
    response_model=CatalogListOut,
)
async def update_configuration_catalog_list(
    configuration_id: int,
    key: str,
    body: CatalogListUpdate,
    session: AsyncSession = Depends(get_session),
) -> CatalogListOut:
    await _get_configuration(session, configuration_id)
    await ensure_catalog_defaults(session, configuration_id)
    row = await get_catalog_list(session, configuration_id, key)
    if row is None:
        raise HTTPException(status_code=404, detail="Catalog list not found")
    row.items = catalog_items_as_json(body.items)
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(row)
    return _serialize_catalog(row)


@router.patch("/{configuration_id}", response_model=ConfigurationOut)
async def update_configuration(
    configuration_id: int,
    body: ConfigurationUpdate,
    session: AsyncSession = Depends(get_session),
) -> ConfigurationOut:
    row = await _get_configuration(session, configuration_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        row.name = data["name"]
    if "language" in data and data["language"] is not None:
        row.language = data["language"]
    language: ConfigurationLanguage = row.language  # type: ignore[assignment]
    if "prompts" in data and data["prompts"] is not None:
        await replace_prompt_overrides(
            session,
            customer_id=row.customer_id,
            language=language,
            prompts=normalize_prompts(
                data["prompts"],
                language=language,
                fill_missing=True,
            ),
        )
    if "ssr_temperature" in data and data["ssr_temperature"] is not None:
        row.ssr_temperature = float(data["ssr_temperature"])
    if "report_thresholds" in data and data["report_thresholds"] is not None:
        rt = data["report_thresholds"]
        parsed = rt if isinstance(rt, ReportThresholds) else ReportThresholds.model_validate(rt)
        row.report_thresholds = report_thresholds_to_dict(parsed)
    if "anchor_sets" in data and data["anchor_sets"] is not None:
        refs = data["anchor_sets"]
        if hasattr(refs, "model_dump"):
            refs = refs.model_dump()
        try:
            await validate_configuration_anchor_refs(session, refs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        row.anchor_sets = refs
    if data.get("is_active") is True:
        await _deactivate_others(session, keep_id=row.id)
        row.is_active = True
    elif data.get("is_active") is False:
        row.is_active = False
    row.updated_at = utcnow()
    await session.commit()
    await session.refresh(row)
    return await _serialize(session, row)


@router.post("/{configuration_id}/activate", response_model=ConfigurationOut)
async def activate_configuration(
    configuration_id: int,
    session: AsyncSession = Depends(get_session),
) -> ConfigurationOut:
    try:
        row = await set_active_configuration(session, configuration_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return await _serialize(session, row)


@router.delete("/{configuration_id}", status_code=204)
async def delete_configuration(
    configuration_id: int,
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await _get_configuration(session, configuration_id)
    await session.delete(row)
    await session.commit()
