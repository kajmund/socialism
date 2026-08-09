"""Admin playground: SSR calibration, lexicon compare, prompt iteration, tools."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Configuration, Persona
from app.database.session import get_session
from app.llm import complete_text
from app.services.playground import (
    compare_ssr_lexicon,
    default_anchor_set,
    rate_case,
)
from app.services.playground_tools import list_tool_catalog, run_agent_tool
from app.services.playground_image import react_to_image
from app.services.ssr import ANCHOR_SET_VERSION, style_anchors, tone_anchors

router = APIRouter(prefix="/playground", tags=["playground"])

Dimension = Literal["tone", "style"]
Locale = Literal["sv", "en"]


class AnchorSetOut(BaseModel):
    name: str
    version: str
    labels: list[str]
    statements: list[str]


class AnchorsOut(BaseModel):
    version: str
    tone: dict[str, AnchorSetOut]
    style: dict[str, AnchorSetOut]


class RateRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    dimension: Dimension = "tone"
    locale: Locale = "sv"
    labels: list[str] | None = None
    statements: list[str] | None = None
    temperature: float = Field(default=1.0, gt=0)
    human_labels: list[str] | None = None


class CompareRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    locale: Locale = "sv"
    labels: list[str] | None = None
    statements: list[str] | None = None
    temperature: float = Field(default=1.0, gt=0)


class PromptRunRequest(BaseModel):
    configuration_id: int
    prompt_key: str
    prompt_override: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)
    user_message: str | None = None


class PromptVariantOut(BaseModel):
    id: Literal["A", "B"]
    rendered_prompt: str
    response: str


class PromptRunOut(BaseModel):
    configuration_id: int
    prompt_key: str
    variants: list[PromptVariantOut]


def _anchor_out(anchor) -> AnchorSetOut:
    return AnchorSetOut(
        name=anchor.name,
        version=anchor.version,
        labels=list(anchor.labels),
        statements=list(anchor.statements),
    )


@router.get("/anchors", response_model=AnchorsOut)
async def get_anchors() -> AnchorsOut:
    return AnchorsOut(
        version=ANCHOR_SET_VERSION,
        tone={
            "sv": _anchor_out(tone_anchors(locale="sv")),
            "en": _anchor_out(tone_anchors(locale="en")),
        },
        style={
            "sv": _anchor_out(style_anchors(locale="sv")),
            "en": _anchor_out(style_anchors(locale="en")),
        },
    )


@router.post("/ssr/rate")
async def post_ssr_rate(body: RateRequest) -> dict:
    texts = [t.strip() for t in body.texts if t.strip()]
    if not texts:
        raise HTTPException(status_code=400, detail="texts must contain non-empty strings")
    human = body.human_labels
    if human is not None:
        if len(human) != len(body.texts):
            raise HTTPException(
                status_code=400,
                detail="human_labels must have the same length as texts",
            )
        # Align with stripped texts: drop labels for empty source rows
        human = [h for t, h in zip(body.texts, human, strict=True) if t.strip()]
        if len(human) != len(texts):
            raise HTTPException(
                status_code=400,
                detail="human_labels must align with non-empty texts",
            )
        allowed = set(
            default_anchor_set(dimension=body.dimension, locale=body.locale).labels
            if body.labels is None
            else body.labels
        )
        bad = [h for h in human if h not in allowed]
        if bad:
            raise HTTPException(
                status_code=400,
                detail=f"human_labels not in anchor labels: {bad[0]!r}",
            )
    try:
        return await rate_case(
            texts,
            dimension=body.dimension,
            locale=body.locale,
            labels=body.labels,
            statements=body.statements,
            temperature=body.temperature,
            human_labels=human,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ssr/compare")
async def post_ssr_compare(body: CompareRequest) -> dict:
    texts = [t.strip() for t in body.texts if t.strip()]
    if not texts:
        raise HTTPException(status_code=400, detail="texts must contain non-empty strings")
    try:
        return await compare_ssr_lexicon(
            texts,
            locale=body.locale,
            labels=body.labels,
            statements=body.statements,
            temperature=body.temperature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _render_prompt_text(text: str, *, prompt_key: str, variables: dict[str, str]) -> str:
    if not text.strip():
        raise HTTPException(status_code=400, detail=f"Prompt '{prompt_key}' is empty")
    try:
        return text.format(**variables)
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Prompt '{prompt_key}' missing placeholder {exc}",
        ) from exc


async def _run_variant(
    *,
    variant_id: Literal["A", "B"],
    rendered: str,
    user_message: str | None,
) -> PromptVariantOut:
    messages: list[dict[str, str]] = [{"role": "system", "content": rendered}]
    if user_message is not None and user_message.strip():
        messages.append({"role": "user", "content": user_message.strip()})
    response = await complete_text(messages)
    return PromptVariantOut(
        id=variant_id,
        rendered_prompt=rendered,
        response=response,
    )


@router.post("/prompts/run", response_model=PromptRunOut)
async def post_prompts_run(
    body: PromptRunRequest,
    session: AsyncSession = Depends(get_session),
) -> PromptRunOut:
    row = await session.get(Configuration, body.configuration_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Configuration not found")
    prompts = dict(row.prompts or {})
    source_a = prompts.get(body.prompt_key)
    if source_a is None:
        raise HTTPException(
            status_code=400,
            detail=f"Configuration missing prompt '{body.prompt_key}'",
        )
    rendered_a = _render_prompt_text(
        str(source_a),
        prompt_key=body.prompt_key,
        variables=body.variables,
    )
    variants = [
        await _run_variant(
            variant_id="A",
            rendered=rendered_a,
            user_message=body.user_message,
        )
    ]
    if body.prompt_override is not None:
        rendered_b = _render_prompt_text(
            body.prompt_override,
            prompt_key=body.prompt_key,
            variables=body.variables,
        )
        variants.append(
            await _run_variant(
                variant_id="B",
                rendered=rendered_b,
                user_message=body.user_message,
            )
        )
    return PromptRunOut(
        configuration_id=body.configuration_id,
        prompt_key=body.prompt_key,
        variants=variants,
    )


class ToolRunRequest(BaseModel):
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolRunOut(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None
    elapsed_ms: float


@router.get("/tools/catalog")
async def get_tools_catalog() -> dict[str, Any]:
    return await asyncio.to_thread(list_tool_catalog)


@router.post("/tools/run", response_model=ToolRunOut)
async def post_tools_run(body: ToolRunRequest) -> ToolRunOut:
    try:
        out = await asyncio.to_thread(run_agent_tool, body.tool_name, body.arguments)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ToolRunOut(
        tool_name=str(out["tool_name"]),
        arguments=dict(out["arguments"]),
        result=out["result"],
        error=out["error"],
        elapsed_ms=float(out["elapsed_ms"]),
    )


class ImageReactOut(BaseModel):
    persona_id: str
    persona_name: str
    image_description: str
    reaction: str
    lexicon_label: str
    locale: Locale
    temperature: float
    ssr: dict[str, Any]
    elapsed_ms: float


@router.post("/image/react", response_model=ImageReactOut)
async def post_image_react(
    persona_id: str = Form(...),
    locale: Locale = Form(default="sv"),
    temperature: float = Form(default=0.1),
    image: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ImageReactOut:
    if temperature <= 0:
        raise HTTPException(status_code=400, detail="temperature must be greater than 0")
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    image_bytes = await image.read()
    try:
        result = await react_to_image(
            session,
            persona=persona,
            image_bytes=image_bytes,
            content_type=image.content_type or "",
            locale=locale,
            temperature=temperature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImageReactOut(**result)
