"""Manual PDF selection proves quote geometry and fresh authorization."""

import asyncio
from copy import deepcopy
from dataclasses import dataclass, replace
from io import BytesIO

import pdfplumber
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.api.voice_workspaces import update_workspace
from app.database.base import Base
from app.database.models import Kund, StoredObject, UserAccount
from app.database.workspace_models import VoiceWorkspace, WorkspaceOperation, WorkspaceReference, WorkspaceSource
from app.database.workspaces import Workspace, WorkspaceMembership
from app.schemas.workspace import WorkspacePatch
from app.services.underlag_schemas import DocumentKnowledgeAnchorWrite
from app.services.workspace import selection_verification
from app.services.workspace.containers import WorkspaceContainer
from app.services.workspace.service import add_source, create_workspace, fingerprint
from app.services.workspace.sources import citation, source_version
from app.services.workspace.tools import execute_workspace_tool
from app.services.workspaces import create_client_workspace

QUOTE = "Policy: Customer files stay private. Cite original evidence."
LEFT_LINES = ("Policy:", "Customer files stay private.", "Cite original evidence.")
SOURCE_ID = "synthetic-column-policy"


def _synthetic_pdf(*, first_stream: str | None = None) -> bytes:
    streams = [
        "BT /F1 12 Tf 72 720 Td (Policy:) Tj ET\n"
        "BT /F1 12 Tf 330 720 Td (Unrelated fee: 43.50 SEK.) Tj ET\n"
        "BT /F1 12 Tf 72 680 Td (Cite original evidence.) Tj ET\n"
        "BT /F1 12 Tf 330 680 Td (Other-column reference.) Tj ET\n"
        "BT /F1 12 Tf 72 700 Td (Customer files stay private.) Tj ET\n"
        "BT /F1 12 Tf 330 700 Td (Independent payment date.) Tj ET\n",
        "BT /F1 12 Tf 72 720 Td (Other page without customer policy.) Tj ET\n",
    ]
    if first_stream is not None:
        streams[0] = first_stream
    objects = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: "<< /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, stream in zip((4, 6), streams, strict=True):
        objects[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {page_id + 1} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        objects[page_id + 1] = f"<< /Length {len(stream)} >>\nstream\n{stream}endstream"
    output, offsets = bytearray(b"%PDF-1.1\n"), []
    for identity in range(1, 8):
        offsets.append(len(output))
        output.extend(f"{identity} 0 obj\n{objects[identity]}\nendobj\n".encode())
    xref = len(output)
    output.extend(b"xref\n0 8\n0000000000 65535 f \n")
    for offset in offsets:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer << /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(output)


def _pdf_inputs(data: bytes) -> tuple[str, dict]:
    with pdfplumber.open(BytesIO(data)) as pdf:
        page = pdf.pages[0]
        flat_text = page.extract_text(x_tolerance=3, y_tolerance=3)
        left_words = [word for word in page.extract_words() if word["x1"] < 300]
        rects = []
        for top in sorted({word["top"] for word in left_words}):
            line = [word for word in left_words if word["top"] == top]
            rects.append({"x": min(word["x0"] for word in line) / page.width,
                "y": top / page.height,
                "width": (max(word["x1"] for word in line) - min(word["x0"] for word in line)) / page.width,
                "height": (max(word["bottom"] for word in line) - top) / page.height})
    assert QUOTE not in " ".join(flat_text.split())
    return flat_text, {"anchor_type": "text", "page_number": 1, "locator": "page:1",
        "exact_text": QUOTE, "rects": rects}


@dataclass(frozen=True)
class PDFCase:
    factory: async_sessionmaker
    engine: AsyncEngine
    user_id: str
    workspace_id: str
    parent_id: str
    sibling_id: str
    data: bytes
    anchor: dict


@pytest.fixture
async def pdf_case(tmp_path):
    data = _synthetic_pdf()
    flat_text, anchor = _pdf_inputs(data)
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/pdf-selection.db",
        pool_size=1, max_overflow=0, pool_timeout=.3)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with factory() as session:
        session.add_all([Kund(id=1, name="Synthetic owner", slug="pdf-selection", available_modules=["dd"]),
            Kund(id=2, name="Synthetic foreign tenant", slug="pdf-selection-foreign", available_modules=["dd"])])
        await session.flush()
        user = UserAccount(id="synthetic-policy-owner", email="synthetic-policy@example.test", role="user", kund_id=1)
        session.add(user)
        await session.flush()
        parent = await create_client_workspace(session, customer_id=1, user_id=user.id, name="Synthetic client")
        sibling = await create_client_workspace(session, customer_id=1, user_id=user.id, name="Synthetic sibling")
        workspace = await create_workspace(session, user, title="Synthetic PDF selection", module="dd",
            container=WorkspaceContainer(workspace_id=parent.id))
        session.add(StoredObject(id=SOURCE_ID, customer_id=1, workspace_id=parent.id, owner_user_id=user.id,
            module="dd", kind="underlag", bucket="synthetic-pdf-selection", object_key="columns.pdf",
            filename="columns.pdf", content_type="application/pdf", size_bytes=len(data),
            extraction_status="ok", extracted_text=flat_text, knowledge_status="ready"))
        await session.flush()
        await add_source(session, workspace, SOURCE_ID)
        case = PDFCase(factory, engine, user.id, workspace.id, parent.id, sibling.id, data, anchor)
        await session.commit()
    yield case
    await engine.dispose()


def _request(case: PDFCase, *, key="select-original", revision=0, state=None) -> WorkspacePatch:
    state = state or {"view": "documents", "documents": [{"source_id": SOURCE_ID}],
        "selection": {"source_id": SOURCE_ID, "anchor": deepcopy(case.anchor)}}
    return WorkspacePatch(expected_revision=revision, idempotency_key=key, state=state)


async def _patch(case: PDFCase, body: WorkspacePatch) -> dict:
    async with case.factory() as session:
        user = await session.get(UserAccount, case.user_id)
        retained_authorization = [await session.get(Kund, 1),
            await session.get(Workspace, case.parent_id),
            await session.get(WorkspaceMembership, (case.parent_id, case.user_id)),
            await session.get(WorkspaceSource, (case.workspace_id, SOURCE_ID))]
        assert all(row is not None for row in retained_authorization)
        return await update_workspace(case.workspace_id, body, session=session, user=user)


def _storage(case: PDFCase, monkeypatch):
    calls = []
    async def get_object(bucket, key):
        assert case.engine.pool.checkedout() == 0
        async with case.factory() as other:
            assert await asyncio.wait_for(other.scalar(text("SELECT 1")), timeout=1) == 1
        calls.append((bucket, key))
        return case.data, "application/pdf"
    monkeypatch.setattr(selection_verification, "get_object", get_object)
    return calls


async def _assert_no_selection_writes(case: PDFCase) -> None:
    async with case.factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceReference)) == 0
        assert await session.scalar(select(func.count()).select_from(WorkspaceOperation)) == 0
        workspace = await session.get(VoiceWorkspace, case.workspace_id)
        if workspace is not None:
            assert workspace.revision == 0 and workspace.state["selection"] is None


async def _unverified_reference(case: PDFCase, anchor: DocumentKnowledgeAnchorWrite) -> tuple[str, dict]:
    async with case.factory() as session:
        workspace = await session.get(VoiceWorkspace, case.workspace_id)
        source = await session.get(StoredObject, SOURCE_ID)
        snapshot = {"title": source.filename, "excerpt": anchor.exact_text, "origin": "synthetic-old-reference"}
        reference = await citation(session, workspace, kind="underlag", source_id=SOURCE_ID,
            version=source_version(source), anchor=anchor.model_dump(), snapshot=snapshot)
        reference_id = reference.id
        await session.commit()
    return reference_id, snapshot


def test_position_selected_column_uses_visual_order_and_preserves_original_quote():
    data = _synthetic_pdf()
    _flat_text, anchor = _pdf_inputs(data)
    assert selection_verification.selected_pdf_quote(data, DocumentKnowledgeAnchorWrite(**anchor)) == QUOTE


def test_normalized_submitted_quote_retains_original_pdf_case():
    data = _synthetic_pdf()
    _flat_text, anchor = _pdf_inputs(data)
    anchor["exact_text"] = QUOTE.swapcase().replace(" ", "\n\t ")
    assert selection_verification.selected_pdf_quote(data, DocumentKnowledgeAnchorWrite(**anchor)) == QUOTE


@pytest.mark.parametrize("changed", [
    {"exact_text": "Policy: Customer files stay public. Cite original evidence."},
    {"page_number": 2, "locator": "page:2"},
    {"page_number": 3, "locator": "page:3"},
    {"locator": "page:2"},
    {"rects": []},
    {"rects": [{"x": .9, "y": .06, "width": .2, "height": .1}]},
    {"rects": [{"x": .52, "y": .06, "width": .45, "height": .1}]},
    {"rects": [{"x": .1, "y": .7, "width": .3, "height": .05}]},
])
def test_forged_quote_page_or_position_is_rejected(changed):
    data = _synthetic_pdf()
    _flat_text, anchor = _pdf_inputs(data)
    with pytest.raises(HTTPException) as error:
        selection_verification.selected_pdf_quote(data, DocumentKnowledgeAnchorWrite(**{**anchor, **changed}))
    assert error.value.status_code == 409 and error.value.detail == "selection_anchor_stale"


async def test_column_selection_releases_only_connection_and_persists_verified_citation(pdf_case, monkeypatch):
    calls = _storage(pdf_case, monkeypatch)
    original = _request(pdf_case)
    arguments = original.model_dump(exclude={"idempotency_key", "expected_revision"})
    result = await _patch(pdf_case, original)
    assert calls == [("synthetic-pdf-selection", "columns.pdf")]
    assert result["revision"] == 1
    reference_id = result["state"]["selection"]["reference_id"]
    async with pdf_case.factory() as session:
        reference = await session.get(WorkspaceReference, reference_id)
        assert reference.snapshot["selection_verified"] is True
        assert reference.snapshot["excerpt"] == reference.anchor["exact_text"] == QUOTE
        assert reference.anchor["rects"] == pdf_case.anchor["rects"]
        operation = await session.scalar(select(WorkspaceOperation))
        assert operation.payload_hash == fingerprint({"tool": "update_workspace", "arguments": arguments, "expected_revision": 0})


async def test_replay_original_request_and_unchanged_zoom_reuse_verified_anchor_without_storage(pdf_case, monkeypatch):
    calls = _storage(pdf_case, monkeypatch)
    payload = _request(pdf_case).model_dump()
    selected = await _patch(pdf_case, WorkspacePatch(**deepcopy(payload)))
    assert await _patch(pdf_case, WorkspacePatch(**deepcopy(payload))) == selected
    state = deepcopy(selected["state"])
    state["documents"][0]["zoom"] = 1.5
    zoomed = await _patch(pdf_case, _request(pdf_case, key="zoom-original", revision=1, state=state))
    assert zoomed["state"]["documents"][0]["zoom"] == 1.5
    assert zoomed["state"]["selection"]["reference_id"] == selected["state"]["selection"]["reference_id"]
    assert len(calls) == 1


@pytest.mark.parametrize("changed,expected_calls", [
    ({"exact_text": "Policy: Customer files stay public. Cite original evidence."}, 1),
    ({"page_number": 2, "locator": "page:2"}, 1),
    ({"rects": [{"x": .52, "y": .06, "width": .45, "height": .1}]}, 2),
])
async def test_modified_known_reference_anchor_is_not_trusted(pdf_case, monkeypatch, *, changed, expected_calls):
    calls = _storage(pdf_case, monkeypatch)
    selected = await _patch(pdf_case, _request(pdf_case))
    state = deepcopy(selected["state"])
    state["selection"]["anchor"].update(changed)
    with pytest.raises(HTTPException) as error:
        await _patch(pdf_case, _request(pdf_case, key="changed-anchor", revision=1, state=state))
    assert error.value.status_code == 409
    assert len(calls) == expected_calls
    async with pdf_case.factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceReference)) == 1
        assert (await session.get(VoiceWorkspace, pdf_case.workspace_id)).revision == 1


async def test_valid_subselection_of_known_reference_is_verified_from_original_pdf(pdf_case, monkeypatch):
    calls = _storage(pdf_case, monkeypatch)
    selected = await _patch(pdf_case, _request(pdf_case))
    state = deepcopy(selected["state"])
    anchor = state["selection"]["anchor"]
    anchor["exact_text"] = LEFT_LINES[1]
    anchor["rects"] = [anchor["rects"][1]]
    subselection = await _patch(pdf_case, _request(pdf_case, key="subselection", revision=1, state=state))
    assert len(calls) == 2
    reference_id = subselection["state"]["selection"]["reference_id"]
    assert reference_id != selected["state"]["selection"]["reference_id"]
    async with pdf_case.factory() as session:
        reference = await session.get(WorkspaceReference, reference_id)
        assert reference.anchor["exact_text"] == reference.snapshot["excerpt"] == LEFT_LINES[1]
        assert reference.snapshot["selection_verified"] is True


async def test_full_document_read_reference_cannot_bypass_manual_pdf_position_proof(pdf_case, monkeypatch):
    calls = _storage(pdf_case, monkeypatch)
    async with pdf_case.factory() as session:
        user = await session.get(UserAccount, pdf_case.user_id)
        read = await execute_workspace_tool(session, workspace_id=pdf_case.workspace_id, user=user,
            tool_name="read_source", arguments={"source_id": SOURCE_ID}, idempotency_key="read-full-document")
        await session.commit()
    anchor = DocumentKnowledgeAnchorWrite(**read["anchor"])
    assert anchor.locator == "document" and anchor.page_number is None and anchor.rects == []
    request = _request(pdf_case)
    request.state.selection.reference_id = read["reference_id"]
    request.state.selection.anchor = anchor
    with pytest.raises(HTTPException) as error:
        await _patch(pdf_case, request)
    assert error.value.status_code == 409 and error.value.detail == "selection_anchor_stale"
    assert calls == []
    async with pdf_case.factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceReference)) == 1
        assert await session.scalar(select(func.count()).select_from(WorkspaceOperation)) == 1
        assert (await session.get(VoiceWorkspace, pdf_case.workspace_id)).revision == 0


async def test_saved_out_of_page_rectangle_is_rejected_even_when_reference_identity_matches(pdf_case, monkeypatch):
    calls = _storage(pdf_case, monkeypatch)
    anchor = DocumentKnowledgeAnchorWrite(**{**pdf_case.anchor,
        "rects": [{"x": .9, "y": .06, "width": .2, "height": .1}]})
    async with pdf_case.factory() as session:
        workspace = await session.get(VoiceWorkspace, pdf_case.workspace_id)
        source = await session.get(StoredObject, SOURCE_ID)
        reference = await citation(session, workspace, kind="underlag", source_id=SOURCE_ID,
            version=source_version(source), anchor=anchor.model_dump(),
            snapshot={"title": source.filename, "excerpt": QUOTE, "selection_verified": True})
        reference_id = reference.id
        await session.commit()
    request = _request(pdf_case)
    request.state.selection.reference_id = reference_id
    request.state.selection.anchor = anchor
    with pytest.raises(HTTPException) as error:
        await _patch(pdf_case, request)
    assert error.value.status_code == 409 and error.value.detail == "selection_anchor_stale"
    assert calls == []
    async with pdf_case.factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceReference)) == 1
        assert await session.scalar(select(func.count()).select_from(WorkspaceOperation)) == 0
        assert (await session.get(VoiceWorkspace, pdf_case.workspace_id)).revision == 0


async def test_unverified_reference_with_wrong_region_requires_original_proof_and_is_rejected(pdf_case, monkeypatch):
    calls = _storage(pdf_case, monkeypatch)
    anchor = DocumentKnowledgeAnchorWrite(**{**pdf_case.anchor,
        "rects": [{"x": .52, "y": .06, "width": .45, "height": .1}]})
    reference_id, original_snapshot = await _unverified_reference(pdf_case, anchor)
    request = _request(pdf_case)
    request.state.selection.reference_id = reference_id
    request.state.selection.anchor = anchor
    with pytest.raises(HTTPException) as error:
        await _patch(pdf_case, request)
    assert error.value.status_code == 409 and error.value.detail == "selection_anchor_stale"
    assert calls == [("synthetic-pdf-selection", "columns.pdf")]
    async with pdf_case.factory() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceReference)) == 1
        assert await session.scalar(select(func.count()).select_from(WorkspaceOperation)) == 0
        assert (await session.get(WorkspaceReference, reference_id)).snapshot == original_snapshot
        assert (await session.get(VoiceWorkspace, pdf_case.workspace_id)).revision == 0


async def test_valid_unverified_reference_gets_new_immutable_verified_reference_then_zoom_reuses_it(pdf_case, monkeypatch):
    calls = _storage(pdf_case, monkeypatch)
    anchor = DocumentKnowledgeAnchorWrite(**pdf_case.anchor)
    old_reference_id, original_snapshot = await _unverified_reference(pdf_case, anchor)
    request = _request(pdf_case)
    request.state.selection.reference_id = old_reference_id
    request.state.selection.anchor = anchor
    selected = await _patch(pdf_case, request)
    new_reference_id = selected["state"]["selection"]["reference_id"]
    assert new_reference_id != old_reference_id
    assert calls == [("synthetic-pdf-selection", "columns.pdf")]
    async with pdf_case.factory() as session:
        old_reference = await session.get(WorkspaceReference, old_reference_id)
        new_reference = await session.get(WorkspaceReference, new_reference_id)
        assert old_reference.snapshot == original_snapshot and "selection_verified" not in old_reference.snapshot
        assert new_reference.snapshot["selection_verified"] is True
        assert new_reference.anchor == old_reference.anchor == anchor.model_dump()
        assert new_reference.identity_key != old_reference.identity_key
        assert new_reference.source_version == old_reference.source_version
        assert await session.scalar(select(func.count()).select_from(WorkspaceReference)) == 2
    state = deepcopy(selected["state"])
    state["documents"][0]["zoom"] = 1.75
    zoomed = await _patch(pdf_case, _request(pdf_case, key="zoom-upgraded", revision=1, state=state))
    assert zoomed["state"]["selection"]["reference_id"] == new_reference_id
    assert len(calls) == 1


async def test_reference_only_display_does_not_verify_or_download_unverified_anchor(pdf_case, monkeypatch):
    calls = _storage(pdf_case, monkeypatch)
    reference_id, original_snapshot = await _unverified_reference(pdf_case, DocumentKnowledgeAnchorWrite(**pdf_case.anchor))
    state = {"view": "documents", "documents": [{"source_id": SOURCE_ID, "reference_id": reference_id}],
        "selection": {"reference_id": reference_id}}
    shown = await _patch(pdf_case, _request(pdf_case, key="show-reference", state=state))
    assert shown["state"]["selection"]["reference_id"] == reference_id
    assert shown["state"]["selection"]["anchor"] is None and shown["state"]["selection"]["source_id"] is None
    assert calls == []
    async with pdf_case.factory() as session:
        assert (await session.get(WorkspaceReference, reference_id)).snapshot == original_snapshot
        assert await session.scalar(select(func.count()).select_from(WorkspaceReference)) == 1


async def test_rejected_new_anchor_does_not_create_operation_or_citation(pdf_case, monkeypatch):
    _storage(pdf_case, monkeypatch)
    request = _request(pdf_case)
    request.state.selection.anchor.exact_text = "Forged quote absent from the original PDF."
    with pytest.raises(HTTPException) as error:
        await _patch(pdf_case, request)
    assert error.value.status_code == 409
    await _assert_no_selection_writes(pdf_case)


async def test_pdf_verification_does_not_commit_unrelated_pending_profile_change(pdf_case, monkeypatch):
    calls = _storage(pdf_case, monkeypatch)
    async with pdf_case.factory() as session:
        user = await session.get(UserAccount, pdf_case.user_id)
        user.first_name = "Unrelated pending edit"
        with pytest.raises(RuntimeError, match="clean transaction"):
            await update_workspace(pdf_case.workspace_id, _request(pdf_case), session=session, user=user)
        await session.rollback()
    assert calls == []
    async with pdf_case.factory() as session:
        assert (await session.get(UserAccount, pdf_case.user_id)).first_name is None
    await _assert_no_selection_writes(pdf_case)


def _revocation(case: PDFCase, boundary: str):
    return {
        "actor_removed": delete(UserAccount).where(UserAccount.id == case.user_id),
        "actor_customer_changed": update(UserAccount).where(UserAccount.id == case.user_id).values(kund_id=2),
        "customer_removed": delete(Kund).where(Kund.id == 1),
        "parent_removed": delete(Workspace).where(Workspace.id == case.parent_id),
        "membership_removed": delete(WorkspaceMembership).where(WorkspaceMembership.workspace_id == case.parent_id,
            WorkspaceMembership.user_id == case.user_id),
        "source_membership_removed": delete(WorkspaceSource).where(WorkspaceSource.workspace_id == case.workspace_id),
        "source_moved": update(StoredObject).where(StoredObject.id == SOURCE_ID).values(workspace_id=case.sibling_id),
        "source_changed": update(StoredObject).where(StoredObject.id == SOURCE_ID).values(extracted_text="Replacement source version."),
    }[boundary]


@pytest.mark.parametrize("boundary", ["actor_removed", "actor_customer_changed", "customer_removed",
    "parent_removed", "membership_removed", "source_membership_removed", "source_moved", "source_changed"])
async def test_authorization_and_source_version_are_rechecked_after_storage_wait(pdf_case, monkeypatch, boundary):
    entered, release = asyncio.Event(), asyncio.Event()
    async def get_object(_bucket, _key):
        assert pdf_case.engine.pool.checkedout() == 0
        entered.set()
        await release.wait()
        return pdf_case.data, "application/pdf"
    monkeypatch.setattr(selection_verification, "get_object", get_object)
    task = asyncio.create_task(_patch(pdf_case, _request(pdf_case)))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert pdf_case.engine.pool.checkedout() == 0
        async with pdf_case.factory.begin() as other:
            await other.execute(_revocation(pdf_case, boundary))
    finally:
        release.set()
    with pytest.raises(HTTPException) as error:
        await task
    assert error.value.status_code == (409 if boundary == "source_changed" else 404)
    await _assert_no_selection_writes(pdf_case)


def _layout_gap_pdf(gap: float = 2) -> bytes:
    # The installed PDF.js inserts layout whitespace here; the source reader joins the glyphs.
    return _synthetic_pdf(first_stream=(
        "BT /F1 12 Tf 72 720 Td (foo) Tj ET\n"
        f"BT /F1 12 Tf {88.68 + gap} 720 Td (bar) Tj ET\n"))


def _character_anchor(data: bytes, quote: str, *, start: int = 0, end: int | None = None) -> DocumentKnowledgeAnchorWrite:
    with pdfplumber.open(BytesIO(data)) as pdf:
        page = pdf.pages[0]
        chars = page.chars[start:end]
        x0, x1 = min(char["x0"] for char in chars), max(char["x1"] for char in chars)
        top, bottom = min(char["top"] for char in chars), max(char["bottom"] for char in chars)
        return DocumentKnowledgeAnchorWrite(page_number=1, locator="page:1", exact_text=quote,
            rects=[{"x": x0 / page.width, "y": top / page.height,
                "width": (x1 - x0) / page.width, "height": (bottom - top) / page.height}])


@pytest.mark.parametrize("gap", [1.5, 2, 2.5, 2.9])
def test_pdfjs_inferred_layout_space_does_not_change_selected_original_characters(gap):
    data = _layout_gap_pdf(gap)
    with pdfplumber.open(BytesIO(data)) as pdf:
        assert "".join(char["text"] for char in pdf.pages[0].chars) == "foobar"
        assert pdf.pages[0].extract_text(x_tolerance=3, y_tolerance=3) == "foobar"
    assert selection_verification.selected_pdf_quote(data, _character_anchor(data, "foo bar")) == "foobar"


def test_partial_word_selection_can_contain_browser_inferred_space():
    data = _layout_gap_pdf()
    anchor = _character_anchor(data, "oo b", start=1, end=4)
    assert selection_verification.selected_pdf_quote(data, anchor) == "oob"


def test_parent_quote_accepts_layout_whitespace_distinct_subselection_before_position_proof():
    anchor = _character_anchor(_layout_gap_pdf(), "oo b", start=1, end=4)
    parent = WorkspaceReference(anchor={"page_number": 1, "locator": "page:1"}, snapshot={"excerpt": "foobar"})
    selection_verification._parent_quote(parent, anchor)


@pytest.mark.parametrize("quote", ["foo baz", "foo1 bar", "foo: bar", "bar foo", "foo ba", "fo bar"])
def test_layout_whitespace_does_not_allow_changed_omitted_or_reordered_original_characters(quote):
    data = _layout_gap_pdf()
    with pytest.raises(HTTPException) as error:
        selection_verification.selected_pdf_quote(data, _character_anchor(data, quote))
    assert error.value.status_code == 409 and error.value.detail == "selection_anchor_stale"


@pytest.mark.parametrize("quote", ["50.00SEK", "150,00SEK", "150.01SEK"])
def test_layout_whitespace_does_not_allow_changed_amount_digits_or_punctuation(quote):
    data = _synthetic_pdf(first_stream="BT /F1 12 Tf 72 720 Td (150.00 SEK) Tj ET\n")
    with pytest.raises(HTTPException) as error:
        selection_verification.selected_pdf_quote(data, _character_anchor(data, quote))
    assert error.value.status_code == 409 and error.value.detail == "selection_anchor_stale"


async def test_layout_subselection_preserves_original_quote_versions_and_private_pool_release(pdf_case, monkeypatch):
    data = _layout_gap_pdf()
    anchor = _character_anchor(data, "foo bar")
    async with pdf_case.factory.begin() as session:
        source = await session.get(StoredObject, SOURCE_ID)
        source.extracted_text, source.size_bytes = "foobar", len(data)
    case = replace(pdf_case, data=data, anchor=anchor.model_dump())
    calls = _storage(case, monkeypatch)
    selected = await _patch(case, _request(case))
    first_id = selected["state"]["selection"]["reference_id"]
    assert await _patch(case, _request(case)) == selected and len(calls) == 1
    state = deepcopy(selected["state"])
    state["selection"]["anchor"] = _character_anchor(data, "oo b", start=1, end=4).model_dump()
    partial = await _patch(case, _request(case, key="layout-subselection", revision=1, state=state))
    second_id = partial["state"]["selection"]["reference_id"]
    assert first_id != second_id and len(calls) == 2
    state = deepcopy(partial["state"])
    state["documents"][0]["zoom"] = 1.75
    zoomed = await _patch(case, _request(case, key="layout-zoom", revision=2, state=state))
    assert zoomed["state"]["selection"]["reference_id"] == second_id and len(calls) == 2
    async with case.factory() as session:
        first = await session.get(WorkspaceReference, first_id)
        second = await session.get(WorkspaceReference, second_id)
        assert first.anchor["exact_text"] == first.snapshot["excerpt"] == "foobar"
        assert second.anchor["exact_text"] == second.snapshot["excerpt"] == "oob"
        assert first.source_version == second.source_version
        assert first.snapshot["selection_verified"] is True and second.snapshot["selection_verified"] is True
        assert await session.scalar(select(func.count()).select_from(WorkspaceReference)) == 2
