"""WebSocket endpoints for jobs fan-out and streaming chat."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.scope import assert_kund_access, effective_customer_id
from app.auth.tokens import user_from_bearer_token
from app.database.models import (
    PanelSession,
    Persona,
    Population,
    PopulationMember,
    Projekt,
    Report,
    Run,
    UserAccount,
)
from app.realtime.hub import job_hub, report_hub
from app.realtime.interview_broadcast import interview_broadcast, interview_key_tuple
from app.realtime.panel_broadcast import panel_broadcast
from app.realtime.run_broadcast import run_broadcast
from app.schemas.domain import (
    ChatMode,
    HelpChatResponse,
    HelpViewContext,
    PersonaChatResponse,
    SpindoctorChatResponse,
    SpindoctorWidgetOut,
)
from app.services import jobs as jobs_service
from app.services.customer_scope import customer_id_for_panel_session
from app.services.help_chat import ChatTurnError as HelpChatTurnError
from app.services.help_chat import stream_help_chat_turn
from app.services.persona_chat import (
    ChatSuggestions,
    ChatTurnError,
    stream_library_chat_turn,
    stream_run_interview_turn,
)
from app.services.spindoctor_chat import (
    SpindoctorChatTurnError,
    stream_spindoctor_chat_turn,
)
from app.services.report_realtime import list_reports, serialize_report
from app.services.run_watch import build_run_replay_payload
from app.services.panel.watch import build_panel_replay_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


class LibraryHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["library"]
    persona_id: str = Field(min_length=1)
    mode: ChatMode = "interview"


class RunInterviewHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["run_interview"]
    run_id: int
    attempt_id: str = Field(min_length=1)
    variant_id: str = Field(min_length=1)
    persona_id: str = Field(min_length=1)
    through_tick_index: int = Field(ge=0)


class HelpHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["help"]
    session_id: str = Field(min_length=1, max_length=64)
    locale: Literal["sv", "en"] = "sv"
    view: HelpViewContext | None = None
    customer_id: int = Field(ge=1)
    module: str = Field(min_length=1, max_length=32)


class SpindoctorHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["spinndoctor"]
    session_id: str = Field(min_length=1, max_length=64)
    report_id: str = Field(min_length=1, max_length=64)
    locale: Literal["sv", "en"] = "sv"


class RunWatchHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["run_watch"]
    run_id: int
    variant_id: str = Field(min_length=1)


class PanelWatchHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["panel_watch"]
    session_id: str = Field(min_length=1)


class JobsWatchHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["jobs_watch"]
    customer_id: int | None = None


class ReportsWatchHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["reports_watch"]
    customer_id: int | None = None


class ChatSend(BaseModel):
    type: Literal["send"]
    message: str = Field(min_length=1)
    view: HelpViewContext | None = None
    ground_population: bool = False


async def _send_error(websocket: WebSocket, detail: str) -> None:
    try:
        await websocket.send_json({"type": "error", "detail": detail})
    except (WebSocketDisconnect, RuntimeError):
        pass


async def _close_auth_error(websocket: WebSocket, exc: HTTPException) -> None:
    code = 4401 if exc.status_code == 401 else 4403
    try:
        await websocket.close(code=code)
    except Exception:
        pass


async def _authenticate_websocket(websocket: WebSocket) -> UserAccount | None:
    """Verify access_token query param before any hub subscribe. Returns None if closed."""
    access_token = websocket.query_params.get("access_token")
    factory = jobs_service.job_session_factory()
    try:
        async with factory() as session:
            return await user_from_bearer_token(session, access_token)
    except HTTPException as exc:
        await _close_auth_error(websocket, exc)
        return None


async def _assert_run_ws_access(
    session: AsyncSession,
    user: UserAccount,
    run: Run,
) -> None:
    projekt = await session.get(Projekt, run.project_id)
    assert_kund_access(user, None if projekt is None else projekt.customer_id)


async def _assert_panel_ws_access(
    session: AsyncSession,
    user: UserAccount,
    *,
    session_id: str,
    campaign_id: int | None,
) -> None:
    if campaign_id is not None:
        customer_id = await customer_id_for_panel_session(session, session_id)
        assert_kund_access(user, customer_id)
        return
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin_required")


@router.websocket("/ws/jobs")
async def jobs_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    user = await _authenticate_websocket(websocket)
    if user is None:
        return
    try:
        raw = await websocket.receive_json()
        if not isinstance(raw, dict):
            await _send_error(websocket, "Expected JSON object")
            await websocket.close(code=1003)
            return
        try:
            hello = JobsWatchHello.model_validate(raw)
        except ValidationError as exc:
            await _send_error(websocket, str(exc.errors()[0]["msg"]))
            await websocket.close(code=1003)
            return

        try:
            customer_id = effective_customer_id(user, hello.customer_id)
        except HTTPException as exc:
            await _close_auth_error(websocket, exc)
            return

        await job_hub.subscribe(websocket, customer_id=customer_id)

        factory = jobs_service.job_session_factory()
        async with factory() as session:
            rows = await jobs_service.list_jobs(
                session, limit=50, customer_id=customer_id
            )
            await websocket.send_json(
                {
                    "type": "jobs.snapshot",
                    "jobs": [
                        jobs_service.serialize_job(row).model_dump(mode="json")
                        for row in rows
                    ],
                }
            )
        while True:
            # Keep the socket open; clients may send pings. Ignore payload.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Jobs watch WebSocket failed")
        try:
            await _send_error(websocket, "WebSocket error")
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        await job_hub.unsubscribe(websocket)


@router.websocket("/ws/reports")
async def reports_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    user = await _authenticate_websocket(websocket)
    if user is None:
        return
    try:
        raw = await websocket.receive_json()
        if not isinstance(raw, dict):
            await _send_error(websocket, "Expected JSON object")
            await websocket.close(code=1003)
            return
        try:
            hello = ReportsWatchHello.model_validate(raw)
        except ValidationError as exc:
            await _send_error(websocket, str(exc.errors()[0]["msg"]))
            await websocket.close(code=1003)
            return

        try:
            customer_id = effective_customer_id(user, hello.customer_id)
        except HTTPException as exc:
            await _close_auth_error(websocket, exc)
            return

        await report_hub.subscribe(websocket, customer_id=customer_id)

        factory = jobs_service.job_session_factory()
        async with factory() as session:
            rows = await list_reports(
                session, limit=50, customer_id=customer_id
            )
            await websocket.send_json(
                {
                    "type": "reports.snapshot",
                    "reports": [
                        serialize_report(row).model_dump(mode="json") for row in rows
                    ],
                }
            )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Reports watch WebSocket failed")
        try:
            await _send_error(websocket, "WebSocket error")
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        await report_hub.unsubscribe(websocket)


@router.websocket("/ws/runs")
async def runs_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    user = await _authenticate_websocket(websocket)
    if user is None:
        return
    hello: RunWatchHello | None = None
    try:
        raw = await websocket.receive_json()
        if not isinstance(raw, dict):
            await _send_error(websocket, "Expected JSON object")
            await websocket.close(code=1003)
            return
        try:
            hello = RunWatchHello.model_validate(raw)
        except ValidationError as exc:
            await _send_error(websocket, str(exc.errors()[0]["msg"]))
            await websocket.close(code=1003)
            return

        factory = jobs_service.job_session_factory()
        async with factory() as session:
            result = await session.execute(
                select(Run)
                .where(Run.id == hello.run_id)
                .options(
                    selectinload(Run.population).selectinload(Population.members)
                )
            )
            run = result.scalar_one_or_none()
            if run is None:
                await _send_error(websocket, f"Run {hello.run_id} not found")
                await websocket.close(code=1003)
                return
            try:
                await _assert_run_ws_access(session, user, run)
            except HTTPException as exc:
                await _close_auth_error(websocket, exc)
                return
            members: list[PopulationMember] = (
                list(run.population.members) if run.population is not None else []
            )
            replay = build_run_replay_payload(
                run,
                variant_id=hello.variant_id,
                members=members,
            )

        key = (hello.run_id, hello.variant_id)
        await run_broadcast.subscribe(key, websocket)
        await websocket.send_json(replay)

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Run watch WebSocket failed")
        try:
            await _send_error(websocket, "WebSocket error")
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        await run_broadcast.unsubscribe(websocket)


@router.websocket("/ws/panels")
async def panels_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    user = await _authenticate_websocket(websocket)
    if user is None:
        return
    hello: PanelWatchHello | None = None
    try:
        raw = await websocket.receive_json()
        if not isinstance(raw, dict):
            await _send_error(websocket, "Expected JSON object")
            await websocket.close(code=1003)
            return
        try:
            hello = PanelWatchHello.model_validate(raw)
        except ValidationError as exc:
            await _send_error(websocket, str(exc.errors()[0]["msg"]))
            await websocket.close(code=1003)
            return

        factory = jobs_service.job_session_factory()
        async with factory() as session:
            panel = await session.get(PanelSession, hello.session_id)
            if panel is None:
                await _send_error(websocket, f"Panel session {hello.session_id} not found")
                await websocket.close(code=1003)
                return
            try:
                await _assert_panel_ws_access(
                    session,
                    user,
                    session_id=hello.session_id,
                    campaign_id=panel.campaign_id,
                )
            except HTTPException as exc:
                await _close_auth_error(websocket, exc)
                return
            replay = build_panel_replay_payload(panel)

        await panel_broadcast.subscribe(hello.session_id, websocket)
        await websocket.send_json(replay)

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Panel watch WebSocket failed")
        try:
            await _send_error(websocket, "WebSocket error")
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        await panel_broadcast.unsubscribe(websocket)


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    user = await _authenticate_websocket(websocket)
    if user is None:
        return
    hello: LibraryHello | RunInterviewHello | HelpHello | SpindoctorHello | None = None
    try:
        raw = await websocket.receive_json()
        if not isinstance(raw, dict):
            await _send_error(websocket, "Expected JSON object")
            await websocket.close(code=1003)
            return
        scope = raw.get("scope")
        try:
            if scope == "library":
                hello = LibraryHello.model_validate(raw)
            elif scope == "run_interview":
                hello = RunInterviewHello.model_validate(raw)
            elif scope == "help":
                hello = HelpHello.model_validate(raw)
            elif scope == "spinndoctor":
                hello = SpindoctorHello.model_validate(raw)
            else:
                await _send_error(
                    websocket,
                    "hello.scope must be library, run_interview, help, or spinndoctor",
                )
                await websocket.close(code=1003)
                return
        except ValidationError as exc:
            await _send_error(websocket, str(exc.errors()[0]["msg"]))
            await websocket.close(code=1003)
            return

        factory = jobs_service.job_session_factory()
        async with factory() as session:
            try:
                if isinstance(hello, LibraryHello):
                    persona = await session.get(Persona, hello.persona_id)
                    if persona is None:
                        await _send_error(websocket, "Persona not found")
                        await websocket.close(code=1003)
                        return
                    assert_kund_access(user, persona.customer_id)
                elif isinstance(hello, RunInterviewHello):
                    run = await session.get(Run, hello.run_id)
                    if run is None:
                        await _send_error(websocket, f"Run {hello.run_id} not found")
                        await websocket.close(code=1003)
                        return
                    await _assert_run_ws_access(session, user, run)
                elif isinstance(hello, SpindoctorHello):
                    report = await session.get(Report, hello.report_id)
                    if report is None:
                        await _send_error(websocket, "Report not found")
                        await websocket.close(code=1003)
                        return
                    assert_kund_access(user, report.customer_id)
                # HelpHello: authenticated user is enough
            except HTTPException as exc:
                await _close_auth_error(websocket, exc)
                return

        await websocket.send_json({"type": "ready", "scope": hello.scope})

        if isinstance(hello, RunInterviewHello):
            await interview_broadcast.subscribe(
                interview_key_tuple(
                    persona_id=hello.persona_id,
                    run_id=hello.run_id,
                    attempt_id=hello.attempt_id,
                    variant_id=hello.variant_id,
                    through_tick_index=hello.through_tick_index,
                ),
                websocket,
            )

        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                await _send_error(websocket, "Expected JSON object")
                continue
            if payload.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
                continue
            try:
                send = ChatSend.model_validate(payload)
            except ValidationError as exc:
                await _send_error(websocket, str(exc.errors()[0]["msg"]))
                continue

            await websocket.send_json({"type": "typing", "on": True})
            try:
                # Same injectable factory as background jobs so tests share one DB.
                factory = jobs_service.job_session_factory()
                async with factory() as session:
                    if isinstance(hello, HelpHello):
                        done_help: HelpChatResponse | None = None
                        turn_view = send.view if send.view is not None else hello.view
                        stream = stream_help_chat_turn(
                            session,
                            session_id=hello.session_id,
                            locale=hello.locale,
                            message=send.message,
                            view=turn_view,
                            customer_id=hello.customer_id,
                            module=hello.module,
                            ground_population=send.ground_population,
                        )
                        async for item in stream:
                            if isinstance(item, HelpChatResponse):
                                done_help = item
                            else:
                                await websocket.send_json({"type": "token", "text": item})
                        if done_help is None:
                            await _send_error(websocket, "Help chat turn produced no reply")
                            continue
                        await websocket.send_json(
                            {
                                "type": "done",
                                "reply": done_help.reply,
                                "messages": [
                                    m.model_dump(mode="json") for m in done_help.messages
                                ],
                            }
                        )
                        continue

                    if isinstance(hello, SpindoctorHello):
                        done_spin: SpindoctorChatResponse | None = None
                        stream = stream_spindoctor_chat_turn(
                            session,
                            report_id=hello.report_id,
                            locale=hello.locale,
                            message=send.message,
                        )
                        async for item in stream:
                            if isinstance(item, SpindoctorWidgetOut):
                                await websocket.send_json(
                                    {
                                        "type": "widget",
                                        **item.model_dump(mode="json"),
                                    }
                                )
                            elif isinstance(item, SpindoctorChatResponse):
                                done_spin = item
                            else:
                                await websocket.send_json({"type": "token", "text": item})
                        if done_spin is None:
                            await _send_error(
                                websocket, "Spinndoktor turn produced no reply"
                            )
                            continue
                        await websocket.send_json(
                            {
                                "type": "done",
                                "reply": done_spin.reply,
                                "messages": [
                                    m.model_dump(mode="json") for m in done_spin.messages
                                ],
                            }
                        )
                        continue

                    done: PersonaChatResponse | None = None
                    if isinstance(hello, LibraryHello):
                        stream = stream_library_chat_turn(
                            session,
                            persona_id=hello.persona_id,
                            mode=hello.mode,
                            message=send.message,
                        )
                    else:
                        stream = stream_run_interview_turn(
                            session,
                            run_id=hello.run_id,
                            attempt_id=hello.attempt_id,
                            variant_id=hello.variant_id,
                            persona_id=hello.persona_id,
                            through_tick_index=hello.through_tick_index,
                            message=send.message,
                            asked_by="human",
                        )
                    async for item in stream:
                        if isinstance(item, PersonaChatResponse):
                            done = item
                            await websocket.send_json(
                                {
                                    "type": "done",
                                    "reply": done.reply,
                                    "messages": [
                                        m.model_dump(mode="json") for m in done.messages
                                    ],
                                    "suggestions": done.suggestions,
                                }
                            )
                        elif isinstance(item, ChatSuggestions):
                            await websocket.send_json(
                                {
                                    "type": "suggestions",
                                    "questions": item.questions,
                                }
                            )
                        else:
                            await websocket.send_json({"type": "token", "text": item})
                    if done is None:
                        await _send_error(websocket, "Chat turn produced no reply")
                        continue
            except WebSocketDisconnect:
                raise
            except HelpChatTurnError as exc:
                await _send_error(websocket, exc.detail)
            except SpindoctorChatTurnError as exc:
                await _send_error(websocket, exc.detail)
            except ChatTurnError as exc:
                await _send_error(websocket, exc.detail)
            except Exception:
                logger.exception("Chat WebSocket turn failed")
                await _send_error(websocket, "Chat turn failed")
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Chat WebSocket failed")
        try:
            await _send_error(websocket, "WebSocket error")
            await websocket.close(code=1011)
        except Exception:
            pass
    finally:
        await interview_broadcast.unsubscribe(websocket)
