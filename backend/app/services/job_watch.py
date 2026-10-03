"""Materialize authenticated job snapshots before writing to the socket."""

from fastapi import WebSocket

from app.auth.scope import job_visible_to_user
from app.database.models import UserAccount
from app.services import jobs


async def send_jobs_snapshot(websocket: WebSocket, user: UserAccount, *, customer_id: int | None) -> None:
    async with jobs.job_session_factory()() as session:
        rows = await jobs.list_jobs(session, limit=50, customer_id=customer_id)
        snapshot = {"type": "jobs.snapshot", "jobs": [jobs.serialize_job(row).model_dump(mode="json")
                    for row in rows if job_visible_to_user(user, row)]}
    await websocket.send_json(snapshot)
