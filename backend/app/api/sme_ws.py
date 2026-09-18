"""Product-level SME chat WebSocket routing expert output by thread."""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.auth.tokens import user_from_bearer_token
from app.database.models import Kund, Persona, UserAccount
from app.services import jobs as jobs_service
from app.services.persona_chat import ChatTurnError, library_follow_up_questions
from app.services.sme_expert_turns import (
    SmeExpertTurnConflict,
    accept_expert_turn,
    execute_expert_turn,
    finish_expert_turn,
    get_owned_expert_turn,
    mark_expert_turn_running,
    serialize_expert_turn,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


class SmeExpertSend(BaseModel):
    type: Literal["send"]
    request_id: str = Field(min_length=1, max_length=64)
    thread_type: Literal["expert"]
    thread_id: str = Field(min_length=1, max_length=64)
    message: str = Field(max_length=10_000)
    image_sha256: str | None = Field(default=None, min_length=64, max_length=64)

    @field_validator("message")
    @classmethod
    def normalize_message(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def require_message_or_image(self) -> SmeExpertSend:
        if not self.message and not self.image_sha256:
            raise ValueError("message is required")
        return self


async def _authenticate(websocket: WebSocket) -> UserAccount:
    factory = jobs_service.job_session_factory()
    async with factory() as session:
        return await user_from_bearer_token(
            session,
            websocket.query_params.get("access_token"),
        )


@router.websocket("/ws/sme")
async def sme_chat_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        user = await _authenticate(websocket)
        if user.kund_id is None:
            raise HTTPException(status_code=403, detail="kund_access_denied")
        factory = jobs_service.job_session_factory()
        async with factory() as session:
            kund = await session.get(Kund, user.kund_id)
            if kund is None or kund.product != "sme":
                raise HTTPException(status_code=403, detail="sme_product_required")
    except HTTPException as exc:
        await websocket.send_json({"type": "error", "detail": str(exc.detail)})
        await websocket.close(code=4403)
        return

    disconnected = asyncio.Event()
    send_lock = asyncio.Lock()
    tasks: set[asyncio.Task[None]] = set()

    async def emit(payload: dict) -> None:
        if disconnected.is_set():
            return
        async with send_lock:
            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                disconnected.set()

    async def _fail_expert_turn(
        request_id: str,
        turn_fence: int | None,
        detail: str,
    ) -> None:
        if turn_fence is None:
            return
        async with factory() as session:
            await finish_expert_turn(
                session,
                request_id,
                fence=turn_fence,
                status="failed",
                error=detail,
            )
            await session.commit()

    async def _emit_completed_turn(send: SmeExpertSend, envelope: dict) -> None:
        async with factory() as session:
            if user.kund_id is None:
                raise ChatTurnError("kund_access_denied", status_code=403)
            turn = await get_owned_expert_turn(
                session,
                send.request_id,
                customer_id=user.kund_id,
                user_id=user.id,
            )
            if turn is None:
                raise ChatTurnError("Expert turn not found", status_code=404)
            if turn.status in {"accepted", "running"}:
                await emit({"type": "turn", "status": turn.status, **envelope})
                return
            payload = await serialize_expert_turn(session, turn)
            if turn.status == "failed":
                await emit(
                    {
                        "type": "error",
                        "detail": turn.error or "Chat error",
                        **envelope,
                    }
                )
                return
            questions = await library_follow_up_questions(
                session,
                persona_id=send.thread_id,
                mode="interview",
            )
        await emit(
            {
                "type": "done",
                "reply": next(
                    (
                        row.content
                        for row in reversed(payload.messages)
                        if row.role == "assistant"
                    ),
                    "",
                ),
                "messages": [row.model_dump(mode="json") for row in payload.messages],
                **envelope,
            }
        )
        await emit(
            {
                "type": "suggestions",
                "questions": questions,
                **envelope,
            }
        )

    async def run_expert_turn(send: SmeExpertSend) -> None:
        envelope = {
            "thread_type": send.thread_type,
            "thread_id": send.thread_id,
            "request_id": send.request_id,
        }
        await emit({"type": "typing", "on": True, **envelope})
        fence: int | None = None
        token: str | None = None
        should_run = False
        try:
            async with factory() as session:
                persona = await session.get(Persona, send.thread_id)
                if persona is None or persona.kind != "expert":
                    raise ChatTurnError("Expert not found", status_code=404)
                if persona.customer_id != user.kund_id:
                    raise HTTPException(status_code=403, detail="kund_access_denied")
                try:
                    turn, should_run = await accept_expert_turn(
                        session,
                        request_id=send.request_id,
                        customer_id=persona.customer_id,
                        user_id=user.id,
                        persona_id=send.thread_id,
                        message=send.message,
                        image_sha256=send.image_sha256,
                    )
                except SmeExpertTurnConflict as exc:
                    raise ChatTurnError(str(exc), status_code=409) from exc
                fence = turn.fence
                token = turn.lease_token
                if should_run and turn.status == "accepted":
                    if token is None:
                        raise ChatTurnError("stale_expert_turn", status_code=409)
                    marked = await mark_expert_turn_running(
                        session,
                        send.request_id,
                        fence=fence,
                        token=token,
                    )
                    if not marked:
                        raise ChatTurnError("stale_expert_turn", status_code=409)
                await session.commit()
            if not should_run:
                await _emit_completed_turn(send, envelope)
                return
            if token is None:
                raise ChatTurnError("stale_expert_turn", status_code=409)

            async def on_token(text: str) -> None:
                await emit({"type": "token", "text": text, **envelope})

            done = await execute_expert_turn(
                factory,
                request_id=send.request_id,
                persona_id=send.thread_id,
                message=send.message,
                image_sha256=send.image_sha256,
                fence=fence,
                token=token,
                on_token=on_token,
            )
            async with factory() as session:
                questions = await library_follow_up_questions(
                    session,
                    persona_id=send.thread_id,
                    mode="interview",
                )
            await emit(
                {
                    "type": "done",
                    "reply": done.reply,
                    "messages": [
                        message.model_dump(mode="json")
                        for message in done.messages
                    ],
                    **envelope,
                }
            )
            await emit(
                {
                    "type": "suggestions",
                    "questions": questions,
                    **envelope,
                }
            )
        except HTTPException as exc:
            await _fail_expert_turn(send.request_id, fence, str(exc.detail))
            await emit({"type": "error", "detail": str(exc.detail), **envelope})
        except ChatTurnError as exc:
            await _fail_expert_turn(send.request_id, fence, exc.detail)
            await emit({"type": "error", "detail": exc.detail, **envelope})
        except Exception:
            logger.exception("SME expert chat turn failed")
            await _fail_expert_turn(send.request_id, fence, "Chat error")
            await emit({"type": "error", "detail": "Chat error", **envelope})
        finally:
            await emit({"type": "typing", "on": False, **envelope})

    await emit({"type": "ready", "scope": "sme"})
    try:
        while True:
            raw = await websocket.receive_json()
            if not isinstance(raw, dict):
                await emit({"type": "error", "detail": "Expected JSON object"})
                continue
            if raw.get("type") == "ping":
                await emit({"type": "pong"})
                continue
            try:
                send = SmeExpertSend.model_validate(raw)
            except ValidationError as exc:
                await emit(
                    {
                        "type": "error",
                        "detail": str(exc.errors()[0]["msg"]),
                    }
                )
                continue
            task = asyncio.create_task(run_expert_turn(send))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
    except WebSocketDisconnect:
        disconnected.set()
    except Exception:
        logger.exception("SME chat WebSocket failed")
        disconnected.set()
    finally:
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
