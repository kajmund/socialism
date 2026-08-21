"""Persist Spinndoktor board widgets per report."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import SpindoctorWidget
from app.schemas.domain import SpindoctorWidgetOut

_GRID_ORIGIN = (80.0, 80.0)
_GRID_STEP = (48.0, 56.0)
_NODE_WIDTH = 320.0
_ROW_HEIGHT = 220.0


def cascade_position(index: int) -> tuple[float, float]:
    col = index % 4
    row = index // 4
    return (
        _GRID_ORIGIN[0] + col * (_NODE_WIDTH + _GRID_STEP[0]),
        _GRID_ORIGIN[1] + row * (_ROW_HEIGHT + _GRID_STEP[1]),
    )


def serialize_spindoctor_widget(row: SpindoctorWidget) -> SpindoctorWidgetOut:
    payload = dict(row.data) if isinstance(row.data, dict) else {}
    payload["id"] = row.id
    payload["kind"] = row.kind
    payload["title"] = row.title
    payload["pos_x"] = row.pos_x
    payload["pos_y"] = row.pos_y
    return SpindoctorWidgetOut.model_validate(payload)


async def list_spindoctor_widgets(
    session: AsyncSession,
    report_id: str,
) -> list[SpindoctorWidgetOut]:
    stmt = (
        select(SpindoctorWidget)
        .where(SpindoctorWidget.report_id == report_id)
        .order_by(SpindoctorWidget.created_at.asc(), SpindoctorWidget.id.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [serialize_spindoctor_widget(row) for row in rows]


async def save_spindoctor_widget(
    session: AsyncSession,
    report_id: str,
    widget: SpindoctorWidgetOut,
) -> SpindoctorWidgetOut:
    existing = await session.get(SpindoctorWidget, widget.id)
    if existing is not None:
        if existing.report_id != report_id:
            raise ValueError("Widget belongs to another report")
        return serialize_spindoctor_widget(existing)

    count = await session.scalar(
        select(func.count())
        .select_from(SpindoctorWidget)
        .where(SpindoctorWidget.report_id == report_id)
    )
    pos_x, pos_y = cascade_position(int(count or 0))
    data = widget.model_dump()
    data.pop("pos_x", None)
    data.pop("pos_y", None)
    row = SpindoctorWidget(
        id=widget.id,
        report_id=report_id,
        kind=widget.kind,
        title=widget.title,
        data=data,
        pos_x=pos_x,
        pos_y=pos_y,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return serialize_spindoctor_widget(row)


async def update_spindoctor_widget_position(
    session: AsyncSession,
    report_id: str,
    widget_id: str,
    *,
    pos_x: float,
    pos_y: float,
) -> SpindoctorWidgetOut:
    row = await session.get(SpindoctorWidget, widget_id)
    if row is None or row.report_id != report_id:
        raise ValueError("Widget not found")
    row.pos_x = pos_x
    row.pos_y = pos_y
    await session.commit()
    await session.refresh(row)
    return serialize_spindoctor_widget(row)


async def delete_spindoctor_widget(
    session: AsyncSession,
    report_id: str,
    widget_id: str,
) -> None:
    row = await session.get(SpindoctorWidget, widget_id)
    if row is None or row.report_id != report_id:
        raise ValueError("Widget not found")
    await session.delete(row)
    await session.commit()


async def clear_spindoctor_widgets(session: AsyncSession, report_id: str) -> None:
    await session.execute(
        delete(SpindoctorWidget).where(SpindoctorWidget.report_id == report_id)
    )
    await session.commit()
