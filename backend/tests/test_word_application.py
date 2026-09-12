"""Atomic WordAction application claim / complete / unresolved / dismiss."""

from __future__ import annotations

import asyncio

import pytest

from app.database.models import Job, WordAction
from app.serializers import utcnow
from app.services.expertgranskning import WORD_JOB_KIND
from app.services.word.application import (
    APPLICATION_APPLIED,
    APPLICATION_APPLYING,
    APPLICATION_DISMISSED,
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

_ANCHOR = {
    "paragraph_index": 1,
    "unique_local_id": None,
    "reviewed_text": "Detta stycke är tillräckligt långt.",
    "text_hash": "frozen-hash",
    "previous_text_hash": None,
    "next_text_hash": None,
    "word_session_id": None,
}


async def _seed_action(factory, *, action_id: str = "wa_claim_1") -> tuple[str, str]:
    async with factory() as session:
        job = Job(
            id=f"job-{action_id}",
            customer_id=1,
            kind=WORD_JOB_KIND,
            status="running",
            label="Word claim",
            request=_REQUEST,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        row = WordAction(
            id=action_id,
            job_id=job.id,
            customer_id=1,
            source_type="expert_review_result",
            source_id=f"src-{action_id}",
            source_ordinal=0,
            action_type="comment",
            anchor=_ANCHOR,
            content="Anna: Skärp ingressen.",
            explanation=None,
            status=APPLICATION_PENDING,
            created_at=utcnow(),
        )
        session.add_all([job, row])
        await session.commit()
        return job.id, row.id


@pytest.mark.asyncio
async def test_claim_pending_then_complete_applied(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory)
    claimed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
        json={"application_id": "app-1"},
    )
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["status"] == APPLICATION_APPLYING
    assert claimed.json()["application_id"] == "app-1"
    assert claimed.json()["anchor"]["reviewed_text"] == "Detta stycke är tillräckligt långt."
    assert claimed.json()["content"] == "Anna: Skärp ingressen."

    again = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
        json={"application_id": "app-1"},
    )
    assert again.status_code == 200
    assert again.json()["status"] == APPLICATION_APPLYING

    other = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
        json={"application_id": "app-2"},
    )
    assert other.status_code == 409
    assert other.json()["detail"] == "application_not_claimable"

    done = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/complete",
        json={"application_id": "app-1", "word_artifact_id": "word-1"},
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == APPLICATION_APPLIED
    assert done.json()["word_artifact_id"] == "word-1"

    replay_claim = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
        json={"application_id": "app-3"},
    )
    assert replay_claim.status_code == 409


@pytest.mark.asyncio
async def test_mark_unresolved_from_pending_and_applying(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_unresolved_1")
    marked = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/unresolved",
        json={"reason": "stale"},
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["status"] == APPLICATION_UNRESOLVED
    assert marked.json()["application_error"] == "stale"

    again = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/unresolved",
        json={"reason": "stale"},
    )
    assert again.status_code == 200
    assert again.json()["status"] == APPLICATION_UNRESOLVED

    claim = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
        json={"application_id": "app-x"},
    )
    assert claim.status_code == 409


@pytest.mark.asyncio
async def test_applying_can_be_marked_unresolved_by_owner(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_unresolved_2")
    await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
        json={"application_id": "app-9"},
    )
    stolen = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/unresolved",
        json={"application_id": "app-other", "reason": "missing"},
    )
    assert stolen.status_code == 409

    marked = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/unresolved",
        json={"application_id": "app-9", "reason": "missing"},
    )
    assert marked.status_code == 200
    assert marked.json()["status"] == APPLICATION_UNRESOLVED
    assert marked.json()["application_error"] == "missing"


@pytest.mark.asyncio
async def test_application_endpoints_are_customer_scoped(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_scope_1")
    token = mint_access_token(sub=BOLAG_USER_ID, email="bolag@test.local")
    headers = {"Authorization": f"Bearer {token}"}
    claim = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
        headers=headers,
        json={"application_id": "app-scope"},
    )
    assert claim.status_code == 403
    complete = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/complete",
        headers=headers,
        json={"application_id": "app-scope", "word_artifact_id": "x"},
    )
    assert complete.status_code == 403
    unresolved = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/unresolved",
        headers=headers,
        json={"reason": "stale"},
    )
    assert unresolved.status_code == 403


@pytest.mark.asyncio
async def test_action_id_alone_is_not_enough_to_mutate(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_wrong_job")
    other = await _seed_action(factory, action_id="wa_other_job")
    stolen = await client.post(
        f"/expertgranskning/word-jobs/{other[0]}/actions/{action_id}/claim",
        json={"application_id": "app-cross"},
    )
    assert stolen.status_code == 404
    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")
    assert listed.json()[0]["status"] == APPLICATION_PENDING


@pytest.mark.asyncio
async def test_legacy_result_application_routes_are_removed(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_patch_1")
    patched = await client.patch(
        f"/expertgranskning/word-jobs/{job_id}/results/{action_id}",
        json={"comment_id": "word-legacy"},
    )
    assert patched.status_code in {404, 405}
    claimed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/results/{action_id}/claim",
        json={"application_id": "app-legacy"},
    )
    assert claimed.status_code == 404
    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")
    assert listed.json()[0]["status"] == APPLICATION_PENDING
    assert listed.json()[0]["word_artifact_id"] is None


@pytest.mark.asyncio
async def test_dismiss_pending_is_idempotent_and_persists(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_dismiss_1")
    dismissed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/dismiss"
    )
    assert dismissed.status_code == 200, dismissed.text
    body = dismissed.json()
    assert body["status"] == APPLICATION_DISMISSED
    assert body["application_id"] is None
    assert body["word_artifact_id"] is None
    assert body["application_error"] is None

    again = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/dismiss"
    )
    assert again.status_code == 200
    assert again.json()["status"] == APPLICATION_DISMISSED
    assert again.json()["application_id"] is None
    assert again.json()["word_artifact_id"] is None

    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")
    assert listed.json()[0]["status"] == APPLICATION_DISMISSED
    assert listed.json()[0]["id"] == action_id


@pytest.mark.asyncio
async def test_dismiss_unresolved_keeps_reason_and_creates_no_artifact(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_dismiss_unresolved")
    marked = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/unresolved",
        json={"reason": "stale"},
    )
    assert marked.status_code == 200
    dismissed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/dismiss"
    )
    assert dismissed.status_code == 200, dismissed.text
    body = dismissed.json()
    assert body["status"] == APPLICATION_DISMISSED
    assert body["application_error"] == "stale"
    assert body["word_artifact_id"] is None
    assert body["application_id"] is None


@pytest.mark.asyncio
async def test_applied_and_applying_cannot_be_dismissed(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_dismiss_applied")
    await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
        json={"application_id": "app-applied"},
    )
    applying = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/dismiss"
    )
    assert applying.status_code == 409
    assert applying.json()["detail"] == "application_not_dismissible"
    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")
    assert listed.json()[0]["status"] == APPLICATION_APPLYING

    await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/complete",
        json={"application_id": "app-applied", "word_artifact_id": "word-keep"},
    )
    applied = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/dismiss"
    )
    assert applied.status_code == 409
    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")
    assert listed.json()[0]["status"] == APPLICATION_APPLIED
    assert listed.json()[0]["word_artifact_id"] == "word-keep"


@pytest.mark.asyncio
async def test_dismiss_is_customer_scoped(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_dismiss_scope")
    token = mint_access_token(sub=BOLAG_USER_ID, email="bolag@test.local")
    headers = {"Authorization": f"Bearer {token}"}
    dismissed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/dismiss",
        headers=headers,
    )
    assert dismissed.status_code == 403
    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")
    assert listed.json()[0]["status"] == APPLICATION_PENDING


@pytest.mark.asyncio
async def test_claim_then_dismiss_is_rejected(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_claim_wins")
    claimed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
        json={"application_id": "app-a"},
    )
    assert claimed.status_code == 200
    dismissed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/dismiss"
    )
    assert dismissed.status_code == 409
    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")
    assert listed.json()[0]["status"] == APPLICATION_APPLYING
    assert listed.json()[0]["application_id"] == "app-a"


@pytest.mark.asyncio
async def test_dismiss_then_claim_is_rejected(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_dismiss_wins")
    dismissed = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/dismiss"
    )
    assert dismissed.status_code == 200
    claim = await client.post(
        f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
        json={"application_id": "app-b"},
    )
    assert claim.status_code == 409
    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")
    assert listed.json()[0]["status"] == APPLICATION_DISMISSED
    assert listed.json()[0]["application_id"] is None
    assert listed.json()[0]["word_artifact_id"] is None


@pytest.mark.asyncio
async def test_concurrent_claim_and_dismiss_have_one_winner(client_db):
    client, factory = client_db
    job_id, action_id = await _seed_action(factory, action_id="wa_race")
    claimed, dismissed = await asyncio.gather(
        client.post(
            f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/claim",
            json={"application_id": "app-race"},
        ),
        client.post(
            f"/expertgranskning/word-jobs/{job_id}/actions/{action_id}/dismiss"
        ),
    )
    codes = {claimed.status_code, dismissed.status_code}
    assert 200 in codes
    assert 409 in codes
    assert claimed.status_code != dismissed.status_code
    listed = await client.get(f"/expertgranskning/word-jobs/{job_id}/actions")
    status = listed.json()[0]["status"]
    if claimed.status_code == 200:
        assert status == APPLICATION_APPLYING
        assert listed.json()[0]["application_id"] == "app-race"
        assert dismissed.status_code == 409
    else:
        assert status == APPLICATION_DISMISSED
        assert listed.json()[0]["application_id"] is None
        assert listed.json()[0]["word_artifact_id"] is None
        assert claimed.status_code == 409
    assert status in {APPLICATION_APPLYING, APPLICATION_DISMISSED}
    assert not (
        status == APPLICATION_DISMISSED and listed.json()[0]["application_id"] == "app-race"
    )
