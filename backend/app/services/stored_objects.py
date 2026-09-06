"""Persist object metadata and talk to kund+module S3 buckets."""

from __future__ import annotations

import secrets
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Kund, Report, StoredObject, UnderlagFolder
from app.serializers import format_date, utcnow
from app.services.object_storage import (
    KIND_ANNUAL_REPORT,
    KIND_REPORT_HTML,
    KIND_REPORT_JSON,
    KIND_REPORT_SLOTS,
    KIND_UNDERLAG,
    ObjectStorageError,
    bucket_name,
    delete_object,
    ensure_bucket,
    get_object,
    module_prefix,
    put_object,
    safe_filename,
    validate_annual_report,
    validate_underlag,
)
from app.services.underlag_extract import extract_underlag_text


def serialize_stored_object(row: StoredObject) -> dict:
    return {
        "id": row.id,
        "kind": row.kind,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "campaign_id": row.campaign_id,
        "candidate_id": row.candidate_id,
        "report_id": row.report_id,
        "created_at": format_date(row.created_at) if row.created_at else "",
    }


def serialize_underlag(row: StoredObject, *, include_text: bool) -> dict:
    payload = {
        "id": row.id,
        "kind": row.kind,
        "filename": row.filename,
        "content_type": row.content_type,
        "size_bytes": row.size_bytes,
        "module": row.module,
        "owner_user_id": row.owner_user_id,
        "folder_id": row.folder_id,
        "extraction_status": row.extraction_status,
        "created_at": format_date(row.created_at) if row.created_at else "",
    }
    if include_text:
        payload["extracted_text"] = row.extracted_text
    return payload


def serialize_underlag_folder(row: UnderlagFolder) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "parent_id": row.parent_id,
        "created_at": format_date(row.created_at) if row.created_at else "",
    }


def normalize_folder_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("Folder name is required")
    if len(cleaned) > 80:
        raise ValueError("Folder name is too long")
    if "/" in cleaned or "\\" in cleaned or cleaned in {".", ".."}:
        raise ValueError("Invalid folder name")
    return cleaned


async def kund_bucket(session: AsyncSession, customer_id: int) -> tuple[Kund, str]:
    kund = await session.get(Kund, customer_id)
    if kund is None:
        raise LookupError(f"Kund not found: {customer_id}")
    name = bucket_name(kund.slug)
    await ensure_bucket(name)
    return kund, name


async def ensure_kund_bucket(kund: Kund) -> None:
    await ensure_bucket(bucket_name(kund.slug))


async def list_candidate_files(
    session: AsyncSession,
    *,
    campaign_id: int,
    candidate_id: str,
) -> list[StoredObject]:
    result = await session.execute(
        select(StoredObject)
        .where(
            StoredObject.campaign_id == campaign_id,
            StoredObject.candidate_id == candidate_id,
            StoredObject.kind == KIND_ANNUAL_REPORT,
        )
        .order_by(StoredObject.created_at.desc())
    )
    return list(result.scalars().all())


async def upload_annual_report(
    session: AsyncSession,
    *,
    customer_id: int,
    module: str,
    campaign_id: int,
    candidate_id: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> StoredObject:
    resolved_type = validate_annual_report(filename, content_type, data)
    _kund, bucket = await kund_bucket(session, customer_id)
    object_id = secrets.token_hex(16)
    name = safe_filename(filename)
    key = f"{module_prefix(module)}/candidates/{candidate_id}/annual-reports/{object_id}/{name}"
    await put_object(bucket, key, data, resolved_type)
    row = StoredObject(
        id=object_id,
        customer_id=customer_id,
        module=module,
        kind=KIND_ANNUAL_REPORT,
        bucket=bucket,
        object_key=key,
        filename=name,
        content_type=resolved_type,
        size_bytes=len(data),
        campaign_id=campaign_id,
        candidate_id=candidate_id,
        created_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    return row


async def get_underlag_folder(session: AsyncSession, folder_id: str) -> UnderlagFolder | None:
    return await session.get(UnderlagFolder, folder_id)


async def own_underlag_folder(
    row: UnderlagFolder | None,
    *,
    customer_id: int,
    owner_user_id: str,
    module: str,
) -> UnderlagFolder:
    if (
        row is None
        or row.customer_id != customer_id
        or row.owner_user_id != owner_user_id
        or row.module != module
    ):
        raise LookupError("Folder not found")
    return row


async def list_underlag_folders(
    session: AsyncSession,
    *,
    customer_id: int,
    owner_user_id: str,
    module: str,
    parent_id: str | None,
) -> list[UnderlagFolder]:
    result = await session.execute(
        select(UnderlagFolder)
        .where(
            UnderlagFolder.customer_id == customer_id,
            UnderlagFolder.owner_user_id == owner_user_id,
            UnderlagFolder.module == module,
            UnderlagFolder.parent_id == parent_id,
        )
        .order_by(UnderlagFolder.name.asc())
    )
    return list(result.scalars().all())


async def create_underlag_folder(
    session: AsyncSession,
    *,
    customer_id: int,
    owner_user_id: str,
    module: str,
    name: str,
    parent_id: str | None,
) -> UnderlagFolder:
    name = normalize_folder_name(name)
    if parent_id is not None:
        await own_underlag_folder(
            await get_underlag_folder(session, parent_id),
            customer_id=customer_id,
            owner_user_id=owner_user_id,
            module=module,
        )
    existing = await session.execute(
        select(UnderlagFolder).where(
            UnderlagFolder.customer_id == customer_id,
            UnderlagFolder.owner_user_id == owner_user_id,
            UnderlagFolder.module == module,
            UnderlagFolder.parent_id == parent_id,
            UnderlagFolder.name == name,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError("Folder already exists")
    row = UnderlagFolder(
        id=secrets.token_hex(16),
        customer_id=customer_id,
        owner_user_id=owner_user_id,
        module=module,
        name=name,
        parent_id=parent_id,
        created_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    return row


async def list_underlag(
    session: AsyncSession,
    *,
    customer_id: int,
    owner_user_id: str,
    module: str,
    folder_id: str | None = None,
) -> list[StoredObject]:
    result = await session.execute(
        select(StoredObject)
        .where(
            StoredObject.customer_id == customer_id,
            StoredObject.owner_user_id == owner_user_id,
            StoredObject.kind == KIND_UNDERLAG,
            StoredObject.module == module,
            StoredObject.folder_id == folder_id,
        )
        .order_by(StoredObject.created_at.desc())
    )
    return list(result.scalars().all())


async def upload_underlag(
    session: AsyncSession,
    *,
    customer_id: int,
    owner_user_id: str,
    module: str,
    filename: str,
    content_type: str,
    data: bytes,
    folder_id: str | None = None,
) -> StoredObject:
    resolved_type = validate_underlag(filename, content_type, data)
    extracted, status = extract_underlag_text(resolved_type, data)
    if status != "ok":
        extracted = None
    if folder_id is not None:
        await own_underlag_folder(
            await get_underlag_folder(session, folder_id),
            customer_id=customer_id,
            owner_user_id=owner_user_id,
            module=module,
        )
    _kund, bucket = await kund_bucket(session, customer_id)
    object_id = secrets.token_hex(16)
    name = safe_filename(filename)
    key = f"{module_prefix(module)}/underlag/{owner_user_id}/{object_id}/{name}"
    await put_object(bucket, key, data, resolved_type)
    row = StoredObject(
        id=object_id,
        customer_id=customer_id,
        module=module,
        kind=KIND_UNDERLAG,
        bucket=bucket,
        object_key=key,
        filename=name,
        content_type=resolved_type,
        size_bytes=len(data),
        owner_user_id=owner_user_id,
        folder_id=folder_id,
        extracted_text=extracted,
        extraction_status=status,
        created_at=utcnow(),
    )
    session.add(row)
    await session.flush()
    return row


async def get_stored_object(session: AsyncSession, object_id: str) -> StoredObject | None:
    return await session.get(StoredObject, object_id)


async def read_stored_bytes(row: StoredObject) -> tuple[bytes, str]:
    return await get_object(row.bucket, row.object_key)


async def delete_stored_object(session: AsyncSession, row: StoredObject) -> None:
    await delete_object(row.bucket, row.object_key)
    await session.delete(row)


async def delete_objects_for_campaign(session: AsyncSession, campaign_id: int) -> None:
    result = await session.execute(
        select(StoredObject).where(StoredObject.campaign_id == campaign_id)
    )
    rows = list(result.scalars().all())
    for row in rows:
        await delete_object(row.bucket, row.object_key)
        await session.delete(row)


async def delete_objects_for_report(session: AsyncSession, report_id: str) -> None:
    result = await session.execute(select(StoredObject).where(StoredObject.report_id == report_id))
    rows = list(result.scalars().all())
    for row in rows:
        await delete_object(row.bucket, row.object_key)
        await session.delete(row)


async def report_html_object(session: AsyncSession, report_id: str) -> StoredObject | None:
    result = await session.execute(
        select(StoredObject).where(
            StoredObject.report_id == report_id,
            StoredObject.kind == KIND_REPORT_HTML,
        )
    )
    return result.scalar_one_or_none()


async def store_report_artifacts(
    session: AsyncSession,
    report: Report,
    out_dir: Path,
    *,
    module: str,
) -> None:
    _kund, bucket = await kund_bucket(session, report.customer_id)
    files: list[tuple[Path, str, str]] = [
        (out_dir / "report.html", KIND_REPORT_HTML, "text/html; charset=utf-8"),
        (out_dir / "report.slots.json", KIND_REPORT_SLOTS, "application/json"),
    ]
    sidecars = [
        path
        for path in sorted(out_dir.glob("report.*.json"))
        if path.name != "report.slots.json" and path.is_file()
    ]
    if not sidecars:
        raise ObjectStorageError("Report artifacts missing JSON sidecar")
    files.extend((path, KIND_REPORT_JSON, "application/json") for path in sidecars)

    uploaded: list[tuple[str, str, str, str, int]] = []
    for path, kind, content_type in files:
        if not path.is_file():
            raise ObjectStorageError(f"Report artifact missing: {path.name}")
        data = path.read_bytes()
        key = f"{module_prefix(module)}/reports/{report.id}/{path.name}"
        await put_object(bucket, key, data, content_type)
        uploaded.append((key, kind, path.name, content_type, len(data)))

    result = await session.execute(
        select(StoredObject).where(StoredObject.report_id == report.id)
    )
    old_rows = list(result.scalars().all())
    new_keys = {key for key, *_ in uploaded}
    for row in old_rows:
        if row.object_key not in new_keys:
            await delete_object(row.bucket, row.object_key)
        await session.delete(row)

    now = utcnow()
    for key, kind, filename, content_type, size_bytes in uploaded:
        session.add(
            StoredObject(
                id=secrets.token_hex(16),
                customer_id=report.customer_id,
                module=module,
                kind=kind,
                bucket=bucket,
                object_key=key,
                filename=filename,
                content_type=content_type,
                size_bytes=size_bytes,
                report_id=report.id,
                created_at=now,
            )
        )
    await session.flush()
