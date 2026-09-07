from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from httpx import AsyncClient

from app.services.object_storage import (
    KIND_UNDERLAG,
    MAX_UNDERLAG_BYTES,
    UNDERLAG_DOCX_TYPE,
    get_object_storage,
)
from app.services.underlag_extract import extract_underlag_text
from tests.conftest import USER_USER_ID


def _minimal_docx(paragraph: str) -> bytes:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)
    return buf.getvalue()


def test_extract_underlag_plaintext_ok_empty_failed():
    text, status = extract_underlag_text("text/plain", "Hej underlag\n".encode())
    assert status == "ok"
    assert text == "Hej underlag"
    empty, empty_status = extract_underlag_text("text/markdown", b"   \n")
    assert empty is None
    assert empty_status == "empty"
    failed, failed_status = extract_underlag_text("text/plain", b"\xff\xfe")
    assert failed is None
    assert failed_status == "failed"


def test_extract_underlag_docx_markdown():
    data = _minimal_docx("Rubrik från docx")
    text, status = extract_underlag_text(UNDERLAG_DOCX_TYPE, data)
    assert status == "ok"
    assert "Rubrik från docx" in (text or "")


def test_extract_underlag_broken_pdf_is_failed():
    text, status = extract_underlag_text("application/pdf", b"%PDF-1.4 not-a-real-pdf")
    assert text is None
    assert status == "failed"


def test_extract_underlag_unsupported_type():
    text, status = extract_underlag_text("image/png", b"\x89PNG")
    assert text is None
    assert status == "unsupported"


@pytest.mark.asyncio
async def test_underlag_upload_list_get_is_owner_scoped(
    client: AsyncClient, user_token: str, admin_token: str
):
    client.headers["Authorization"] = f"Bearer {user_token}"
    uploaded = await client.post(
        "/underlag",
        params={"module": "expertgranskning"},
        files={"file": ("brief.txt", "Personligt underlag.\n".encode(), "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["filename"] == "brief.txt"
    assert body["kind"] == KIND_UNDERLAG
    assert body["owner_user_id"] == USER_USER_ID
    assert body["extraction_status"] == "ok"
    assert body["extracted_text"] == "Personligt underlag."
    object_id = body["id"]

    storage = get_object_storage()
    keys = set(storage.buckets["devbrains"])
    assert any(
        key.startswith(f"expertgranskning/underlag/{USER_USER_ID}/{object_id}/") for key in keys
    )

    listed = await client.get("/underlag", params={"module": "expertgranskning"})
    assert listed.status_code == 200
    listing = listed.json()
    assert listing["folder_id"] is None
    assert listing["folders"] == []
    assert [row["id"] for row in listing["files"]] == [object_id]
    assert listing["files"][0]["folder_id"] is None
    assert "extracted_text" not in listing["files"][0] or listing["files"][0].get("extracted_text") is None

    fetched = await client.get(f"/underlag/{object_id}")
    assert fetched.status_code == 200
    assert fetched.json()["extracted_text"] == "Personligt underlag."

    client.headers["Authorization"] = f"Bearer {admin_token}"
    admin_listed = await client.get("/underlag", params={"module": "expertgranskning"})
    assert admin_listed.status_code == 200
    assert admin_listed.json()["files"] == []
    assert admin_listed.json()["folders"] == []

    admin_get = await client.get(f"/underlag/{object_id}")
    assert admin_get.status_code == 404


@pytest.mark.asyncio
async def test_underlag_rejects_unknown_module_and_wrong_type(user_client: AsyncClient):
    unknown = await user_client.post(
        "/underlag",
        params={"module": "not-a-module"},
        files={"file": ("brief.txt", b"x", "text/plain")},
    )
    assert unknown.status_code == 400
    wrong = await user_client.post(
        "/underlag",
        params={"module": "expertgranskning"},
        files={"file": ("notes.exe", b"MZ", "application/octet-stream")},
    )
    assert wrong.status_code == 400


@pytest.mark.asyncio
async def test_underlag_rejects_oversize(user_client: AsyncClient):
    payload = b"a" * (MAX_UNDERLAG_BYTES + 1)
    resp = await user_client.post(
        "/underlag",
        params={"module": "expertgranskning"},
        files={"file": ("huge.txt", payload, "text/plain")},
    )
    assert resp.status_code == 400
    assert "20 MB" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_underlag_folders_are_owner_scoped_and_hold_files(
    client: AsyncClient, user_token: str, admin_token: str
):
    client.headers["Authorization"] = f"Bearer {user_token}"
    created = await client.post(
        "/underlag/folders",
        json={"module": "expertgranskning", "name": "  Kampanj 2024  "},
    )
    assert created.status_code == 201, created.text
    folder = created.json()
    assert folder["name"] == "Kampanj 2024"
    assert folder["parent_id"] is None
    folder_id = folder["id"]

    duplicate = await client.post(
        "/underlag/folders",
        json={"module": "expertgranskning", "name": "Kampanj 2024"},
    )
    assert duplicate.status_code == 400

    slash = await client.post(
        "/underlag/folders",
        json={"module": "expertgranskning", "name": "a/b"},
    )
    assert slash.status_code == 400

    nested = await client.post(
        "/underlag/folders",
        json={"module": "expertgranskning", "name": "Q3", "parent_id": folder_id},
    )
    assert nested.status_code == 201, nested.text

    uploaded = await client.post(
        "/underlag",
        params={"module": "expertgranskning", "folder_id": folder_id},
        files={"file": ("inside.txt", b"I mappen\n", "text/plain")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["folder_id"] == folder_id

    root = await client.get("/underlag", params={"module": "expertgranskning"})
    assert root.status_code == 200
    assert [row["id"] for row in root.json()["folders"]] == [folder_id]
    assert root.json()["files"] == []

    inside = await client.get(
        "/underlag",
        params={"module": "expertgranskning", "folder_id": folder_id},
    )
    assert inside.status_code == 200
    assert [row["name"] for row in inside.json()["folders"]] == ["Q3"]
    assert [row["filename"] for row in inside.json()["files"]] == ["inside.txt"]

    tree = await client.get("/underlag/folders", params={"module": "expertgranskning"})
    assert tree.status_code == 200
    tree_names = sorted(row["name"] for row in tree.json())
    assert tree_names == ["Kampanj 2024", "Q3"]
    nested_row = next(row for row in tree.json() if row["name"] == "Q3")
    assert nested_row["parent_id"] == folder_id

    missing_parent = await client.post(
        "/underlag/folders",
        json={"module": "expertgranskning", "name": "x", "parent_id": "missing"},
    )
    assert missing_parent.status_code == 404

    client.headers["Authorization"] = f"Bearer {admin_token}"
    admin_root = await client.get("/underlag", params={"module": "expertgranskning"})
    assert admin_root.json()["folders"] == []
    admin_tree = await client.get("/underlag/folders", params={"module": "expertgranskning"})
    assert admin_tree.status_code == 200
    assert admin_tree.json() == []
    admin_inside = await client.get(
        "/underlag",
        params={"module": "expertgranskning", "folder_id": folder_id},
    )
    assert admin_inside.status_code == 404


@pytest.mark.asyncio
async def test_underlag_move_delete_and_file_download(
    client: AsyncClient, user_token: str, admin_token: str
):
    client.headers["Authorization"] = f"Bearer {user_token}"
    folder = await client.post(
        "/underlag/folders",
        json={"module": "expertgranskning", "name": "Arkiv"},
    )
    assert folder.status_code == 201, folder.text
    folder_id = folder.json()["id"]

    uploaded = await client.post(
        "/underlag",
        params={"module": "expertgranskning"},
        files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    object_id = uploaded.json()["id"]
    assert uploaded.json()["folder_id"] is None

    moved_in = await client.patch(f"/underlag/{object_id}", json={"folder_id": folder_id})
    assert moved_in.status_code == 200, moved_in.text
    assert moved_in.json()["folder_id"] == folder_id

    root = await client.get("/underlag", params={"module": "expertgranskning"})
    assert root.status_code == 200
    assert root.json()["files"] == []

    inside = await client.get(
        "/underlag",
        params={"module": "expertgranskning", "folder_id": folder_id},
    )
    assert inside.status_code == 200
    assert [row["id"] for row in inside.json()["files"]] == [object_id]

    moved_out = await client.patch(f"/underlag/{object_id}", json={"folder_id": None})
    assert moved_out.status_code == 200, moved_out.text
    assert moved_out.json()["folder_id"] is None

    missing_folder = await client.patch(
        f"/underlag/{object_id}", json={"folder_id": "missing"}
    )
    assert missing_folder.status_code == 404

    file_resp = await client.get(f"/underlag/{object_id}/file")
    assert file_resp.status_code == 200
    assert file_resp.content == b"%PDF-1.4 fake"
    assert "application/pdf" in (file_resp.headers.get("content-type") or "")
    assert "inline" in (file_resp.headers.get("content-disposition") or "")

    client.headers["Authorization"] = f"Bearer {admin_token}"
    admin_move = await client.patch(f"/underlag/{object_id}", json={"folder_id": folder_id})
    assert admin_move.status_code == 404
    admin_file = await client.get(f"/underlag/{object_id}/file")
    assert admin_file.status_code == 404
    admin_delete = await client.delete(f"/underlag/{object_id}")
    assert admin_delete.status_code == 404

    client.headers["Authorization"] = f"Bearer {user_token}"
    deleted = await client.delete(f"/underlag/{object_id}")
    assert deleted.status_code == 204

    gone = await client.get(f"/underlag/{object_id}")
    assert gone.status_code == 404
    gone_file = await client.get(f"/underlag/{object_id}/file")
    assert gone_file.status_code == 404

    storage = get_object_storage()
    keys = set(storage.buckets.get("devbrains", {}))
    assert not any(
        key.startswith(f"expertgranskning/underlag/{USER_USER_ID}/{object_id}/") for key in keys
    )


def test_expertgranskning_report_renders_document_as_markdown():
    from app.services.expertgranskning.report_html import render_expertgranskning_html

    html = render_expertgranskning_html(
        title="T",
        locale="sv",
        document_text="**fet** text",
        summary="ok",
        transcript=[],
        session_id="s1",
    )
    assert "document-body" not in html
    assert "<strong>fet</strong>" in html
    assert 'class="explainer md-body"' in html
