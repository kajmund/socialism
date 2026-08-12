"""WebSocket endpoints for jobs fan-out and streaming chat."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError

from app.realtime.hub import job_hub, report_hub
from app.schemas.domain import (
    ChatMode,
    HelpChatResponse,
    HelpViewContext,
    PersonaChatResponse,
    SpindoctorChatResponse,
)
from app.services import jobs as jobs_service
from app.services.help_chat import ChatTurnError as HelpChatTurnError
from app.services.help_chat import stream_help_chat_turn
from app.services.persona_chat import (
    ChatTurnError,
    stream_library_chat_turn,
    stream_run_interview_turn,
)
from app.services.spindoctor_chat import (
    SpindoctorChatTurnError,
    stream_spindoctor_chat_turn,
)
from app.services.report_realtime import list_reports, serialize_report

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


class SpindoctorHello(BaseModel):
    type: Literal["hello"] = "hello"
    scope: Literal["spinndoctor"]
    session_id: str = Field(min_length=1, max_length=64)
    report_id: str = Field(min_length=1, max_length=64)
    locale: Literal["sv", "en"] = "sv"


class ChatSend(BaseModel):
    type: Literal["send"]
    message: str = Field(min_length=1)
    view: HelpViewContext | None = None
    ground_population: bool = False


async def _send_error(websocket: WebSocket, detail: str) -> None:
    await websocket.send_json({"type": "error", "detail": detail})


@router.websocket("/ws/jobs")
async def jobs_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    await job_hub.subscribe(websocket)
    try:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            rows = await jobs_service.list_jobs(session, limit=50)
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
    finally:
        await job_hub.unsubscribe(websocket)


@router.websocket("/ws/reports")
async def reports_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    await report_hub.subscribe(websocket)
    try:
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            rows = await list_reports(session, limit=50)
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
    finally:
        await report_hub.unsubscribe(websocket)


@router.websocket("/ws/chat")
async def chat_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
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

        await websocket.send_json({"type": "ready", "scope": hello.scope})

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
                            if isinstance(item, SpindoctorChatResponse):
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
                        )
                    async for item in stream:
                        if isinstance(item, PersonaChatResponse):
                            done = item
                        else:
                            await websocket.send_json({"type": "token", "text": item})
                    if done is None:
                        await _send_error(websocket, "Chat turn produced no reply")
                        continue
                    await websocket.send_json(
                        {
                            "type": "done",
                            "reply": done.reply,
                            "messages": [
                                m.model_dump(mode="json") for m in done.messages
                            ],
                        }
                    )
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
