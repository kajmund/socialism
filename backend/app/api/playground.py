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
from app.services.anchor_store import ensure_default_anchor_sets, row_to_anchor_set
from app.services.playground import (
    compare_ssr_lexicon,
    default_anchor_set,
    rate_case,
)
from app.services.playground_tools import list_tool_catalog, run_agent_tool
from app.services.playground_image import MAX_IMAGE_BYTES, react_to_image
from app.services.playground_image_models import image_model_catalog
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
    anchor_set_id: int | None = None
    labels: list[str] | None = None
    statements: list[str] | None = None
    temperature: float = Field(default=1.0, gt=0)
    human_labels: list[str] | None = None


class CompareRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    locale: Locale = "sv"
    anchor_set_id: int | None = None
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
async def get_anchors(session: AsyncSession = Depends(get_session)) -> AnchorsOut:
    await ensure_default_anchor_sets(session)
    from sqlalchemy import select

    from app.database.models import SsrAnchorSet

    stmt = select(SsrAnchorSet).where(SsrAnchorSet.status == "published")
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    tone: dict[str, AnchorSetOut] = {}
    style: dict[str, AnchorSetOut] = {}
    for row in rows:
        out = _anchor_out(row_to_anchor_set(row))
        out_dict = out.model_dump()
        payload = AnchorSetOut(**out_dict)
        if row.kind == "tone" and row.locale not in tone:
            tone[row.locale] = payload
        if row.kind == "style" and row.locale not in style:
            style[row.locale] = payload
    for loc in ("sv", "en"):
        if loc not in tone:
            raise HTTPException(
                status_code=500,
                detail=f"No published tone anchor set for locale '{loc}'",
            )
        if loc not in style:
            raise HTTPException(
                status_code=500,
                detail=f"No published style anchor set for locale '{loc}'",
            )
    version = rows[0].version if rows else ANCHOR_SET_VERSION
    return AnchorsOut(version=version, tone=tone, style=style)  # type: ignore[arg-type]


@router.post("/ssr/rate")
async def post_ssr_rate(
    body: RateRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    texts = [t.strip() for t in body.texts if t.strip()]
    if not texts:
        raise HTTPException(status_code=400, detail="texts must contain non-empty strings")

    labels = body.labels
    statements = body.statements
    if body.anchor_set_id is not None:
        from app.services.anchor_pool import centroid_vectors_for_set
        from app.services.anchor_store import get_anchor_set_row, row_to_anchor_set

        row = await get_anchor_set_row(session, body.anchor_set_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Anchor set not found")
        anchor = row_to_anchor_set(row)
        labels = list(anchor.labels)
        statements = list(anchor.statements)
        anchor_vectors = await centroid_vectors_for_set(session, row)
        if row.kind != body.dimension:
            raise HTTPException(
                status_code=400,
                detail=f"Anchor set {body.anchor_set_id} is kind={row.kind!r}, not {body.dimension!r}",
            )
        if row.locale != body.locale:
            raise HTTPException(
                status_code=400,
                detail=f"Anchor set locale {row.locale!r} does not match request locale {body.locale!r}",
            )
    else:
        anchor_vectors = None

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
            labels=labels,
            statements=statements,
            temperature=body.temperature,
            human_labels=human,
            anchor_vectors=anchor_vectors,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ssr/compare")
async def post_ssr_compare(
    body: CompareRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    texts = [t.strip() for t in body.texts if t.strip()]
    if not texts:
        raise HTTPException(status_code=400, detail="texts must contain non-empty strings")
    labels = body.labels
    statements = body.statements
    if body.anchor_set_id is not None:
        from app.services.anchor_pool import centroid_vectors_for_set
        from app.services.anchor_store import require_anchor_set_row, row_to_anchor_set

        row = await require_anchor_set_row(session, body.anchor_set_id)
        if row.kind != "tone":
            raise HTTPException(status_code=400, detail="Compare requires a tone anchor set")
        anchor = row_to_anchor_set(row)
        labels = list(anchor.labels)
        statements = list(anchor.statements)
        anchor_vectors = await centroid_vectors_for_set(session, row)
    else:
        anchor_vectors = None
    try:
        return await compare_ssr_lexicon(
            texts,
            locale=body.locale,
            labels=labels,
            statements=statements,
            temperature=body.temperature,
            anchor_vectors=anchor_vectors,
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
    vision_provider: str
    vision_model: str
    reaction_model: str
    ssr: dict[str, Any]
    elapsed_ms: float


@router.get("/image/models")
async def get_image_models() -> dict[str, Any]:
    return image_model_catalog()


@router.post("/image/react", response_model=ImageReactOut)
async def post_image_react(
    persona_id: str = Form(...),
    locale: Locale = Form(default="sv"),
    temperature: float = Form(default=0.1),
    vision_provider: str | None = Form(default=None),
    vision_model: str | None = Form(default=None),
    reaction_model: str | None = Form(default=None),
    image: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ImageReactOut:
    if temperature <= 0:
        raise HTTPException(status_code=400, detail="temperature must be greater than 0")
    persona = await session.get(Persona, persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="Persona not found")
    # Cap read before buffering — validate_image runs after read; unbounded read()
    # would allow multi‑GB uploads to exhaust worker memory.
    image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
    if len(image_bytes) > MAX_IMAGE_BYTES:
        mb = MAX_IMAGE_BYTES // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"Image exceeds {mb} MB limit")
    try:
        result = await react_to_image(
            session,
            persona=persona,
            image_bytes=image_bytes,
            content_type=image.content_type or "",
            locale=locale,
            temperature=temperature,
            vision_provider=vision_provider,
            vision_model=vision_model,
            reaction_model=reaction_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ImageReactOut(**result)
