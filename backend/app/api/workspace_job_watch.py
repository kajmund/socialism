"""Personal job snapshots and membership-checked realtime delivery."""

import logging
from typing import Literal

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from app.auth.scope import effective_customer_id
from app.realtime.hub import job_hub
from app.services import jobs as jobs_service
from app.services.workspace_api_scope import visible_workspace_jobs
from app.services.workspace_ws_scope import workspace_event_authorizer

logger = logging.getLogger(__name__)


class JobsWatchHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["jobs_watch"]
    customer_id: int | None = None


async def watch_workspace_jobs(
    websocket: WebSocket, *, authenticate, send_error, close_auth_error
) -> None:
    await websocket.accept()
    user = await authenticate(websocket)
    if user is None:
        return
    try:
        raw = await websocket.receive_json()
        if not isinstance(raw, dict):
            await send_error(websocket, "Expected JSON object")
            await websocket.close(code=1003)
            return
        try:
            hello = JobsWatchHello.model_validate(raw)
            customer_id = effective_customer_id(user, hello.customer_id)
        except ValidationError as exc:
            await send_error(websocket, str(exc.errors()[0]["msg"]))
            await websocket.close(code=1003)
            return
        except HTTPException as exc:
            await close_auth_error(websocket, exc)
            return
        factory = jobs_service.job_session_factory()
        await job_hub.subscribe(
            websocket,
            customer_id=customer_id,
            authorize=workspace_event_authorizer(factory, user.id),
        )
        async with factory() as session:
            rows = await jobs_service.list_jobs(session, limit=50, customer_id=customer_id)
            rows = await visible_workspace_jobs(session, user, rows)
            snapshot = [jobs_service.serialize_job(row).model_dump(mode="json") for row in rows]
        await websocket.send_json({"type": "jobs.snapshot", "jobs": snapshot})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Jobs watch WebSocket failed")
        await send_error(websocket, "WebSocket error")
        try:
            await websocket.close(code=1011)
        except (WebSocketDisconnect, RuntimeError):
            pass
    finally:
        await job_hub.unsubscribe(websocket)
