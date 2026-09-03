from __future__ import annotations

import pytest

from app.database.models import Report
from app.services.object_storage import (
    ObjectStorageError,
    bucket_name,
    get_object_storage,
    module_prefix,
    safe_filename,
    supabase_s3_endpoint,
    validate_annual_report,
)
from app.services.stored_objects import store_report_artifacts
from tests.conftest import TEST_CUSTOMER_ID


def test_bucket_name_is_kund_slug_only():
    assert bucket_name("bolag-demo") == "bolag-demo"
    assert bucket_name("Devbrains") == "devbrains"


def test_bucket_name_sanitizes():
    assert bucket_name("Bolag Demo!") == "bolag-demo"


def test_module_prefix_is_key_folder():
    assert module_prefix("politik") == "politik"
    assert module_prefix("Due Diligence") == "due-diligence"


def test_supabase_s3_endpoint():
    assert (
        supabase_s3_endpoint("https://pgznofozxkbtdfkaiafl.supabase.co")
        == "https://pgznofozxkbtdfkaiafl.storage.supabase.co/storage/v1/s3"
    )


def test_safe_filename_strips_path():
    assert safe_filename("../../årsredovisning 2024.pdf") == "årsredovisning_2024.pdf"


def test_validate_annual_report_pdf():
    data = b"%PDF-1.4 fake"
    assert validate_annual_report("bokslut.pdf", "application/pdf", data) == "application/pdf"


def test_validate_annual_report_rejects_empty():
    try:
        validate_annual_report("x.pdf", "application/pdf", b"")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_validate_annual_report_rejects_non_pdf_bytes():
    try:
        validate_annual_report("x.pdf", "application/pdf", b"not a pdf")
    except ValueError as exc:
        assert "PDF" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def _write_report_dir(out_dir, *, sidecar_name: str | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    (out_dir / "report.slots.json").write_text("{}", encoding="utf-8")
    if sidecar_name is not None:
        (out_dir / sidecar_name).write_text("{}", encoding="utf-8")


@pytest.mark.asyncio
async def test_store_report_artifacts_accepts_expertgranskning_sidecar(client_db, tmp_path):
    _client, factory = client_db
    out_dir = tmp_path / "rpt_eg"
    _write_report_dir(out_dir, sidecar_name="report.expertgranskning.json")
    async with factory() as session:
        report = Report(
            id="rpt_eg",
            customer_id=TEST_CUSTOMER_ID,
            status="running",
            title="EG",
            locale="sv",
            mode="expertgranskning",
            sources=[],
        )
        session.add(report)
        await session.flush()
        await store_report_artifacts(session, report, out_dir, module="expertgranskning")
        await session.commit()
    storage = get_object_storage()
    keys = set(storage.buckets["devbrains"])
    assert "expertgranskning/reports/rpt_eg/report.html" in keys
    assert "expertgranskning/reports/rpt_eg/report.slots.json" in keys
    assert "expertgranskning/reports/rpt_eg/report.expertgranskning.json" in keys


@pytest.mark.asyncio
async def test_store_report_artifacts_requires_json_sidecar(client_db, tmp_path):
    _client, factory = client_db
    out_dir = tmp_path / "rpt_empty"
    _write_report_dir(out_dir, sidecar_name=None)
    async with factory() as session:
        report = Report(
            id="rpt_empty",
            customer_id=TEST_CUSTOMER_ID,
            status="running",
            title="Tom",
            locale="sv",
            mode="quick",
            sources=[],
        )
        session.add(report)
        await session.flush()
        try:
            await store_report_artifacts(session, report, out_dir, module="politik")
        except ObjectStorageError as exc:
            assert "JSON sidecar" in str(exc)
        else:
            raise AssertionError("expected ObjectStorageError")
