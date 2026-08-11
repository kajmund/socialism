"""Tests for SHA256 image caption cache."""

from __future__ import annotations

import pytest

from app.llm.vision import VisionRequest, set_vision_completer
from app.services.playground_image import MAX_IMAGE_BYTES
from app.services.image_cache import (
    clear_image_cache,
    compose_feed_body,
    delete_entry,
    ensure_cached_image,
    get_entry,
    list_entries,
    sha256_hex,
    update_caption,
)

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture(autouse=True)
def _isolate_image_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.image_cache.settings.image_cache_dir", str(tmp_path))
    clear_image_cache()
    yield
    clear_image_cache()


@pytest.mark.asyncio
async def test_ensure_cached_image_vision_then_cache_hit():
    seen: list[VisionRequest] = []

    async def _mock_vision(request: VisionRequest) -> str:
        seen.append(request)
        return "Röd pixel — valaffisch med texten Test."

    set_vision_completer(_mock_vision)
    digest = sha256_hex(_TINY_PNG)

    entry, hit1 = await ensure_cached_image(
        _TINY_PNG,
        content_type="image/png",
        locale="sv",
    )
    assert hit1 is False
    assert entry["sha256"] == digest
    assert "valaffisch" in entry["caption"].lower()
    assert len(seen) == 1

    entry2, hit2 = await ensure_cached_image(
        _TINY_PNG,
        content_type="image/png",
    )
    assert hit2 is True
    assert entry2["caption"] == entry["caption"]
    assert len(seen) == 1


def test_update_caption_and_delete():
    digest = sha256_hex(_TINY_PNG)
    from pathlib import Path

    from app.services import image_cache as mod

    root = Path(mod.settings.image_cache_dir) / "entries"
    root.mkdir(parents=True)
    mod._bytes_path(digest).write_bytes(_TINY_PNG)
    mod._write_meta(
        mod._meta_path(digest),
        {
            "sha256": digest,
            "caption": "Auto",
            "content_type": "image/png",
            "size_bytes": len(_TINY_PNG),
            "vision_provider": "openai",
            "vision_model": "gpt-4o-mini",
            "caption_edited": False,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    )

    updated = update_caption(digest, "Redigerad caption för flera inlägg.")
    assert updated["caption"] == "Redigerad caption för flera inlägg."
    assert updated["caption_edited"] is True

    assert get_entry(digest) is not None
    assert delete_entry(digest) is True
    assert get_entry(digest) is None
    assert list_entries() == []


def test_compose_feed_body_modes():
    assert compose_feed_body(body="", caption="Bara bild") == "Bara bild"
    assert compose_feed_body(body="Hej", caption="Visuellt") == "Hej\n\n[Bild: Visuellt]"
    assert compose_feed_body(body="Hej", caption="") == "Hej"


@pytest.mark.asyncio
async def test_message_image_upload_rejects_oversized(client):
    oversized = _TINY_PNG + b"\x00" * (MAX_IMAGE_BYTES - len(_TINY_PNG) + 1)
    res = await client.post(
        "/messages/images/upload",
        files={"image": ("big.png", oversized, "image/png")},
    )
    assert res.status_code == 400
    assert "MB limit" in res.json()["detail"]


@pytest.mark.asyncio
async def test_image_cache_api(client):
    async def _mock_vision(request: VisionRequest) -> str:
        return "Politisk reklam med blå bakgrund."

    set_vision_completer(_mock_vision)

    res = await client.post(
        "/messages/images/upload",
        files={"image": ("ad.png", _TINY_PNG, "image/png")},
        data={"locale": "sv"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["cache_hit"] is False
    digest = data["entry"]["sha256"]

    res2 = await client.post(
        "/messages/images/upload",
        files={"image": ("ad.png", _TINY_PNG, "image/png")},
    )
    assert res2.status_code == 200
    assert res2.json()["cache_hit"] is True

    res3 = await client.patch(
        f"/messages/images/cache/{digest}",
        json={"caption": "Anpassad caption delad mellan inlägg."},
    )
    assert res3.status_code == 200
    assert res3.json()["caption_edited"] is True

    res4 = await client.get("/messages/images/cache")
    assert res4.status_code == 200
    assert res4.json()["count"] == 1

    res5 = await client.delete(f"/messages/images/cache/{digest}")
    assert res5.status_code == 200
    assert res5.json()["deleted"] is True


@pytest.mark.asyncio
async def test_message_image_only_create(client):
    async def _mock_vision(_request: VisionRequest) -> str:
        return "Endast bild — ingen följtext."

    set_vision_completer(_mock_vision)

    up = await client.post(
        "/messages/images/upload",
        files={"image": ("only.png", _TINY_PNG, "image/png")},
    )
    digest = up.json()["entry"]["sha256"]

    created = await client.post(
        "/messages",
        json={
            "type": "post",
            "title": "Bildannons",
            "body": "",
            "metadata": {"image_sha256": digest},
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["image_sha256"] == digest
    assert "Endast bild" in body["image_caption"]

    bad = await client.post(
        "/messages",
        json={
            "type": "post",
            "title": "Saknar bild",
            "body": "",
        },
    )
    assert bad.status_code == 422
