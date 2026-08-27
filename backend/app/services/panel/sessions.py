"""Panel session persistence."""

from __future__ import annotations

import secrets

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession
from app.serializers import format_date
from app.services.panel.schemas import (
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
    return PanelSessionOut(
        id=row.id,
        protocol=row.protocol,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        config=PanelSessionConfig.model_validate(config_raw),
        transcript=[PanelTurn.model_validate(t) for t in transcript_raw],
        scratchpads={str(k): str(v) for k, v in scratchpads_raw.items()},
        analysis=row.analysis,
        campaign_id=row.campaign_id,
        job_id=row.job_id,
        error=row.error,
        created_at=format_date(row.created_at) if row.created_at else "",
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


async def create_panel_session(session: AsyncSession, body: PanelSessionCreate) -> PanelSessionOut:
    config = body.config
    row = PanelSession(
        id=new_panel_session_id(),
        protocol=config.protocol,
        status="draft",
        config=config.model_dump(mode="json"),
        transcript=[],
        scratchpads={slot.slot_id: "" for slot in config.expert_slots},
        analysis=None,
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
