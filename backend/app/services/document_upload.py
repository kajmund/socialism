"""Workspace upload with database inputs released before conversion and S3."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Kund, StoredObject
from app.database.transaction_state import has_pending_writes
from app.serializers import utcnow
from app.services.object_storage import (
    KIND_UNDERLAG,
    UNDERLAG_DOCX_TYPE,
    bucket_name,
    ensure_bucket,
    module_prefix,
    put_object,
    safe_filename,
    validate_underlag,
)
from app.services.underlag_pdf import UnderlagPdfConversionError, convert_docx_to_pdf_async
from app.services.workspaces import resolve_workspace


@dataclass(frozen=True)
class UnderlagUpload:
    customer_id: int
    owner_user_id: str
    module: str
    filename: str
    content_type: str
    data: bytes
    folder_id: str | None = None
    workspace_id: str | None = None


async def upload_document(session: AsyncSession, upload: UnderlagUpload) -> StoredObject:
    from app.services.stored_objects import get_underlag_folder, own_underlag_folder

    resolved_type = validate_underlag(upload.filename, upload.content_type, upload.data)
    if has_pending_writes(session):
        raise RuntimeError("Upload requires its own transaction boundary")
    await session.rollback()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory.begin() as inputs:
        workspace = await resolve_workspace(
            inputs, customer_id=upload.customer_id, user_id=upload.owner_user_id,
            workspace_id=upload.workspace_id,
        )
        workspace_id = workspace.id
        if upload.folder_id is not None:
            if workspace.kind != "company":
                raise ValueError("Folders belong to the company workspace")
            await own_underlag_folder(
                await get_underlag_folder(inputs, upload.folder_id),
                customer_id=upload.customer_id, owner_user_id=upload.owner_user_id,
                module=upload.module,
            )
        customer = await inputs.get(Kund, upload.customer_id)
        if customer is None:
            raise LookupError("Customer not found")
        bucket = bucket_name(customer.slug)
    name, data, content_type = await _upload_content(upload, resolved_type)
    await ensure_bucket(bucket)
    object_id = secrets.token_hex(16)
    key = f"{module_prefix(upload.module)}/workspaces/{workspace_id}/underlag/{object_id}/{name}"
    await put_object(bucket, key, data, content_type)
    row = StoredObject(
        id=object_id, customer_id=upload.customer_id, workspace_id=workspace_id,
        module=upload.module, kind=KIND_UNDERLAG, bucket=bucket, object_key=key,
        filename=name, content_type=content_type, size_bytes=len(data),
        owner_user_id=upload.owner_user_id, folder_id=upload.folder_id,
        extracted_text=None, extraction_status="pending", knowledge_status="pending",
        knowledge_error=None, knowledge_job_id=None, created_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    return row


async def _upload_content(upload: UnderlagUpload, resolved_type: str) -> tuple[str, bytes, str]:
    name = safe_filename(upload.filename)
    if resolved_type != UNDERLAG_DOCX_TYPE:
        return name, upload.data, resolved_type
    try:
        data = await convert_docx_to_pdf_async(upload.data, filename=name)
    except UnderlagPdfConversionError as exc:
        raise ValueError(str(exc)) from exc
    return f"{Path(name).stem or 'document'}.pdf", data, "application/pdf"
