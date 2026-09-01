"""Panel session persistence."""

from __future__ import annotations

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession
from app.serializers import format_date
from app.services.panel.expert_slots import (
    load_expert_slots_from_population,
    require_expert_panel,
    require_project,
)
from app.services.panel.result import dd_panel_result_from_stored
from app.services.panel.schemas import (
    DdPanelResult,
    PanelSessionConfig,
    PanelSessionCreate,
    PanelSessionOut,
    PanelTurn,
)


def new_panel_session_id() -> str:
    return f"panel_{secrets.token_hex(8)}"


def serialize_panel_session(row: PanelSession) -> PanelSessionOut:
    config_raw = row.config if isinstance(row.config, dict) else {}
    transcript_raw = row.transcript if isinstance(row.transcript, list) else []
    scratchpads_raw = row.scratchpads if isinstance(row.scratchpads, dict) else {}
    result_raw = row.result if isinstance(row.result, dict) else None
    result: DdPanelResult | None = None
    if result_raw and row.protocol == "dd_panel":
        result = dd_panel_result_from_stored(result_raw)
    return PanelSessionOut(
        id=row.id,
        protocol=row.protocol,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        config=PanelSessionConfig.model_validate(config_raw),
        transcript=[PanelTurn.model_validate(t) for t in transcript_raw],
        scratchpads={str(k): str(v) for k, v in scratchpads_raw.items()},
        analysis=row.analysis,
        result=result,
        panel_id=row.panel_id,
        project_id=row.project_id,
        campaign_id=row.campaign_id,
        job_id=row.job_id,
        error=row.error,
        created_at=format_date(row.created_at) if row.created_at else "",
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


async def create_panel_session(session: AsyncSession, body: PanelSessionCreate) -> PanelSessionOut:
    config = body.config
    if body.panel_id is not None:
        if config.expert_slots:
            await require_expert_panel(session, body.panel_id)
        else:
            slots = await load_expert_slots_from_population(session, body.panel_id)
            config = config.model_copy(
                update={
                    "expert_slots": slots,
                    "expert_role_keys": config.expert_role_keys or [slot.slot_id for slot in slots],
                }
            )
    if body.project_id is not None:
        await require_project(session, body.project_id)
    row = PanelSession(
        id=new_panel_session_id(),
        protocol=config.protocol,
        status="draft",
        config=config.model_dump(mode="json"),
        transcript=[],
        scratchpads={slot.slot_id: "" for slot in config.expert_slots},
        analysis=None,
        panel_id=body.panel_id,
        project_id=body.project_id,
        campaign_id=config.campaign_id,
        job_id=None,
        error=None,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return serialize_panel_session(row)


async def get_panel_session(session: AsyncSession, session_id: str) -> PanelSession | None:
    return await session.get(PanelSession, session_id)
