"""Materialize authenticated job snapshots before writing to the socket."""

from fastapi import WebSocket

from app.database.models import UserAccount
from app.services import jobs
from app.services.workspace_api_scope import visible_workspace_jobs


async def send_jobs_snapshot(websocket: WebSocket, user: UserAccount, *, customer_id: int | None) -> None:
    async with jobs.job_session_factory()() as session:
        rows = await jobs.list_jobs(session, limit=50, customer_id=customer_id)
        rows = await visible_workspace_jobs(session, user, rows)
        snapshot = {"type": "jobs.snapshot", "jobs": [jobs.serialize_job(row).model_dump(mode="json")
                    for row in rows]}
    await websocket.send_json(snapshot)
