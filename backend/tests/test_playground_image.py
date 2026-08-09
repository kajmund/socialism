"""Playground image react endpoint."""

from __future__ import annotations

import pytest

from app.llm import set_text_completer
from app.llm.vision import set_vision_completer
from app.services.ssr import set_embedder, tone_anchors


# 1×1 PNG (red pixel)
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _tone_fake_embed():
    anchors = tone_anchors(locale="sv")
    index_by_statement = {s: i for i, s in enumerate(anchors.statements)}

    async def _fake(texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            idx = index_by_statement.get(text)
            if idx is None:
                v = [0.0] * 5
                v[0] = 1.0
                out.append(v)
            else:
                v = [0.0] * 5
                v[idx] = 1.0
                out.append(v)
        return out

    return _fake


@pytest.mark.asyncio
async def test_image_react_success(client):
    create = await client.post(
        "/personas",
        json={
            "name": "Bildtest Persona",
            "age": 35,
            "occ": "Lärare",
            "district": "Centrum",
            "quote": "Test",
            "origin": "manuell",
        },
    )
    assert create.status_code == 201
    persona_id = create.json()["id"]

    async def _mock_vision(_messages: list[dict[str, object]], _mime: str) -> str:
        return "En politisk affisch med text om skolan."

    async def _mock_text(_messages: list[dict[str, str]]) -> str:
        return "Det här känns hoppfullt men jag undrar vem som betalar."

    set_vision_completer(_mock_vision)
    set_text_completer(_mock_text)
    set_embedder(_tone_fake_embed())

    res = await client.post(
        "/playground/image/react",
        data={"persona_id": persona_id, "locale": "sv", "temperature": "0.1"},
        files={"image": ("test.png", _TINY_PNG, "image/png")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["persona_id"] == persona_id
    assert data["persona_name"] == "Bildtest Persona"
    assert "skolan" in data["image_description"]
    assert "hoppfullt" in data["reaction"]
    assert data["ssr"]["tone"]["predicted_label"]
    assert data["ssr"]["style"]["predicted_label"]
    assert data["lexicon_label"] in {"positive", "negative", "neutral"}
    assert data["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_image_react_unknown_persona(client):
    res = await client.post(
        "/playground/image/react",
        data={"persona_id": "missing"},
        files={"image": ("test.png", _TINY_PNG, "image/png")},
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_image_react_bad_type(client):
    create = await client.post(
        "/personas",
        json={
            "name": "P",
            "age": 30,
            "occ": "X",
            "district": "Centrum",
            "quote": "Q",
            "origin": "manuell",
        },
    )
    persona_id = create.json()["id"]
    res = await client.post(
        "/playground/image/react",
        data={"persona_id": persona_id},
        files={"image": ("test.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 400
