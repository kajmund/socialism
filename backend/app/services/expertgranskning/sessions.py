"""Create and manage generic_panel sessions for free-text expert review."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import PanelSession, Persona, Population, Projekt
from app.serializers import format_date
from app.services.expertgranskning import MODULE_ID
from app.services.expertgranskning.schemas import (
    ExpertgranskningSessionCreate,
    ExpertgranskningSessionOut,
    ExpertgranskningSessionSummary,
    ExpertgranskningSessionUpdate,
)
from app.services.kund_store import default_os_project_id, require_default_project_id
from app.services.panel.expert_slots import (
    load_expert_slots_from_population,
    require_expert_panel,
    require_project,
)
from app.services.panel.schemas import PanelSessionConfig, PanelSessionCreate
from app.services.panel.sessions import (
    create_panel_session,
    get_panel_session,
    new_panel_session_id,
)


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


def is_expertgranskning_session(row: PanelSession) -> bool:
    config = row.config if isinstance(row.config, dict) else {}
    return row.protocol == "generic_panel" and config.get("module") == MODULE_ID


def serialize_expertgranskning_session(
    row: PanelSession,
    *,
    panel_name: str | None = None,
) -> ExpertgranskningSessionOut:
    config = row.config if isinstance(row.config, dict) else {}
    return ExpertgranskningSessionOut(
        id=row.id,
        protocol=row.protocol,
        status=row.status,  # type: ignore[arg-type]
        module=str(config.get("module") or MODULE_ID),
        topic=str(config.get("topic") or ""),
        document_text=document_text_from_config(config),
        panel_id=row.panel_id,
        panel_name=panel_name,
        project_id=row.project_id,
        job_id=row.job_id,
        error=row.error,
        created_at=format_date(row.created_at) if row.created_at else "",
        updated_at=format_date(row.updated_at) if row.updated_at else "",
    )


def serialize_expertgranskning_summary(
    row: PanelSession,
    *,
    panel_name: str | None = None,
) -> ExpertgranskningSessionSummary:
    config = row.config if isinstance(row.config, dict) else {}
    return ExpertgranskningSessionSummary(
        id=row.id,
        topic=str(config.get("topic") or "Expertgranskning"),
        status=row.status,  # type: ignore[arg-type]
        panel_id=row.panel_id,
        panel_name=panel_name,
        job_id=row.job_id,
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
    panel_id: int | None,
    project_id: int | None,
    user_customer_id: int | None,
    is_admin: bool,
) -> int:
    if not is_admin:
        if user_customer_id is None:
            raise PermissionError("kund_access_denied")
        if panel_id is not None:
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
    if panel_id is not None:
        panel_customer_id = await customer_id_for_expert_panel(session, panel_id)
        if panel_customer_id is not None:
            return panel_customer_id
    projekt = await session.get(Projekt, await default_os_project_id(session))
    if projekt is None:
        raise RuntimeError("Default OS project missing")
    return projekt.customer_id


async def _panel_name(session: AsyncSession, panel_id: int | None) -> str | None:
    if panel_id is None:
        return None
    population = await session.get(Population, panel_id)
    return None if population is None else population.name


async def _create_draft_without_panel(
    session: AsyncSession,
    *,
    topic: str,
    document_text: str,
    project_id: int,
) -> PanelSession:
    config = PanelSessionConfig(
        protocol="generic_panel",
        module=MODULE_ID,
        topic=topic,
        brief=document_text,
        expert_slots=[],
    )
    row = PanelSession(
        id=new_panel_session_id(),
        protocol="generic_panel",
        status="draft",
        config=config.model_dump(mode="json"),
        transcript=[],
        scratchpads={},
        analysis=None,
        panel_id=None,
        project_id=project_id,
        campaign_id=None,
        job_id=None,
        error=None,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


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
    if body.panel_id is None:
        row = await _create_draft_without_panel(
            session,
            topic=topic,
            document_text=body.document_text,
            project_id=project_id,
        )
    else:
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
    panel_name = await _panel_name(session, row.panel_id)
    return serialize_expertgranskning_session(row, panel_name=panel_name)


async def list_expertgranskning_sessions(
    session: AsyncSession,
    *,
    customer_id: int | None,
) -> list[ExpertgranskningSessionSummary]:
    stmt = (
        select(PanelSession, Population.name)
        .outerjoin(Population, Population.id == PanelSession.panel_id)
        .where(PanelSession.protocol == "generic_panel")
        .order_by(PanelSession.updated_at.desc())
    )
    if customer_id is not None:
        stmt = stmt.join(Projekt, Projekt.id == PanelSession.project_id).where(
            Projekt.customer_id == customer_id
        )
    result = await session.execute(stmt)
    out: list[ExpertgranskningSessionSummary] = []
    for row, panel_name in result.all():
        if not is_expertgranskning_session(row):
            continue
        out.append(serialize_expertgranskning_summary(row, panel_name=panel_name))
    return out


async def update_expertgranskning_session(
    session: AsyncSession,
    row: PanelSession,
    body: ExpertgranskningSessionUpdate,
    *,
    customer_id: int,
) -> ExpertgranskningSessionOut:
    if row.status in {"pending", "running"}:
        raise RuntimeError("Cannot edit a running session")

    config = dict(row.config) if isinstance(row.config, dict) else {}
    document_text = (
        body.document_text
        if body.document_text is not None
        else document_text_from_config(config)
    )
    if body.title is not None:
        topic = topic_from_document(body.title, document_text)
    else:
        existing_topic = str(config.get("topic") or "").strip()
        topic = existing_topic or topic_from_document("", document_text)

    panel_id = row.panel_id
    if body.clear_panel:
        panel_id = None
    elif body.panel_id is not None:
        panel_id = body.panel_id

    if panel_id is not None:
        panel_customer_id = await customer_id_for_expert_panel(session, panel_id)
        if panel_customer_id is not None and panel_customer_id != customer_id:
            raise PermissionError("kund_access_denied")

    project_id = row.project_id
    if body.project_id is not None:
        project_id = await resolve_project_id(
            session,
            customer_id=customer_id,
            project_id=body.project_id,
        )

    expert_slots = config.get("expert_slots") or []
    if panel_id is None:
        expert_slots = []
    elif body.panel_id is not None or body.clear_panel or not expert_slots:
        slots = await load_expert_slots_from_population(session, panel_id)
        expert_slots = [slot.model_dump(mode="json") for slot in slots]

    config.update(
        {
            "protocol": "generic_panel",
            "module": MODULE_ID,
            "topic": topic,
            "brief": document_text,
            "expert_slots": expert_slots,
        }
    )
    row.config = config
    row.panel_id = panel_id
    row.project_id = project_id
    if panel_id is None:
        row.scratchpads = {}
    else:
        row.scratchpads = {
            str(slot.get("slot_id") or slot.get("id") or ""): ""
            for slot in expert_slots
            if isinstance(slot, dict)
        }
    # Reset failed runs back to draft so they can be reconfigured and re-run.
    if row.status == "failed":
        row.status = "draft"
        row.error = None
    await session.flush()
    await session.refresh(row)
    panel_name = await _panel_name(session, row.panel_id)
    return serialize_expertgranskning_session(row, panel_name=panel_name)


async def delete_expertgranskning_session(session: AsyncSession, row: PanelSession) -> None:
    if row.status in {"pending", "running"}:
        raise RuntimeError("Cannot delete a running session")
    await session.delete(row)
    await session.flush()


async def prepare_session_for_run(session: AsyncSession, row: PanelSession) -> None:
    """Validate and hydrate expert slots before enqueueing a run."""
    config = dict(row.config) if isinstance(row.config, dict) else {}
    document_text = document_text_from_config(config)
    if not document_text:
        raise ValueError("document_text is required to run")
    if row.panel_id is None:
        raise ValueError("panel_id is required to run")
    slots = config.get("expert_slots") or []
    if not slots:
        loaded = await load_expert_slots_from_population(session, row.panel_id)
        config["expert_slots"] = [slot.model_dump(mode="json") for slot in loaded]
        row.config = config
        row.scratchpads = {slot.slot_id: "" for slot in loaded}
        await session.flush()


async def get_expertgranskning_session_out(
    session: AsyncSession,
    row: PanelSession,
) -> ExpertgranskningSessionOut:
    panel_name = await _panel_name(session, row.panel_id)
    return serialize_expertgranskning_session(row, panel_name=panel_name)
