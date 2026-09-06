from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.database.models import PanelExpertProfile, StoredObject
from app.llm import set_structured_completer
from app.llm.expert_gen import (
    DEFAULT_SUGGEST_COUNT,
    ExpertCandidate,
    ExpertCandidatesOut,
    llm_experts_from_underlag,
)


def _candidates(count: int = DEFAULT_SUGGEST_COUNT) -> list[ExpertCandidate]:
    return [
        ExpertCandidate(
            name=f"Expert {index}",
            description=f"Bedömer aspekt {index}.",
            kompetensomrade=f"Område {index}",
            radgivningsstil="Saklig",
            yrkesbakgrund=f"Bakgrund {index}",
            professionell_anekdot=f"Anekdot {index}.",
        )
        for index in range(1, count + 1)
    ]


def _prompts() -> dict[str, str]:
    return {
        "expert.from_underlag.system": "system {count} {module}",
        "expert.from_underlag.user": "user {count} {module}\n{underlag_text}",
    }


@pytest.mark.asyncio
async def test_llm_experts_from_underlag_one_structured_call():
    seen: list[tuple[list[dict[str, str]], type]] = []

    async def stub(messages: list[dict[str, str]], response_model: type):
        seen.append((messages, response_model))
        return ExpertCandidatesOut(candidates=_candidates(2))

    set_structured_completer(stub)
    out = await llm_experts_from_underlag(
        "  Bolaget har hög skuldsättning.  ",
        2,
        "dd",
        session=None,  # type: ignore[arg-type]
        customer_id=1,
        prompts=_prompts(),
    )
    assert [row.name for row in out] == ["Expert 1", "Expert 2"]
    assert len(seen) == 1
    messages, model = seen[0]
    assert model is ExpertCandidatesOut
    assert "2" in messages[0]["content"]
    assert "Bolaget har hög skuldsättning." in messages[1]["content"]


@pytest.mark.asyncio
async def test_llm_experts_from_underlag_fails_on_empty_text():
    with pytest.raises(ValueError, match="no extracted text"):
        await llm_experts_from_underlag(
            "   \n",
            4,
            "dd",
            session=None,  # type: ignore[arg-type]
            customer_id=1,
            prompts=_prompts(),
        )


@pytest.mark.asyncio
async def test_llm_experts_from_underlag_fails_on_count_mismatch():
    async def stub(_messages: list[dict[str, str]], _response_model: type):
        return ExpertCandidatesOut(candidates=_candidates(1))

    set_structured_completer(stub)
    with pytest.raises(RuntimeError, match="Expected 4 expert candidates"):
        await llm_experts_from_underlag(
            "text",
            4,
            "dd",
            session=None,  # type: ignore[arg-type]
            customer_id=1,
            prompts=_prompts(),
        )


async def _upload_underlag(
    client: AsyncClient, *, module: str = "dd", body: str = "Underlag om förvärvet."
) -> str:
    uploaded = await client.post(
        "/underlag",
        params={"module": module},
        files={"file": ("brief.txt", body.encode(), "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    return uploaded.json()["id"]


@pytest.mark.asyncio
async def test_suggest_experts_returns_list_and_does_not_persist(client_db):
    client, factory = client_db
    underlag_id = await _upload_underlag(client)

    async def stub(_messages: list[dict[str, str]], response_model: type):
        assert response_model is ExpertCandidatesOut
        return ExpertCandidatesOut(candidates=_candidates())

    set_structured_completer(stub)

    async with factory() as session:
        before = (
            await session.execute(PanelExpertProfile.__table__.select())
        ).all()

    listed_before = await client.get(
        "/panel/expert-profiles", params={"module": "dd", "include_inactive": True}
    )
    assert listed_before.status_code == 200

    resp = await client.post(
        "/personas/suggest-from-underlag",
        json={"underlag_id": underlag_id, "module": "dd"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body) == DEFAULT_SUGGEST_COUNT
    assert body[0]["name"] == "Expert 1"
    assert body[0]["kompetensomrade"] == "Område 1"
    assert "id" not in body[0]
    assert "generation_id" not in body[0]

    listed_after = await client.get(
        "/panel/expert-profiles", params={"module": "dd", "include_inactive": True}
    )
    assert listed_after.status_code == 200
    assert [row["id"] for row in listed_after.json()] == [
        row["id"] for row in listed_before.json()
    ]

    async with factory() as session:
        after = (await session.execute(PanelExpertProfile.__table__.select())).all()
    assert len(after) == len(before)


@pytest.mark.asyncio
async def test_suggest_experts_unknown_file_is_404(client: AsyncClient):
    resp = await client.post(
        "/personas/suggest-from-underlag",
        json={"underlag_id": "missing-underlag", "module": "dd"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_suggest_experts_other_owners_file_is_404(
    client: AsyncClient, user_token: str, admin_token: str
):
    client.headers["Authorization"] = f"Bearer {user_token}"
    uploaded = await client.post(
        "/underlag",
        params={"module": "dd"},
        files={"file": ("user.txt", b"Anvandare underlag.", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    underlag_id = uploaded.json()["id"]

    client.headers["Authorization"] = f"Bearer {admin_token}"
    resp = await client.post(
        "/personas/suggest-from-underlag",
        json={"underlag_id": underlag_id, "module": "dd"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_suggest_experts_failed_extraction_is_400(client_db):
    client, factory = client_db
    underlag_id = await _upload_underlag(client)
    async with factory() as session:
        row = await session.get(StoredObject, underlag_id)
        assert row is not None
        row.extraction_status = "failed"
        row.extracted_text = None
        await session.commit()

    resp = await client.post(
        "/personas/suggest-from-underlag",
        json={"underlag_id": underlag_id, "module": "dd"},
    )
    assert resp.status_code == 400
    assert "failed" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_suggest_experts_empty_text_is_400(client_db):
    client, factory = client_db
    underlag_id = await _upload_underlag(client)
    async with factory() as session:
        row = await session.get(StoredObject, underlag_id)
        assert row is not None
        row.extracted_text = "   "
        await session.commit()

    resp = await client.post(
        "/personas/suggest-from-underlag",
        json={"underlag_id": underlag_id, "module": "dd"},
    )
    assert resp.status_code == 400
    assert "no extracted text" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_suggest_experts_module_mismatch_is_400(client: AsyncClient):
    underlag_id = await _upload_underlag(client, module="dd")
    resp = await client.post(
        "/personas/suggest-from-underlag",
        json={"underlag_id": underlag_id, "module": "expertgranskning"},
    )
    assert resp.status_code == 400
    assert "module" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_suggest_experts_unknown_file_is_404_for_user(user_client: AsyncClient):
    resp = await user_client.post(
        "/personas/suggest-from-underlag",
        json={"underlag_id": "x", "module": "dd"},
    )
    assert resp.status_code == 404
