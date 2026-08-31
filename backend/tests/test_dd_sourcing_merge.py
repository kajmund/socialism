"""Tests for sourcing candidate merge on re-run."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.dd.campaigns import merge_sourcing_candidates
from app.services.dd.schemas import DdCandidateCompany


def _candidate(
    orgnr: str,
    *,
    namn: str = "Test AB",
    alder_ar: int = 10,
) -> DdCandidateCompany:
    import hashlib

    return DdCandidateCompany(
        id=hashlib.sha256(orgnr.encode()).hexdigest()[:16],
        namn=namn,
        organisationsnummer=orgnr,
        alder_ar=alder_ar,
        omrade="Stockholm",
        resultat="vinst",
        omsattning_sek=1_000_000,
        anstallda=5,
        beskrivning="Test",
    )


def test_merge_sourcing_upserts_by_orgnr_and_keeps_existing():
    existing = [_candidate("556111-1111", namn="Old name")]
    incoming = [_candidate("556111-1111", namn="New name"), _candidate("556222-2222", namn="Other AB")]

    merged = merge_sourcing_candidates(existing, incoming)

    assert len(merged) == 2
    assert merged[0].organisationsnummer == "556111-1111"
    assert merged[0].namn == "New name"
    assert merged[1].organisationsnummer == "556222-2222"


def test_merge_sourcing_never_drops_existing_without_incoming_match():
    kept = _candidate("556333-3333", namn="Kept AB")
    existing = [kept, _candidate("556444-4444")]
    incoming = [_candidate("556555-5555", namn="Fresh AB")]

    merged = merge_sourcing_candidates(existing, incoming)

    assert {c.organisationsnummer for c in merged} == {
        "556333-3333",
        "556444-4444",
        "556555-5555",
    }


def test_merge_sourcing_preserves_existing_id_when_orgnr_matches():
    """Chat/Allabolag use orgnr as id; mock sourcing uses hash — upsert must keep the first id."""
    existing = [
        DdCandidateCompany(
            id="556123-4567",
            namn="Chat AB",
            organisationsnummer="556123-4567",
            alder_ar=10,
            omrade="Stockholm",
            resultat="vinst",
            omsattning_sek=1_000_000,
            anstallda=5,
            beskrivning="From sourcing chat",
        )
    ]
    incoming = [_candidate("556123-4567", namn="Mock refresh")]

    merged = merge_sourcing_candidates(
        existing,
        incoming,
        protected_candidate_ids={"556123-4567"},
    )

    assert len(merged) == 1
    assert merged[0].id == "556123-4567"
    assert merged[0].namn == "Mock refresh"


def test_merge_sourcing_keeps_protected_candidate_ids():
    protected = _candidate("556666-6666", namn="Protected AB")
    existing = [protected]
    incoming: list[DdCandidateCompany] = []

    merged = merge_sourcing_candidates(
        existing,
        incoming,
        protected_candidate_ids={protected.id},
    )

    assert len(merged) == 1
    assert merged[0].id == protected.id


@pytest.mark.asyncio
async def test_sourcing_rerun_preserves_candidate_with_panel_run(client: AsyncClient):
    create = await client.post(
        "/dd/campaigns",
        json={
            "title": "Merge test",
            "criteria": {"alder_min": 0, "alder_max": 50, "omrade": "", "resultat": "oavsett"},
        },
    )
    assert create.status_code == 201
    campaign_id = create.json()["id"]

    first = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    assert first.status_code == 200
    first_candidates = first.json()["candidates"]
    assert len(first_candidates) >= 1
    target = first_candidates[0]

    session_resp = await client.post(
        f"/dd/campaigns/{campaign_id}/panel-sessions",
        json={"campaign_id": campaign_id, "candidate_id": target["id"]},
    )
    assert session_resp.status_code == 201

    await client.patch(
        f"/dd/campaigns/{campaign_id}",
        json={"criteria": {"alder_min": 0, "alder_max": 1, "omrade": "Nowhere", "resultat": "vinst"}},
    )

    second = await client.post(f"/dd/campaigns/{campaign_id}/sourcing/run")
    assert second.status_code == 200
    second_ids = {c["id"] for c in second.json()["candidates"]}

    assert target["id"] in second_ids

    detail = await client.get(f"/dd/campaigns/{campaign_id}")
    assert detail.status_code == 200
    runs = detail.json()["candidate_runs"]
    assert any(row["candidate_id"] == target["id"] for row in runs)
