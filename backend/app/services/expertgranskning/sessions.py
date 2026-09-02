"""Create generic_panel sessions from free-text documents and saved expert panels."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession, Persona, Projekt
from app.serializers import format_date
from app.services.expertgranskning import MODULE_ID
from app.services.expertgranskning.schemas import (
    ExpertgranskningSessionCreate,
    ExpertgranskningSessionOut,
)
from app.services.kund_store import default_os_project_id, require_default_project_id
from app.services.panel.expert_slots import require_expert_panel, require_project
from app.services.panel.schemas import PanelSessionConfig, PanelSessionCreate
from app.services.panel.sessions import create_panel_session, get_panel_session


def topic_from_document(title: str, document_text: str) -> str:
    if title.strip():
        return title.strip()[:4000]
    first_line = next(
        (line.strip() for line in document_text.splitlines() if line.strip()),
        "",
    )
    return (first_line or "Expertgranskning")[:4000]


def document_text_from_config(config: dict) -> str:
    return str(config.get("brief") or "").strip()


def serialize_expertgranskning_session(row: PanelSession) -> ExpertgranskningSessionOut:
    config = row.config if isinstance(row.config, dict) else {}
    return ExpertgranskningSessionOut(
        id=row.id,
        protocol=row.protocol,
        status=row.status,  # type: ignore[arg-type]
        module=str(config.get("module") or MODULE_ID),
        topic=str(config.get("topic") or ""),
        document_text=document_text_from_config(config),
        panel_id=row.panel_id,
        project_id=row.project_id,
        job_id=row.job_id,
        error=row.error,
        created_at=format_date(row.created_at) if row.created_at else "",
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


async def customer_id_for_expert_panel(session: AsyncSession, panel_id: int) -> int | None:
    population = await require_expert_panel(session, panel_id)
    persona_ids = [member.persona_id for member in population.members if member.persona_id]
    if not persona_ids:
        return None
    result = await session.execute(select(Persona).where(Persona.id.in_(persona_ids)))
    customer_ids = {row.customer_id for row in result.scalars().all()}
    if len(customer_ids) == 1:
        return next(iter(customer_ids))
    return None


async def resolve_project_id(
    session: AsyncSession,
    *,
    customer_id: int,
    project_id: int | None,
) -> int:
    if project_id is not None:
        projekt = await require_project(session, project_id)
        if projekt.customer_id != customer_id:
            raise ValueError("project_id does not belong to this customer")
        return projekt.id
    return await require_default_project_id(session, customer_id)


async def resolve_customer_id(
    session: AsyncSession,
    *,
    panel_id: int,
    project_id: int | None,
    user_customer_id: int | None,
    is_admin: bool,
) -> int:
    if not is_admin:
        if user_customer_id is None:
            raise PermissionError("kund_access_denied")
        panel_customer_id = await customer_id_for_expert_panel(session, panel_id)
        if panel_customer_id != user_customer_id:
            raise PermissionError("kund_access_denied")
        if project_id is not None:
            projekt = await require_project(session, project_id)
            if projekt.customer_id != user_customer_id:
                raise PermissionError("kund_access_denied")
        return user_customer_id
    if project_id is not None:
        projekt = await require_project(session, project_id)
        return projekt.customer_id
    panel_customer_id = await customer_id_for_expert_panel(session, panel_id)
    if panel_customer_id is not None:
        return panel_customer_id
    projekt = await session.get(Projekt, await default_os_project_id(session))
    if projekt is None:
        raise RuntimeError("Default OS project missing")
    return projekt.customer_id


async def create_expertgranskning_session(
    session: AsyncSession,
    body: ExpertgranskningSessionCreate,
    *,
    customer_id: int,
) -> ExpertgranskningSessionOut:
    project_id = await resolve_project_id(
        session,
        customer_id=customer_id,
        project_id=body.project_id,
    )
    topic = topic_from_document(body.title, body.document_text)
    created = await create_panel_session(
        session,
        PanelSessionCreate(
            config=PanelSessionConfig(
                protocol="generic_panel",
                module=MODULE_ID,
                topic=topic,
                brief=body.document_text,
            ),
            panel_id=body.panel_id,
            project_id=project_id,
        ),
    )
    row = await get_panel_session(session, created.id)
    if row is None:
        raise RuntimeError(f"Panel session disappeared after create: {created.id}")
    return serialize_expertgranskning_session(row)


def is_expertgranskning_session(row: PanelSession) -> bool:
    config = row.config if isinstance(row.config, dict) else {}
    return row.protocol == "generic_panel" and config.get("module") == MODULE_ID
