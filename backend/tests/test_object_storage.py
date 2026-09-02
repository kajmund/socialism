from app.services.object_storage import (
    bucket_name,
    module_prefix,
    safe_filename,
    supabase_s3_endpoint,
    validate_annual_report,
)


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
