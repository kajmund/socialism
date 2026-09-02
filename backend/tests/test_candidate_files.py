from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_candidate_annual_report_upload_list_download_delete(client: AsyncClient):
    create = await client.post("/dd/campaigns", json={"title": "Filer", "module": "dd"})
    assert create.status_code == 201
    campaign_id = create.json()["id"]

    search = await client.post(
        "/dd/sourcing/search",
        json={"criteria": {"alder_min": 0, "alder_max": 100, "omrade": "", "resultat": "oavsett"}},
    )
    assert search.status_code == 200
    candidate = search.json()["candidates"][0]
    patched = await client.patch(
        f"/dd/campaigns/{campaign_id}",
        json={"candidates": [candidate]},
    )
    assert patched.status_code == 200
    candidate_id = candidate["id"]

    pdf = b"%PDF-1.4 test-arsredovisning"
    uploaded = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/files",
        files={"file": ("bokslut-2024.pdf", pdf, "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["filename"] == "bokslut-2024.pdf"
    assert body["kind"] == "annual_report"
    assert body["size_bytes"] == len(pdf)
    file_id = body["id"]

    listed = await client.get(f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/files")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == file_id

    downloaded = await client.get(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/files/{file_id}"
    )
    assert downloaded.status_code == 200
    assert downloaded.content == pdf
    assert "bokslut-2024.pdf" in downloaded.headers.get("content-disposition", "")

    deleted = await client.delete(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/files/{file_id}"
    )
    assert deleted.status_code == 204
    empty = await client.get(f"/dd/campaigns/{campaign_id}/candidates/{candidate_id}/files")
    assert empty.json() == []


@pytest.mark.asyncio
async def test_candidate_file_rejects_unknown_candidate(client: AsyncClient):
    create = await client.post("/dd/campaigns", json={"title": "Tom", "module": "dd"})
    campaign_id = create.json()["id"]
    resp = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/missing/files",
        files={"file": ("x.pdf", b"%PDF-1.4 x", "application/pdf")},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_candidate_file_rejects_non_pdf(client: AsyncClient):
    create = await client.post("/dd/campaigns", json={"title": "Fel fil", "module": "dd"})
    campaign_id = create.json()["id"]
    search = await client.post(
        "/dd/sourcing/search",
        json={"criteria": {"alder_min": 0, "alder_max": 100, "omrade": "", "resultat": "oavsett"}},
    )
    candidate = search.json()["candidates"][0]
    await client.patch(f"/dd/campaigns/{campaign_id}", json={"candidates": [candidate]})
    resp = await client.post(
        f"/dd/campaigns/{campaign_id}/candidates/{candidate['id']}/files",
        files={"file": ("notes.txt", b"hej", "text/plain")},
    )
    assert resp.status_code == 400
