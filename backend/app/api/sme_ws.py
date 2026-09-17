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
from app.schemas.domain import PersonaChatResponse
from app.services import jobs as jobs_service
from app.services.persona_chat import (
    ChatTurnError,
    library_follow_up_questions,
    stream_library_chat_turn,
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

    async def run_expert_turn(send: SmeExpertSend) -> None:
        envelope = {
            "thread_type": send.thread_type,
            "thread_id": send.thread_id,
            "request_id": send.request_id,
        }
        await emit({"type": "typing", "on": True, **envelope})
        try:
            async with factory() as session:
                persona = await session.get(Persona, send.thread_id)
                if persona is None or persona.kind != "expert":
                    raise ChatTurnError("Expert not found", status_code=404)
                if persona.customer_id != user.kund_id:
                    raise HTTPException(status_code=403, detail="kund_access_denied")
                done: PersonaChatResponse | None = None
                stream = stream_library_chat_turn(
                    session,
                    persona_id=send.thread_id,
                    mode="interview",
                    message=send.message,
                    image_sha256=send.image_sha256,
                )
                try:
                    async for item in stream:
                        if isinstance(item, PersonaChatResponse):
                            done = item
                        else:
                            await emit({"type": "token", "text": item, **envelope})
                finally:
                    await stream.aclose()
                if done is None:
                    raise ChatTurnError("Chat turn produced no reply", status_code=502)
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
                questions = await library_follow_up_questions(
                    session,
                    persona_id=send.thread_id,
                    mode="interview",
                )
                await emit(
                    {
                        "type": "suggestions",
                        "questions": questions,
                        **envelope,
                    }
                )
        except HTTPException as exc:
            await emit({"type": "error", "detail": str(exc.detail), **envelope})
        except ChatTurnError as exc:
            await emit({"type": "error", "detail": exc.detail, **envelope})
        except Exception:
            logger.exception("SME expert chat turn failed")
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
