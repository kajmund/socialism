"""Atomic Word application claim / complete / unresolved."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.database.models import ExpertgranskningResult, Job
from app.serializers import utcnow
from app.services.expertgranskning import WORD_JOB_KIND
from app.services.word.application import (
    APPLICATION_APPLIED,
    APPLICATION_APPLYING,
    APPLICATION_PENDING,
    APPLICATION_UNRESOLVED,
)
from tests.conftest import mint_access_token, BOLAG_USER_ID

_REQUEST = {
    "panel_id": 1,
    "customer_id": 1,
    "owner_user_id": "00000000-0000-4000-8000-aaaaaaaaaaaa",
    "doc_id": "doc-claim",
    "sections": [
        {
            "heading": "Avtal",
            "heading_style": "Heading 1",
            "heading_paragraph_index": 0,
            "paragraphs": [
                {"index": 1, "text": "Detta stycke är tillräckligt långt.", "style": "Normal"}
            ],
        }
    ],
}


async def _seed_result(factory, *, result_id: str = "egr_claim_1") -> tuple[str, str]:
    async with factory() as session:
        job = Job(
            id=f"job-{result_id}",
            customer_id=1,
            kind=WORD_JOB_KIND,
            status="running",
            label="Word claim",
            request=_REQUEST,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        row = ExpertgranskningResult(
            id=result_id,
            job_id=job.id,
            customer_id=1,
            section_index=0,
            paragraph_index=1,
            expert_id="slot_1",
            expert_namn="Anna",
            kommentar="Skärp ingressen.",
            is_heading_suggestion=False,
            comment_id=None,
            status=APPLICATION_PENDING,
            created_at=utcnow(),
        )
        session.add_all([job, row])
        await session.commit()
        return job.id, row.id


@pytest.mark.asyncio
async def test_claim_pending_then_complete_applied(client_db):
    client, factory = client_db
    job_id, result_id = await _seed_result(factory)
    claimed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/claim",
        json={"application_id": "app-1"},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["status"] == APPLICATION_APPLYING
    assert claimed.json()["application_id"] == "app-1"
    assert claimed.json()["anchor"]["reviewed_text"] == "Detta stycke är tillräckligt långt."

    again = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/claim",
        json={"application_id": "app-1"},
    )
    assert again.status_code == 200
    assert again.json()["status"] == APPLICATION_APPLYING

    other = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/claim",
        json={"application_id": "app-2"},
    )
    assert other.status_code == 409
    assert other.json()["detail"] == "application_not_claimable"

    done = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/complete",
        json={"application_id": "app-1", "comment_id": "word-1"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == APPLICATION_APPLIED
    assert done.json()["comment_id"] == "word-1"

    replay_claim = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/claim",
        json={"application_id": "app-3"},
    )
    assert replay_claim.status_code == 409


@pytest.mark.asyncio
async def test_mark_unresolved_from_pending_and_applying(client_db):
    client, factory = client_db
    job_id, result_id = await _seed_result(factory, result_id="egr_unresolved_1")
    marked = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/unresolved",
        json={"reason": "stale"},
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["status"] == APPLICATION_UNRESOLVED
    assert marked.json()["application_error"] == "stale"

    again = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/unresolved",
        json={"reason": "stale"},
    )
    assert again.status_code == 200
    assert again.json()["status"] == APPLICATION_UNRESOLVED

    claim = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/claim",
        json={"application_id": "app-x"},
    )
    assert claim.status_code == 409


@pytest.mark.asyncio
async def test_applying_can_be_marked_unresolved_by_owner(client_db):
    client, factory = client_db
    job_id, result_id = await _seed_result(factory, result_id="egr_unresolved_2")
    await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/claim",
        json={"application_id": "app-9"},
    )
    stolen = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/unresolved",
        json={"application_id": "app-other", "reason": "missing"},
    )
    assert stolen.status_code == 409

    marked = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/unresolved",
        json={"application_id": "app-9", "reason": "missing"},
    )
    assert marked.status_code == 200
    assert marked.json()["status"] == APPLICATION_UNRESOLVED
    assert marked.json()["application_error"] == "missing"


@pytest.mark.asyncio
async def test_application_endpoints_are_customer_scoped(client_db):
    client, factory = client_db
    job_id, result_id = await _seed_result(factory, result_id="egr_scope_1")
    token = mint_access_token(sub=BOLAG_USER_ID, email="bolag@test.local")
    headers = {"Authorization": f"Bearer {token}"}
    claim = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/claim",
        headers=headers,
        json={"application_id": "app-scope"},
    )
    assert claim.status_code == 403
    complete = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/complete",
        headers=headers,
        json={"application_id": "app-scope", "comment_id": "x"},
    )
    assert complete.status_code == 403
    unresolved = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}/unresolved",
        headers=headers,
        json={"reason": "stale"},
    )
    assert unresolved.status_code == 403


@pytest.mark.asyncio
async def test_legacy_patch_is_removed(client_db):
    client, factory = client_db
    job_id, result_id = await _seed_result(factory, result_id="egr_patch_1")
    patched = await client.patch(
        f"/expertgranskning/word-jobs/{job_id}/results/{result_id}",
        json={"comment_id": "word-legacy"},
    )
    assert patched.status_code in {404, 405}
    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/results")
    assert listed.json()[0]["status"] == APPLICATION_PENDING
    assert listed.json()[0]["comment_id"] is None
