"""Vision chat for playground image understanding (OpenAI, Google, Ollama)."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.services.playground_image_models import VisionProvider

VisionCompleter = Callable[["VisionRequest"], Awaitable[str]]

_client: AsyncOpenAI | None = None
_vision_completer: VisionCompleter | None = None


@dataclass(frozen=True)
class VisionRequest:
    image_bytes: bytes
    content_type: str
    prompt: str
    provider: VisionProvider
    model: str


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


def _image_data_url(image_bytes: bytes, content_type: str) -> str:
    b64 = base64.standard_b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{b64}"


async def _vision_openai(request: VisionRequest) -> str:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": request.prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": _image_data_url(request.image_bytes, request.content_type)},
                },
            ],
        }
    ]
    client = get_vision_client()
    completion = await asyncio.wait_for(
        client.chat.completions.create(
            model=request.model,
            messages=messages,  # type: ignore[arg-type]
        ),
        timeout=settings.vision_timeout_seconds,
    )
    content = completion.choices[0].message.content
    if not content:
        raise RuntimeError("OpenAI vision returned empty response")
    return content.strip()


async def _vision_google(request: VisionRequest) -> str:
    if not settings.google_api_key.strip():
        raise RuntimeError("GOOGLE_API_KEY is not configured")
    b64 = base64.standard_b64encode(request.image_bytes).decode("ascii")
    url = (
        f"{settings.google_vision_base_url.rstrip('/')}/models/"
        f"{request.model}:generateContent"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": request.prompt},
                    {"inline_data": {"mime_type": request.content_type, "data": b64}},
                ]
            }
        ]
    }
    async with httpx.AsyncClient(timeout=settings.vision_timeout_seconds) as client:
        response = await client.post(
            url,
            params={"key": settings.google_api_key},
            json=payload,
        )
    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise RuntimeError(f"Google vision failed ({response.status_code}): {detail}")
    data = response.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("Google vision returned no candidates")
    parts = candidates[0].get("content", {}).get("parts") or []
    text_parts = [str(part.get("text", "")).strip() for part in parts if part.get("text")]
    text = "\n".join(part for part in text_parts if part).strip()
    if not text:
        raise RuntimeError("Google vision returned empty text")
    return text


async def _vision_ollama(request: VisionRequest) -> str:
    if not settings.ollama_api_key.strip():
        raise RuntimeError("OLLAMA_API_KEY is not configured")
    b64 = base64.standard_b64encode(request.image_bytes).decode("ascii")
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload = {
        "model": request.model,
        "messages": [
            {
                "role": "user",
                "content": request.prompt,
                "images": [b64],
            }
        ],
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {settings.ollama_api_key}"}
    async with httpx.AsyncClient(timeout=settings.vision_timeout_seconds) as client:
        response = await client.post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise RuntimeError(f"Ollama vision failed ({response.status_code}): {detail}")
    data = response.json()
    message = data.get("message") or {}
    content = str(message.get("content", "")).strip()
    if not content:
        raise RuntimeError("Ollama vision returned empty response")
    return content


async def complete_vision_text(
    *,
    image_bytes: bytes,
    content_type: str,
    prompt: str,
    provider: VisionProvider,
    model: str,
) -> str:
    request = VisionRequest(
        image_bytes=image_bytes,
        content_type=content_type,
        prompt=prompt,
        provider=provider,
        model=model,
    )
    if _vision_completer is not None:
        return await _vision_completer(request)

    if provider == "openai":
        return await _vision_openai(request)
    if provider == "google":
        return await _vision_google(request)
    if provider == "ollama":
        return await _vision_ollama(request)
    raise RuntimeError(f"Unsupported vision provider: {provider!r}")
