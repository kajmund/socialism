"""Authorized research replay and membership-checked realtime delivery."""

import logging
from typing import Literal

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.auth.scope import assert_kund_access
from app.database.models import ExecutionAttempt, ExecutionRun
from app.realtime.research_progress_broadcast import research_progress_broadcast
from app.services import jobs as jobs_service
from app.services.research.progress import list_research_progress_events, progress_event_to_dict
from app.services.workspace_api_scope import require_context_workspace, require_execution_attempt
from app.services.workspace_ws_scope import workspace_event_authorizer

logger = logging.getLogger(__name__)


class ResearchWatchHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["research_watch"]
    attempt_id: str = Field(min_length=1)
    after_sequence: int = Field(default=0, ge=0)


class _MissingAttempt(Exception):
    pass


async def _authorized_attempt_id(factory, user, attempt_id: str) -> str:
    async with factory() as session:
        attempt = await session.get(ExecutionAttempt, attempt_id)
        if attempt is None:
            raise _MissingAttempt
        run = await session.get(ExecutionRun, attempt.run_id)
        if run is None:
            raise _MissingAttempt
        assert_kund_access(user, run.customer_id)
        await require_context_workspace(session, user, run.customer_id, run.context or {})
        return attempt.id


async def watch_workspace_research(
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
            hello = ResearchWatchHello.model_validate(raw)
        except ValidationError as exc:
            await send_error(websocket, str(exc.errors()[0]["msg"]))
            await websocket.close(code=1003)
            return
        factory = jobs_service.job_session_factory()
        try:
            attempt_id = await _authorized_attempt_id(factory, user, hello.attempt_id)
        except _MissingAttempt:
            await send_error(websocket, f"Attempt {hello.attempt_id} not found")
            await websocket.close(code=1003)
            return
        except HTTPException as exc:
            await close_auth_error(websocket, exc)
            return
        # Subscribe before replay so a committed transition reaches at least
        # one channel. Membership is checked again before replay and each push.
        await research_progress_broadcast.subscribe(
            attempt_id,
            websocket,
            authorize=workspace_event_authorizer(factory, user.id, attempt_id=attempt_id),
        )
        async with factory() as session:
            await require_execution_attempt(session, user, attempt_id)
            events = await list_research_progress_events(
                session, attempt_id, after_sequence=hello.after_sequence
            )
            replay = [progress_event_to_dict(row) for row in events]
        await websocket.send_json(
            {
                "type": "research.progress.replay",
                "attempt_id": attempt_id,
                "after_sequence": hello.after_sequence,
                "events": replay,
            }
        )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Research progress watch WebSocket failed")
        await send_error(websocket, "WebSocket error")
        try:
            await websocket.close(code=1011)
        except (WebSocketDisconnect, RuntimeError):
            pass
    finally:
        await research_progress_broadcast.unsubscribe(websocket)
