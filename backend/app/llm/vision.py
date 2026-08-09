"""OpenAI vision chat for playground image understanding."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable

from openai import AsyncOpenAI

from app.config import settings

VisionCompleter = Callable[[list[dict[str, object]], str], Awaitable[str]]

_client: AsyncOpenAI | None = None
_vision_completer: VisionCompleter | None = None


def get_vision_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.embedding_base_url,
            timeout=settings.vision_timeout_seconds,
        )
    return _client


def reset_vision_client() -> None:
    global _client
    _client = None


def set_vision_completer(completer: VisionCompleter | None) -> None:
    global _vision_completer
    _vision_completer = completer


async def complete_vision_text(
    *,
    image_bytes: bytes,
    content_type: str,
    prompt: str,
) -> str:
    if _vision_completer is not None:
        messages: list[dict[str, object]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{base64.standard_b64encode(image_bytes).decode('ascii')}",
                        },
                    },
                ],
            }
        ]
        return await _vision_completer(messages, content_type)

    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{content_type};base64,{b64}"},
                },
            ],
        }
    ]
    client = get_vision_client()
    completion = await asyncio.wait_for(
        client.chat.completions.create(
            model=settings.vision_model,
            messages=messages,  # type: ignore[arg-type]
        ),
        timeout=settings.vision_timeout_seconds,
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("Vision model returned empty response")
    return content.strip()
